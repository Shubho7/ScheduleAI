from google.adk.tools import ToolContext
from .utils import NOT_CONNECTED_CODE, NOT_CONNECTED_MESSAGE, get_calendar_service

def delete_event(
    event_id: str,
    confirm: bool,
    tool_context: ToolContext,
) -> dict:
    """
    Delete an event from Google Calendar.

    Args:
        event_id (str): The unique ID of the event to delete
        confirm (bool): Confirmation flag (must be set to True to delete)

    Returns:
        dict: Operation status and details
    """
    if not confirm:
        return {
            "status": "error",
            "message": "Please confirm deletion by setting confirm=True",
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

        # Call the Calendar API to delete the event
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

        return {
            "status": "success",
            "message": f"Event {event_id} has been deleted successfully",
            "event_id": event_id,
        }

    except Exception as e:
        return {"status": "error", "message": f"Error deleting event: {str(e)}"}