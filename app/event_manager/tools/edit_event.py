from google.adk.tools import ToolContext
from .utils import (
    NOT_CONNECTED_CODE,
    NOT_CONNECTED_MESSAGE,
    get_calendar_service,
    parse_datetime,
    parse_email_list,
)
import re

def edit_event(
    event_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    tool_context: ToolContext,
    attendees: str = "",
) -> dict:
    """
    Edit an existing event in Google Calendar - change title, reschedule and/or change who is invited. Guests are emailed the updated invitation automatically.

    Args:
        event_id (str): The ID of the event to edit
        summary (str): New title/summary for the event (pass empty string to keep unchanged)
        start_time (str): New start time (e.g., "2023-12-31 14:00", pass empty string to keep unchanged)
        end_time (str): New end time (e.g., "2023-12-31 15:00", pass empty string to keep unchanged)
        attendees (str): The COMPLETE new guest list as comma-separated email addresses (e.g., "alex@gmail.com, sam@example.com"). Pass empty string to keep the guests unchanged.

    Returns:
        dict: Information about the edited event or error details
    """
    # An email address in the title means the guest was not added as an attendee
    if summary and re.search(r"\S+@\S+", summary):
        return {
            "status": "error",
            "message": "Do not put email addresses in the title. Use the `attendees` parameter for guests.",
        }

    new_emails, invalid_emails = parse_email_list(attendees)
    if invalid_emails:
        return {
            "status": "error",
            "message": f"These are not valid email addresses: {', '.join(invalid_emails)}. Ask the user to type the correct address.",
        }

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

        # Get the existing event
        try:
            event = (
                service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )
        except Exception:
            return {
                "status": "error",
                "message": f"Event with ID {event_id} not found in primary calendar.",
            }

        # Update the event with new values
        if summary:
            event["summary"] = summary

        # Get timezone from the original event
        timezone_id = "Asia/Kolkata"
        if "start" in event and "timeZone" in event["start"]:
            timezone_id = event["start"]["timeZone"]

        if start_time:
            start_dt = parse_datetime(start_time)
            if not start_dt:
                return {
                    "status": "error",
                    "message": "Invalid start time format. Please use YYYY-MM-DD HH:MM format.",
                }
            event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": timezone_id}

        if end_time:
            end_dt = parse_datetime(end_time)
            if not end_dt:
                return {
                    "status": "error",
                    "message": "Invalid end time format. Please use YYYY-MM-DD HH:MM format.",
                }
            event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": timezone_id}

        # Replace the guest list if a new one was given. Keep the organizer's own
        # entry, and keep the response status of guests who stay on the list.
        if new_emails:
            current = event.get("attendees", [])
            by_email = {a.get("email", "").lower(): a for a in current}
            kept = [a for a in current if a.get("organizer") or a.get("self")]
            kept_emails = {a.get("email", "").lower() for a in kept}
            guests = [
                by_email.get(e.lower(), {"email": e})
                for e in new_emails
                if e.lower() not in kept_emails
            ]
            event["attendees"] = kept + guests

        # Update the event. sendUpdates="all" makes Google email the guests the
        # updated invitation (without it, guests are never told about changes).
        # conferenceDataVersion=1 keeps the existing Google Meet link intact.
        updated_event = (
            service.events()
            .update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
                sendUpdates="all",
                conferenceDataVersion=1,
            )
            .execute()
        )

        guests_notified = [
            a.get("email")
            for a in updated_event.get("attendees", [])
            if a.get("email") and not (a.get("organizer") or a.get("self"))
        ]
        result = {
            "status": "success",
            "message": "Event updated successfully",
            "event_id": updated_event["id"],
            "event_link": updated_event.get("htmlLink", ""),
        }
        if guests_notified:
            result["guests_notified"] = guests_notified
        return result

    except Exception as e:
        return {"status": "error", "message": f"Error updating event: {str(e)}"}