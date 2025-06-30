import datetime
from .utils import get_calendar_service

def format_time_for_display(dt):
    """
    Format datetime for display in AM/PM format, following existing tools pattern.
    """
    if dt.tzinfo:
        return dt.strftime("%I:%M %p")
    else:
        return dt.strftime("%I:%M %p")

def parse_event_datetime(event_time_dict):
    """
    Parse event time dictionary from Google Calendar API into a datetime object.
    
    Args:
        event_time_dict (dict): Event time dictionary from Google Calendar API
        
    Returns:
        datetime: Parsed datetime object or None if parsing fails
    """
    try:
        if "dateTime" in event_time_dict:
            dt_str = event_time_dict["dateTime"]
            if dt_str.endswith("Z"):
                dt_str = dt_str.replace("Z", "+00:00")
            elif "+" not in dt_str and "-" not in dt_str[-6:]:
                dt_str = dt_str + "+00:00"
            return datetime.datetime.fromisoformat(dt_str)
        elif "date" in event_time_dict:
            date_str = event_time_dict["date"]
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        return None
    except Exception:
        return None

def find_free_time(
    start_date: str,
    days: int,
    start_hour: int = 9,
    end_hour: int = 2,
    min_duration: int = 30,
) -> dict:
    """
    Find available free time slots in Google Calendar within a specified date range.

    Args:
        start_date (str): Start date in YYYY-MM-DD format. If empty string, defaults to today.
        days (int): Number of days to look ahead. Use 1 for today only, 7 for a week, 30 for a month, etc.
        start_hour (int): Start of working hours (24-hour format, default: 9 AM)
        end_hour (int): End of working hours next day (24-hour format, default: 2 AM next day)
        min_duration (int): Minimum duration of free time slots in minutes (default: 30)

    Returns:
        dict: Information about available free time slots or error details
    """
    try:
        print("Finding free time")
        print("Start date: ", start_date)
        print("Days: ", days)
        print("Working hours: ", f"{start_hour}:00 - {end_hour}:00")
        print("Minimum duration: ", f"{min_duration} minutes")

        # Get calendar service
        service = get_calendar_service()
        if not service:
            return {
                "status": "error",
                "message": "Failed to authenticate with Google Calendar",
                "free_slots": [],
            }

        # Always use primary calendar
        calendar_id = "primary"

        if not start_date or start_date.strip() == "":
            start_time = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            print(f"Using current date: {start_time}")
        else:
            try:
                start_time = datetime.datetime.strptime(start_date, "%Y-%m-%d")
                print(f"Parsed start date: {start_time}")
            except ValueError:
                return {
                    "status": "error",
                    "message": f"Invalid date format: {start_date}. Use YYYY-MM-DD format.",
                    "free_slots": [],
                }

        if not days or days < 1:
            days = 1

        end_time = start_time + datetime.timedelta(days=days)

        time_min = start_time.isoformat() + "Z"
        time_max = end_time.isoformat() + "Z"

        # Call the Calendar API to get events
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=100,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])
        print(f"Retrieved {len(events)} total events from calendar API")

        # Find free time slots
        free_slots = []
        current_date = start_time.date()
        
        for day in range(days):
            day_date = current_date + datetime.timedelta(days=day)
            
            window_start = datetime.datetime.combine(day_date, datetime.time(start_hour, 0))
            
            if end_hour <= start_hour:
                next_day = day_date + datetime.timedelta(days=1)
                window_end = datetime.datetime.combine(next_day, datetime.time(end_hour, 0))
            else:
                window_end = datetime.datetime.combine(day_date, datetime.time(end_hour, 0))
            
            print(f"Search window: {window_start} → {window_end}")
            
            # Get events for this window
            window_events = []
            for event in events:
                event_start_dict = event.get("start", {})
                event_end_dict = event.get("end", {})
                
                start_dt = parse_event_datetime(event_start_dict)
                end_dt = parse_event_datetime(event_end_dict)
                
                if start_dt and end_dt:
                    if start_dt.tzinfo:
                        start_dt_utc = start_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                    else:
                        start_dt_utc = start_dt
                    
                    if end_dt.tzinfo:
                        end_dt_utc = end_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                    else:
                        end_dt_utc = end_dt
                    
                    if start_dt_utc < window_end and end_dt_utc > window_start:
                        window_events.append({
                            "start": start_dt,
                            "end": end_dt,
                            "start_utc": start_dt_utc,
                            "end_utc": end_dt_utc,
                            "summary": event.get("summary", "Untitled Event")
                        })
            
            window_events.sort(key=lambda x: x["start_utc"])
            
            print(f"Found {len(window_events)} events in window")
            for event in window_events:
                print(f"  Event: {event['summary']} ({event['start']} → {event['end']})")
            
            if not window_events:
                print("No events found - entire window is free")
                duration_minutes = int((window_end - window_start).total_seconds() / 60)
                if duration_minutes >= min_duration:
                    window_start_display = datetime.datetime.combine(day_date, datetime.time(start_hour, 0))
                    if end_hour <= start_hour:
                        next_day = day_date + datetime.timedelta(days=1)
                        window_end_display = datetime.datetime.combine(next_day, datetime.time(end_hour, 0))
                    else:
                        window_end_display = datetime.datetime.combine(day_date, datetime.time(end_hour, 0))
                    
                    free_slots.append({
                        "date": day_date.strftime("%Y-%m-%d"),
                        "start_time": format_time_for_display(window_start_display),
                        "end_time": format_time_for_display(window_end_display),
                        "duration_minutes": duration_minutes,
                        "formatted_duration": f"{duration_minutes // 60}h {duration_minutes % 60}m"
                    })
                    print(f"Added free slot: {format_time_for_display(window_start_display)} - {format_time_for_display(window_end_display)}")
            else:
                print(f"Processing {len(window_events)} events for gaps")
                
                # Check for free time before first event
                first_event_start_utc = window_events[0]["start_utc"]
                first_event_start_display = window_events[0]["start"]
                
                if window_start < first_event_start_utc:
                    duration_minutes = int((first_event_start_utc - window_start).total_seconds() / 60)
                    if duration_minutes >= min_duration:
                        window_start_display = datetime.datetime.combine(day_date, datetime.time(start_hour, 0))
                        
                        free_slots.append({
                            "date": day_date.strftime("%Y-%m-%d"),
                            "start_time": format_time_for_display(window_start_display),
                            "end_time": format_time_for_display(first_event_start_display),
                            "duration_minutes": duration_minutes,
                            "formatted_duration": f"{duration_minutes // 60}h {duration_minutes % 60}m"
                        })
                        print(f"Added free slot before first event: {format_time_for_display(window_start_display)} - {format_time_for_display(first_event_start_display)}")
                
                # Check for free time between events
                for i in range(len(window_events) - 1):
                    current_event_end_utc = window_events[i]["end_utc"]
                    current_event_end_display = window_events[i]["end"]
                    next_event_start_utc = window_events[i + 1]["start_utc"]
                    next_event_start_display = window_events[i + 1]["start"]
                    
                    if current_event_end_utc < next_event_start_utc:
                        duration_minutes = int((next_event_start_utc - current_event_end_utc).total_seconds() / 60)
                        if duration_minutes >= min_duration:
                            free_slots.append({
                                "date": day_date.strftime("%Y-%m-%d"),
                                "start_time": format_time_for_display(current_event_end_display),
                                "end_time": format_time_for_display(next_event_start_display),
                                "duration_minutes": duration_minutes,
                                "formatted_duration": f"{duration_minutes // 60}h {duration_minutes % 60}m"
                            })
                            print(f"Added free slot between events: {format_time_for_display(current_event_end_display)} - {format_time_for_display(next_event_start_display)}")
                
                # Check for free time after last event
                last_event_end_utc = window_events[-1]["end_utc"]
                last_event_end_display = window_events[-1]["end"]
                
                if last_event_end_utc < window_end:
                    duration_minutes = int((window_end - last_event_end_utc).total_seconds() / 60)
                    if duration_minutes >= min_duration:
                        if end_hour <= start_hour:
                            next_day = day_date + datetime.timedelta(days=1)
                            window_end_display = datetime.datetime.combine(next_day, datetime.time(end_hour, 0))
                        else:
                            window_end_display = datetime.datetime.combine(day_date, datetime.time(end_hour, 0))
                        
                        free_slots.append({
                            "date": day_date.strftime("%Y-%m-%d"),
                            "start_time": format_time_for_display(last_event_end_display),
                            "end_time": format_time_for_display(window_end_display),
                            "duration_minutes": duration_minutes,
                            "formatted_duration": f"{duration_minutes // 60}h {duration_minutes % 60}m"
                        })
                        print(f"Added free slot after last event: {format_time_for_display(last_event_end_display)} - {format_time_for_display(window_end_display)}")
            
            # Count slots for this specific day
            day_slots = [slot for slot in free_slots if slot["date"] == day_date.strftime("%Y-%m-%d")]
            print(f"Total free slots found for {day_date}: {len(day_slots)}")

        print(f"Overall total free slots found: {len(free_slots)}")
        
        if not free_slots:
            return {
                "status": "success",
                "message": f"No free time slots found for the specified period (minimum {min_duration} minutes).",
                "free_slots": [],
            }

        return {
            "status": "success",
            "message": f"Found {len(free_slots)} free time slot(s).",
            "free_slots": free_slots,
        }

    except Exception as e:
        print(f"Exception in find_free_time: {str(e)}")
        print(f"Exception type: {type(e).__name__}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "message": f"Error finding free time: {str(e)}",
            "free_slots": [],
        }
