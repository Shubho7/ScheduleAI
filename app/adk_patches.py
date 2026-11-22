"""Compatibility patches for google-adk 0.5.0 (the version pinned in requirements).

Call apply() once at startup. Each patch is small and documented; if ADK is
upgraded, re-check whether they are still needed.
"""

import logging
from typing import AsyncGenerator

from google.adk.flows.llm_flows import base_llm_flow
from google.adk.models import gemini_llm_connection
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)


def _patch_tracing() -> None:
    """Gemini 3.x returns a binary `thought_signature` on tool calls, and ADK's
    tracing json.dumps() the request, which fails on bytes and aborts the reply.
    Tracing is optional, so log failures instead of raising."""
    original = base_llm_flow.trace_call_llm

    def safe_trace_call_llm(*args, **kwargs):
        try:
            original(*args, **kwargs)
        except Exception as e:
            print(f"[TRACE SKIPPED]: {type(e).__name__}: {e}")

    base_llm_flow.trace_call_llm = safe_trace_call_llm


def _patch_live_context_compression() -> None:
    """Turn on context-window compression for Live sessions.

    Without it a long voice conversation eventually exceeds the model's context
    limit and the Live API closes the connection. A sliding window lets the
    session keep going by dropping the oldest turns first."""
    original_connect = Gemini.connect

    def connect_with_compression(self, llm_request):
        llm_request.live_connect_config.context_window_compression = (
            types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow())
        )
        return original_connect(self, llm_request)

    Gemini.connect = connect_with_compression


def _patch_live_receive() -> None:
    """Keep the model's private reasoning ("thought" parts) out of the saved text.

    ADK 0.5.0 appends every text part of a model turn, including thought
    summaries, to the text it later saves into the session history as "what the
    agent said". After a reconnect that history is replayed to the model, so the
    agent saw its own reasoning notes as part of the conversation and lost track
    of what was really said. This is ADK's GeminiLlmConnection.receive() with one
    change: thought parts are not accumulated."""

    async def receive(self) -> AsyncGenerator[LlmResponse, None]:
        build_full_text = self._GeminiLlmConnection__build_full_text_response

        text = ""
        async for message in self._gemini_session.receive():
            logger.debug("Got LLM Live message: %s", message)
            if message.server_content:
                content = message.server_content.model_turn
                if content and content.parts:
                    llm_response = LlmResponse(
                        content=content, interrupted=message.server_content.interrupted
                    )
                    first = content.parts[0]
                    if first.text:
                        if not first.thought:  # <-- the change
                            text += first.text
                        llm_response.partial = True
                    # don't yield the merged text event when receiving audio data
                    elif text and not first.inline_data:
                        yield build_full_text(text)
                        text = ""
                    yield llm_response
                if (
                    message.server_content.input_transcription
                    and message.server_content.input_transcription.text
                ):
                    user_text = message.server_content.input_transcription.text
                    yield LlmResponse(
                        content=types.Content(
                            role="user", parts=[types.Part.from_text(text=user_text)]
                        )
                    )
                if (
                    message.server_content.output_transcription
                    and message.server_content.output_transcription.text
                ):
                    # Transcription is always a partial event; the merged full text
                    # is yielded on turn_complete, interruption or a tool call.
                    chunk = message.server_content.output_transcription.text
                    text += chunk
                    yield LlmResponse(
                        content=types.Content(
                            role="model", parts=[types.Part.from_text(text=chunk)]
                        ),
                        partial=True,
                    )

                if message.server_content.turn_complete:
                    if text:
                        yield build_full_text(text)
                        text = ""
                    yield LlmResponse(
                        turn_complete=True,
                        interrupted=message.server_content.interrupted,
                    )
                    break
                # an interrupted message merges the previous partial text
                if message.server_content.interrupted and text:
                    yield build_full_text(text)
                    text = ""
                yield LlmResponse(interrupted=message.server_content.interrupted)
            if message.tool_call:
                if text:
                    yield build_full_text(text)
                    text = ""
                parts = [
                    types.Part(function_call=function_call)
                    for function_call in message.tool_call.function_calls
                ]
                yield LlmResponse(content=types.Content(role="model", parts=parts))

    gemini_llm_connection.GeminiLlmConnection.receive = receive


_applied = False


def apply() -> None:
    global _applied
    if _applied:
        return
    _patch_tracing()
    _patch_live_context_compression()
    _patch_live_receive()
    _applied = True
