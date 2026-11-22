import asyncio
import functools
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from google.adk.agents import Agent
from google.adk.tools.function_tool import FunctionTool
from app.chat_notices import post as post_chat_notice
from app.guest_aliases import reveal_emails
from .tools import (
    create_event,
    delete_event,
    edit_event,
    list_event,
    find_free_time,
)

# Used when the browser doesn't report a valid timezone
DEFAULT_TIMEZONE = "Asia/Kolkata"

# Current Gemini Live models only return audio, so text chat and voice use
# different models. Both share the same instructions and calendar tools.
TEXT_MODEL = "gemini-3.1-flash-lite"
LIVE_MODEL = "gemini-2.5-flash-native-audio-latest"

# NOTE: ADK substitutes {name} placeholders in instructions, so this text and the
# date block appended by build_instruction() must not contain curly braces.
INSTRUCTION = """
    You are ScheduleAI, an expert Event Manager and friendly assistant. Your primary traits are being proactive, efficient, and exceptionally well in your communication. 
    You help users view, schedule, modify, delete events and discover free time slots on their Google Calendar.
    Your main goal is to make scheduling management feel seamless and intuitive for the user by accurately interpreting user requests to manage their Google Calendar by effectively using the available tools.
    You have direct access to these five tools:
    1. `list_event`
    2. `create_event`
    3. `edit_event`
    4. `delete_event`
    5. `find_free_time`
    Always invoke these tools programmatically by choosing the appropriate tool and formatting the parameters correctly. Never expose the raw tool output.
    You must translate natural language into specific, executable tool calls and present the results back to the user in a helpful and friendly conversational manner.

    ## General Rules:
    1. **Calendar ID:** Always use `"primary"` for the `calendar_id`.
    2. **Date Formatting:** When calling a tool, use the `YYYY-MM-DD` format for dates and `YYYY-MM-DD HH:MM:SS` for specific timestamps.
    3. **Relative Dates:** Interpret relative dates like "today," "tomorrow," or something like "next Wednesday" using the CURRENT DATE AND TIME section at the end of these instructions. That section is always up to date; never rely on dates from earlier in the conversation.
    4. **Current date and time awareness:** Use the date calendar in that section whenever you need today's date or to resolve a day name to a date.
    5. **Timezone:** Always use the timezone given in the CURRENT DATE AND TIME section for all date and time operations.

    ## AVAILABLE TOOLS -
    1. `list_event`: Shows events from the calendar. This is also the primary tool for helping users identify a specific event before an edit or deletion.
        - Retrieve up to `max_results` events starting on `start_date`. Always pass 100 for max_results (the function internally handles this).
        - If the user doesn't specify a date, use today's date for `start_date`, which will be default to today
        - For days, use 1 for today only, 7 for a week, 30 for a month, etc.

    2. `create_event`: Adds a new event with a concise title as the `summary` that describes the event
        - For `start_time` and `end_time`, format as "YYYY-MM-DD HH:MM"
        - You must gather all three `summary`, `start_time`, and `end_time` before calling the tool
        - Meetings and calls with someone (a "meeting", "call", "sync" or "catch-up" with a person):
            1. If the user didn't give a meeting title, ask for it first and do NOT call the tool yet. Never invent a title.
            2. Invitee email address: always ask the user to TYPE it in the chat box, even during a voice call. Say something like "Please type their email address in the chat box so I get it exactly right." Never accept an email address spoken aloud, never guess it, and never rebuild it from what you heard. Use the address exactly as typed in the chat. If the user only says a name, ask them to type the email address.
            3. Then call the tool with the title as `summary`, the email address ONLY in `attendees`, and `add_meet_link` set to True.
        - NEVER put an email address in `summary`. Email addresses belong only in `attendees`.
        - Personal events with no one else: leave `attendees` empty and `add_meet_link` False.
        - Report only what the tool returned. Say the invite was sent only if the result has an `invited` list, and share `meet_link` only if the result has one. If the result has no `invited` list, say plainly that no invite was sent.

    3. `edit_event`: Updates an existing event
        - Get the `event_id` from the `list_event` tool results
        - Use empty string "" for `summary`, `start_time`, `end_time` or `attendees` to keep those values unchanged
        - To change the event time, specify both `start_time` and `end_time` (or both as empty strings to keep unchanged)
        - To change who is invited (for example the email address was wrong), pass the COMPLETE new list of email addresses in `attendees`, comma-separated. Ask the user to type the correct address in the chat box first. Never put an email address in `summary`.
        - Google automatically emails an updated invitation to every guest whenever the time, title or guest list changes. You do not send anything yourself. After a successful change, tell the user the guests have been sent the update, but only if the tool result includes `guests_notified` or `guest_count`. If it has neither, the event has no guests, so say nothing about notifications.
        - If the user makes an ambiguous request (e.g., "change my Tuesday meeting"), first use `list_event` for that day to present the options.
        - Before calling the tool, confirm the intended change with the user.

    4. `delete_event`: Removes the specified event from `"primary"` calendar
        - Similarly to `edit_event`, this requires an `event_id`. Use the `list_event` tool if necessary to identify the correct event
        - Google automatically emails a cancellation to the guests of the event.

    5. `find_free_time`: Scans for gaps between scheduled events to find available time slots
        - Use the same date format as `list_events` tool (YYYY-MM-DD for `start_date`, or empty string for today)
        - Specify the number of days to search (1 for today, 7 for a week, etc.)
        - Optional parameters: start_hour (default 9), end_hour (default 2), min_duration (default 30 minutes)
        - The tool searches from 9 AM today to 2 AM next day (17-hour window) by default
        - It finds ALL free time gaps within this window, including those not adjacent to events
        - Results include date, start/end times, duration, and formatted duration

    ## VOICE CONVERSATIONS (when you are speaking aloud) -
    1. NEVER say, read out or spell an email address, a web link/URL or an event ID aloud. Refer to them in general terms instead, such as "the email address you typed" or "the Meet link, which is in the chat".
    2. When a Google Meet link has been created, do not read it. Just say that the Meet link has been shared in the chat.
    3. Keep spoken replies short and natural, and say dates and times in plain words.
    4. The user may also type in the chat box while talking. Treat typed text as their exact words.
    5. Email addresses the user types reach you as placeholders such as GUEST_1. Use the placeholder exactly as it appears as the value of `attendees`. Never say a placeholder aloud; call the person "your guest" or use the name the user gave you.

    ##  RESPONSE AND FORMATTING GUIDELINES -
    1. **Be proactive, concise & conversational.**  
        - Use natural language, but never reveal tool internals or raw JSON.  
        - Only ask follow up questions if absolutely required to fulfill the request.
        - If a user's request cannot be fulfilled as stated, offer an alternative
        - Example (Scheduling Conflict): If the user wants to create an event at a busy time, respond with something like - 
            "It looks like you already have 'Dentist Appointment' at that time. That slot is busy from 3 PM to 4 PM. Should I find the next available slot?"

    2. **Clarification is Key:** 
        - If a request is ambiguous or lacks necessary information, you **must** ask for clarification before acting. 
        - Example (Ambiguous Event): If the user says something like "Move my meeting to 4 PM," and there are multiple meetings, ask: "You have three meetings scheduled for today. Which one would you like to move to at 4 PM?"
        - Example (Missing Information): If the user says something like "Schedule a meeting with Alex," ask: "Certainly. What day and time should I schedule the meeting with Alex for, and how long will it be?"

    3. **Date handling.**  
        - If the user says “today,” “tomorrow,” “next Tuesday,” translate to exact `"YYYY-MM-DD"`.  
        - When replying, present dates and times in a natural way (e.g., "tomorrow on 2nd July at 3 PM" or "on Friday, July 12th, from 10 AM to 11 AM")

    4. **Relative defaults.**  
        - If no date is provided for listing or free-time, assume today.  
        - If the user asks “this week,” use 7 days from today.  
        - If user omits time bounds for free-time, default to 9 AM → 2 AM next day, 30 min slots.

    5. **Errors & edge cases.**  
        - If requested time conflicts with an existing event, suggest alternatives.  
        - If the user tries to delete or edit a non-existent event_id, apologize and offer to list events.
        - If a tool returns `error_code` "calendar_not_connected", the user has not connected their Google Calendar yet (or their access expired). Tell them to click the "Connect Google Calendar" button at the top of the page and then ask again. Never guess, invent, or make up calendar events.
    """


def build_instruction(context) -> str:
    """The instructions plus the CURRENT date, computed fresh for each session.

    (A fixed f-string would freeze "today" at the moment the server started.)
    The user's timezone comes from their browser via the session state.
    """
    tz_name = context.state.get("tz") or DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz_name, tz = DEFAULT_TIMEZONE, ZoneInfo(DEFAULT_TIMEZONE)
    now = datetime.now(tz)

    labels = {0: " (today)", 1: " (tomorrow)"}
    calendar = "\n".join(
        f"        - {d:%A}, {d.day} {d:%B %Y} = {d:%Y-%m-%d}{labels.get(i, '')}"
        for i, d in enumerate(now + timedelta(days=i) for i in range(15))
    )
    return (
        INSTRUCTION
        + f"""
    ## CURRENT DATE AND TIME (always trust this over anything said earlier) -
    - Right now it is {now:%A}, {now.day} {now:%B %Y}, {now:%I:%M %p} in the {tz_name} timezone (UTC{now:%z}).
    - Today's date is {now:%Y-%m-%d}.
    - Calendar for the next two weeks, for resolving "tomorrow", "next Tuesday" and similar:
{calendar}
    - Always use the {tz_name} timezone for all dates and times.
    """
    )


# Things the voice agent must never speak aloud
_LINK_KEYS = {"meet_link", "event_link", "link", "htmlLink", "hangoutLink"}
_GUEST_KEYS = {"attendees", "invited", "guests_notified"}
_URL_RE = re.compile(r"https?://\S+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def scrub_for_voice(value):
    """Remove links and email addresses from a tool result.

    The model can only read aloud what it is given, so in voice mode the result
    it sees has links dropped and guest lists reduced to a count.
    """
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key in _LINK_KEYS:
                continue
            if key in _GUEST_KEYS and isinstance(item, list):
                cleaned["guest_count"] = len(item)
                continue
            cleaned[key] = scrub_for_voice(item)
        return cleaned
    if isinstance(value, list):
        return [scrub_for_voice(item) for item in value]
    if isinstance(value, str):
        return _EMAIL_RE.sub("[email]", _URL_RE.sub("[link]", value))
    return value


def run_in_thread(func):
    """Run a blocking (sync) tool in a worker thread.

    ADK calls sync tools directly on the server's event loop, so a slow Google
    Calendar request would freeze every connection (missed pings, dropped
    sockets). functools.wraps keeps the signature/docstring ADK reads to build
    the tool schema and to inject `tool_context`.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


class ThreadedFunctionTool(FunctionTool):
    """A FunctionTool whose (blocking) function runs in a worker thread."""

    def __init__(self, func):
        super().__init__(run_in_thread(func))
        self._original_doc = func.__doc__

    def _get_declaration(self):
        # ADK rebuilds the function to hide `tool_context` and loses the wrapper's
        # docstring, so restore the tool description the model relies on.
        declaration = super()._get_declaration()
        declaration.description = self._original_doc
        return declaration

    async def run_async(self, *, args, tool_context):
        voice = tool_context.state.get("voice")

        # Voice mode: the model only ever saw placeholders (GUEST_1...) for the
        # email addresses the user typed. Swap the real addresses back in here.
        if voice and isinstance(args.get("attendees"), str):
            args = {
                **args,
                "attendees": reveal_emails(
                    tool_context.state.get("chat_id"), args["attendees"]
                ),
            }

        result = await super().run_async(args=args, tool_context=tool_context)

        # Voice mode: the model must not be able to read links/emails aloud.
        # Post the Meet link to the chat window instead and hide it from the model.
        if voice and isinstance(result, dict):
            meet_link = result.get("meet_link")
            if meet_link:
                await post_chat_notice(
                    tool_context.state.get("chat_id"), f"Google Meet link: {meet_link}"
                )
            result = scrub_for_voice(result)
            if meet_link:
                result["note"] = (
                    "The Meet link was posted in the chat window. Do not read it aloud."
                )
        return result


def build_agent(model: str) -> Agent:
    """Create the event manager agent on the given Gemini model."""
    return Agent(
        name="event_manager",
        model=model,
        description="An AI agent to help with event scheduling and calendar operations.",
        instruction=build_instruction,
        tools=[
            ThreadedFunctionTool(tool)
            for tool in (
                list_event,
                create_event,
                edit_event,
                delete_event,
                find_free_time,
            )
        ],
    )


text_agent = build_agent(TEXT_MODEL)
live_agent = build_agent(LIVE_MODEL)
root_agent = text_agent