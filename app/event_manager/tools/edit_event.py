from .utils import get_calendar_service, parse_datetime

def edit_event(
    event_id: str,
    summary: str,
    start_time: str,
    end_time: str,
) -> dict:
    """
    Edit an existing event in Google Calendar - change title and/or reschedule.

    Args:
        event_id (str): The ID of the event to edit
        summary (str): New title/summary for the event (pass empty string to keep unchanged)
        start_time (str): New start time (e.g., "2023-12-31 14:00", pass empty string to keep unchanged)
        end_time (str): New end time (e.g., "2023-12-31 15:00", pass empty string to keep unchanged)

    Returns:
        dict: Information about the edited event or error details
    """
    try:
        # Get calendar service
        service = get_calendar_service()
        if not service:
            return {
                "status": "error",
                "message": "Failed to authenticate with Google Calendar",
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

        # Update the event
        updated_event = (
            service.events()
            .update(calendarId=calendar_id, eventId=event_id, body=event)
            .execute()
        )

        return {
            "status": "success",
            "message": "Event updated successfully",
            "event_id": updated_event["id"],
            "event_link": updated_event.get("htmlLink", ""),
        }

    except Exception as e:
        return {"status": "error", "message": f"Error updating event: {str(e)}"}