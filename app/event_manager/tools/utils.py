import re
from datetime import datetime
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from app.google_auth import REFRESH_TOKEN_KEY, SCOPES, TOKEN_URI, client_credentials

# Returned by every tool when the visitor hasn't connected (or must reconnect).
NOT_CONNECTED_MESSAGE = (
    "Google Calendar is not connected. Ask the user to click the "
    "'Connect Google Calendar' button at the top of the page, then try again."
)
NOT_CONNECTED_CODE = "calendar_not_connected"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_email_list(text):
    """Split a comma-separated string of email addresses.

    Returns:
        (valid_emails, invalid_entries)
    """
    entries = [e.strip() for e in (text or "").split(",") if e.strip()]
    valid = [e for e in entries if EMAIL_RE.match(e)]
    invalid = [e for e in entries if not EMAIL_RE.match(e)]
    return valid, invalid


def get_calendar_service(tool_context):
    """
    Create a Google Calendar service for the user of this chat session.

    The user's refresh token is placed in the session state when their
    WebSocket connects (from their own encrypted cookie).

    Args:
        tool_context: The ADK ToolContext passed to the calling tool.

    Returns:
        A Google Calendar service object, or None if the user has not connected
        their calendar or their access was revoked/expired.
    """
    refresh_token = tool_context.state.get(REFRESH_TOKEN_KEY)
    client_id, client_secret = client_credentials()
    if not (refresh_token and client_id and client_secret):
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except RefreshError as e:
        # Revoked, or expired (tokens last ~7 days while the OAuth app is in Testing)
        print(f"[AUTH] refresh failed: {e}")
        return None

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def format_event_time(event_time):
    """
    Format an event time into a human-readable string.

    Args:
        event_time (dict): The event time dictionary from Google Calendar API

    Returns:
        str: A human-readable time string
    """
    if "dateTime" in event_time:
        
        dt = datetime.fromisoformat(event_time["dateTime"].replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %I:%M %p")
    elif "date" in event_time:
        return f"{event_time['date']} (All day)"
    return "Unknown time format"

def parse_datetime(datetime_str):
    """
    Parse a datetime string into a datetime object.

    Args:
        datetime_str (str): A string representing a date and time

    Returns:
        datetime: A datetime object or None if parsing fails
    """
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y",
        "%B %d, %Y %H:%M",
        "%B %d, %Y %I:%M %p",
        "%B %d, %Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(datetime_str, fmt)
        except ValueError:
            continue

    return None

def get_current_time() -> dict:
    """
    Get the current time and date
    """
    now = datetime.now()

    # Format date as MM-DD-YYYY
    formatted_date = now.strftime("%m-%d-%Y")

    return {
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "formatted_date": formatted_date,
    }