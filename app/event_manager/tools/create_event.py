import datetime
import re
import uuid
from google.adk.tools import ToolContext
from .utils import (
    NOT_CONNECTED_CODE,
    NOT_CONNECTED_MESSAGE,
    get_calendar_service,
    parse_datetime,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    tool_context: ToolContext,
    attendees: str = "",
    add_meet_link: bool = False,
) -> dict:
    """
    Create a new event in Google Calendar, optionally inviting people and adding a Google Meet link.

    Args:
        summary (str): Event title/summary
        start_time (str): Start time (e.g., "2023-12-31 14:00")
        end_time (str): End time (e.g., "2023-12-31 15:00")
        attendees (str): Comma-separated email addresses of people to invite (e.g., "alex@gmail.com, sam@example.com"). Leave empty for a personal event. Google emails each invitee.
        add_meet_link (bool): Set to True to add a Google Meet video link. Use True when scheduling a meeting with someone.

    Returns:
        dict: Information about the created event or error details
    """
    try:
        # Get calendar service
        service = get_calendar_service(tool_context)
        if not service:
            return {
                "status": "error",
                "error_code": NOT_CONNECTED_CODE,
                "message": NOT_CONNECTED_MESSAGE,
            }

        # Always use primary calendar
        calendar_id = "primary"

        # Parse time
        start_dt = parse_datetime(start_time)
        end_dt = parse_datetime(end_time)

        if not start_dt or not end_dt:
            return {
                "status": "error",
                "message": "Invalid date/time format. Please use YYYY-MM-DD HH:MM format.",
            }

        # Default timezone
        timezone_id = "Asia/Kolkata"

        try:
            # Get the timezone from the calendar settings
            settings = service.settings().list().execute()
            for setting in settings.get("items", []):
                if setting.get("id") == "timezone":
                    timezone_id = setting.get("value")
                    break
        except Exception:
            pass

        # Create event body without type annotations
        event_body = {}

        # Add summary
        event_body["summary"] = summary

        # Add start and end times with the determined timezone
        event_body["start"] = {
            "dateTime": start_dt.isoformat(),
            "timeZone": timezone_id,
        }
        event_body["end"] = {"dateTime": end_dt.isoformat(), "timeZone": timezone_id}

        # Invitees: validate every address before creating anything
        emails = [e.strip() for e in (attendees or "").split(",") if e.strip()]
        invalid = [e for e in emails if not EMAIL_RE.match(e)]
        if invalid:
            return {
                "status": "error",
                "message": f"These are not valid email addresses: {', '.join(invalid)}. Ask the user for the correct address.",
            }
        if emails:
            event_body["attendees"] = [{"email": e} for e in emails]

        insert_kwargs = {"calendarId": calendar_id, "body": event_body}

        # Google Meet link: Google requires a request id so retries don't create duplicate links
        if add_meet_link:
            event_body["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
            insert_kwargs["conferenceDataVersion"] = 1

        # Email invitations to attendees (Google sends the normal invite)
        if emails:
            insert_kwargs["sendUpdates"] = "all"

        # Call the Calendar API to create the event
        event = service.events().insert(**insert_kwargs).execute()

        meet_link = event.get("hangoutLink", "")
        result = {
            "status": "success",
            "message": "Event created successfully",
            "event_id": event["id"],
            "event_link": event.get("htmlLink", ""),
        }
        if emails:
            result["invited"] = emails
        if meet_link:
            result["meet_link"] = meet_link
        return result

    except Exception as e:
        return {"status": "error", "message": f"Error creating event: {str(e)}"}