import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Path for token storage
TOKEN_PATH = Path(os.path.expanduser("~/.credentials/calendar_token.json"))
CREDENTIALS_PATH = Path("credentials.json")

# OAuth setup
def setup_oauth():
    print("\n=== Google Calendar OAuth Setup ===\n")

    if not CREDENTIALS_PATH.exists():
        print(f"Error: {CREDENTIALS_PATH} not found!")
        return False

    print(f"Found credentials.json. Setting up OAuth flow...")

    try:
        # Run the OAuth flow
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)

        # Save the credentials
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())

        print(f"\nSuccessfully saved credentials to {TOKEN_PATH}")

        print("\nTesting Google Calendar API connection...")
        service = build("calendar", "v3", credentials=creds)
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get("items", [])

        if calendars:
            print(f"\nSuccess! Found {len(calendars)} calendars:")
            for calendar in calendars:
                print(f"- {calendar['summary']} ({calendar['id']})")
        else:
            print(
                "\nConnected to Google Calendar API, but no calendars found."
            )

        print(
            "\nOAuth setup complete!"
        )
        return True

    except Exception as e:
        print(f"\nError during setup: {str(e)}")
        return False

if __name__ == "__main__":
    setup_oauth()