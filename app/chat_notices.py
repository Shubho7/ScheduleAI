"""Post messages straight into a user's chat window, bypassing the voice agent.

In voice mode the agent must not read links or email addresses aloud, so tools
send things like the Google Meet link here instead. The text shows up in the
chat (role "info", no speaker icon) but the model never speaks it.
"""

import json
from typing import Optional

from fastapi import WebSocket

_sockets: dict[str, WebSocket] = {}


def register(chat_id: str, websocket: WebSocket) -> None:
    _sockets[chat_id] = websocket


def unregister(chat_id: str, websocket: WebSocket) -> None:
    # Only remove our own entry: a reconnect may already have registered a new socket
    if _sockets.get(chat_id) is websocket:
        del _sockets[chat_id]


async def post(chat_id: Optional[str], text: str) -> None:
    """Show `text` in the chat of the given session, if that user is connected."""
    websocket = _sockets.get(chat_id) if chat_id else None
    if not websocket:
        return
    try:
        await websocket.send_text(
            json.dumps({"mime_type": "text/plain", "role": "info", "data": text})
        )
    except Exception as e:
        print(f"[NOTICE] could not post to chat: {type(e).__name__}")
