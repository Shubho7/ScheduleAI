import asyncio
import base64
import json
import os
import traceback
import uuid
from pathlib import Path
from typing import AsyncIterable, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from app import adk_patches, chat_notices
from app.guest_aliases import hide_emails
from app.event_manager.agent import live_agent, text_agent
from app.google_auth import (
    REFRESH_TOKEN_KEY,
    get_refresh_token,
    make_resume_token,
    read_resume_token,
)
from app.google_auth import router as auth_router

load_dotenv()

# Fixes for google-adk 0.5.0 (see app/adk_patches.py)
adk_patches.apply()

APP_NAME = "ScheduleAI"
session_service = InMemorySessionService()


def valid_timezone(name: Optional[str]) -> Optional[str]:
    """The IANA timezone name if it is valid (e.g. "Asia/Kolkata"), else None."""
    if not name:
        return None
    try:
        ZoneInfo(name)
        return name
    except Exception:
        return None

# Text chat uses a regular Gemini model (Live models only return audio).
text_runner = Runner(
    app_name=APP_NAME,
    agent=text_agent,
    session_service=session_service,
)

def start_agent_session(session_id, is_audio=False, state=None):
    """Starts an agent session"""

    # Reuse the session when the page reconnects (keeps the conversation context);
    # otherwise create one (state carries this user's Google Calendar login)
    session = session_service.get_session(
        app_name=APP_NAME, user_id=session_id, session_id=session_id
    ) or session_service.create_session(
        app_name=APP_NAME,
        user_id=session_id,
        session_id=session_id,
        state=state,
    )

    # Create a Runner
    runner = Runner(
        app_name=APP_NAME,
        agent=live_agent,
        session_service=session_service,
    )

    # Live models only return audio
    modality = "AUDIO"

    # Speech config
    speech_config = types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
        )
    )

    config = {
        "response_modalities": [modality],
        "speech_config": speech_config,
        # Transcribe both sides. The user's spoken words are saved into the
        # session history too, so the conversation can be restored after a
        # reconnect (without this the agent only remembered its own side).
        "output_audio_transcription": {},
        "input_audio_transcription": {},
    }

    run_config = RunConfig(**config)

    live_request_queue = LiveRequestQueue()

    # Start agent session
    live_events = runner.run_live(
        session=session,
        live_request_queue=live_request_queue,
        run_config=run_config,
    )
    return live_events, live_request_queue


async def agent_to_client_messaging(
    websocket: WebSocket, live_events: AsyncIterable[Event | None]
):
    """Agent to client communication"""
    # The event stream lasts for the whole session. When it ends (e.g. the Live
    # API closed the session) this function returns so the connection can be
    # re-established; looping on an exhausted stream would spin the CPU.
    async for event in live_events:
        if event is None:
            continue

        if event.turn_complete or event.interrupted:
            message = {
                "turn_complete": event.turn_complete,
                "interrupted": event.interrupted,
            }
            await websocket.send_text(json.dumps(message))
            print(f"[AGENT TO CLIENT]: {message}")
            continue

        part = event.content and event.content.parts and event.content.parts[0]
        if not part:
            continue

        if not isinstance(part, types.Part):
            continue

        # `part.thought` marks the model's internal reasoning summaries; only
        # the words it actually speaks (the audio transcript) go to the chat.
        if part.text and event.partial and not part.thought:
            message = {
                "mime_type": "text/plain",
                "data": part.text,
                "role": "model",
            }
            await websocket.send_text(json.dumps(message))
            print(f"[AGENT TO CLIENT]: text/plain: {part.text}")

        # If it's audio, send Base64 encoded audio data
        is_audio = (
            part.inline_data
            and part.inline_data.mime_type
            and part.inline_data.mime_type.startswith("audio/pcm")
        )
        if is_audio:
            audio_data = part.inline_data and part.inline_data.data
            if audio_data:
                message = {
                    "mime_type": "audio/pcm",
                    "data": base64.b64encode(audio_data).decode("ascii"),
                    "role": "model",
                }
                await websocket.send_text(json.dumps(message))


async def client_to_agent_messaging(
    websocket: WebSocket, live_request_queue: LiveRequestQueue, chat_id: str
):
    """Client to agent communication"""
    while True:
        # Decode JSON message
        message_json = await websocket.receive_text()
        message = json.loads(message_json)
        mime_type = message["mime_type"]

        # Heartbeat from the page: keeps the connection from going idle
        if mime_type == "ping":
            await websocket.send_text(json.dumps({"pong": True}))
            continue

        data = message["data"]
        role = message.get("role", "user")

        # Send the message to the agent
        if mime_type == "text/plain":
            # The voice model must never see (and so never read out) an email
            # address: replace typed addresses with placeholders. The tools swap
            # the real address back in when they call Google.
            data = hide_emails(chat_id, data)
            content = types.Content(role=role, parts=[types.Part.from_text(text=data)])
            live_request_queue.send_content(content=content)

            # ADK does not save typed messages of a live session into its history,
            # so after a reconnect the agent would not know them. Save it ourselves.
            saved = session_service.get_session(
                app_name=APP_NAME, user_id=chat_id, session_id=chat_id
            )
            if saved:
                session_service.append_event(
                    session=saved, event=Event(author="user", content=content)
                )
            print(f"[CLIENT TO AGENT PRINT]: {data}")
        elif mime_type == "audio/pcm":
            # Send audio data
            decoded_data = base64.b64decode(data)

            live_request_queue.send_realtime(
                types.Blob(data=decoded_data, mime_type=mime_type)
            )

        else:
            raise ValueError(f"Mime type not supported: {mime_type}")


async def text_chat_messaging(websocket: WebSocket, session_id: str, state: dict):
    """Text mode: one request/response turn per user message."""
    # Reuse the session when the page reconnects, so the conversation continues
    session = session_service.get_session(
        app_name=APP_NAME, user_id=session_id, session_id=session_id
    ) or session_service.create_session(
        app_name=APP_NAME, user_id=session_id, session_id=session_id, state=state
    )

    while True:
        message = json.loads(await websocket.receive_text())
        if message.get("mime_type") == "ping":
            await websocket.send_text(json.dumps({"pong": True}))
            continue
        if message.get("mime_type") != "text/plain":
            continue

        content = types.Content(
            role="user", parts=[types.Part.from_text(text=message["data"])]
        )
        print(f"[CLIENT TO AGENT PRINT]: {message['data']}")

        try:
            async for event in text_runner.run_async(
                user_id=session.user_id,
                session_id=session.id,
                new_message=content,
            ):
                if not (event.is_final_response() and event.content and event.content.parts):
                    continue
                text = "".join(
                    p.text for p in event.content.parts if p.text and not p.thought
                )
                if text:
                    await websocket.send_text(
                        json.dumps(
                            {"mime_type": "text/plain", "data": text, "role": "model"}
                        )
                    )
                    print(f"[AGENT TO CLIENT]: text/plain: {text}")
        except Exception as e:
            # Report the failure in the chat instead of dropping the connection
            print(f"[AGENT ERROR]: {type(e).__name__}: {e}")
            traceback.print_exc()
            await websocket.send_text(
                json.dumps(
                    {
                        "mime_type": "text/plain",
                        "data": "Sorry, something went wrong. Please try again.",
                        "role": "model",
                    }
                )
            )

        await websocket.send_text(
            json.dumps({"turn_complete": True, "interrupted": False})
        )


app = FastAPI()
app.include_router(auth_router)

STATIC_DIR = Path("app/static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    """Serves the index.html"""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    is_audio: str = Query(...),
    resume: Optional[str] = Query(None),
    tz: Optional[str] = Query(None),
):
    """Client websocket endpoint"""

    # Only accept connections from our own pages (the cookie carries the user's
    # calendar login, so don't let other websites open a socket on their behalf).
    origin = websocket.headers.get("origin")
    if origin and urlparse(origin).netloc != websocket.headers.get("host"):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # This visitor's own Google Calendar login, from their encrypted cookie
    refresh_token = get_refresh_token(websocket.cookies)

    # The chat id is server-generated (never the client's guessable one). When the
    # page reconnects it sends back a resume token that only this server can issue
    # and that is bound to this user's login, so the conversation continues.
    resumed_id = read_resume_token(resume, refresh_token)
    conn_id = resumed_id or uuid.uuid4().hex
    resumed = resumed_id is not None
    token = make_resume_token(conn_id, refresh_token)
    if token:
        await websocket.send_text(json.dumps({"session_token": token}))

    use_audio = is_audio == "true"
    # Text and voice keep separate conversation histories
    chat_id = f"{conn_id}-{'v' if use_audio else 't'}"

    # Session state the agent and its tools can read
    state = {"chat_id": chat_id, "voice": use_audio}
    if refresh_token:
        state[REFRESH_TOKEN_KEY] = refresh_token
    user_timezone = valid_timezone(tz)
    if user_timezone:
        state["tz"] = user_timezone  # the browser's timezone, for "today"/"tomorrow"

    print(
        f"Client #{session_id} connected as {conn_id[:8]} ({'voice' if use_audio else 'text'}, "
        f"resume token {'accepted' if resumed else 'not used'}), "
        f"calendar connected: {bool(refresh_token)}, timezone: {user_timezone or 'default'}"
    )

    # Lets tools post messages (e.g. the Meet link) straight into this chat
    chat_notices.register(chat_id, websocket)

    try:
        if use_audio:
            # Voice mode: streaming Live API session
            live_events, live_request_queue = start_agent_session(
                chat_id, True, state=state
            )

            agent_to_client_task = asyncio.create_task(
                agent_to_client_messaging(websocket, live_events)
            )
            client_to_agent_task = asyncio.create_task(
                client_to_agent_messaging(websocket, live_request_queue, chat_id)
            )
            # Stop as soon as either side ends, instead of waiting forever on the other
            done, pending = await asyncio.wait(
                {agent_to_client_task, client_to_agent_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                error = task.exception()
                if error:
                    raise error
            # The agent's stream ended (e.g. the Live API closed the session):
            # close so the page reconnects and resumes
            await websocket.close(code=1011)
        else:
            await text_chat_messaging(websocket, chat_id, state)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] connection ended by {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        chat_notices.unregister(chat_id, websocket)

    print(f"Client #{session_id} disconnected")