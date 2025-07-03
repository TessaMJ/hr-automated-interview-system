# /interview_management_system/utils.py

import logging
import re
import pickle
import os.path
from datetime import datetime, timedelta,timezone
import pytz
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from dateutil.parser import parse as dateutil_parse
from typing import Dict, Any, List, Optional,Set
from interview_management_system.config import (
    GOOGLE_CLIENT_SECRET_FILE,
    GOOGLE_TOKEN_FILE,
    GOOGLE_API_SCOPES
)

logger = logging.getLogger(__name__)

def normalize_phone_number(phone_number: str) -> str:
    cleaned = re.sub(r'\D', '', phone_number)
    if len(cleaned) == 10:
        return f"+91{cleaned}"
    elif len(cleaned) == 12 and cleaned.startswith('91'):
        return f"+{cleaned}"
    elif len(cleaned) > 10:
        return f"+{cleaned}"
    return phone_number

def format_datetime_for_display(dt_obj: datetime, tz: str = 'Asia/Kolkata') -> str:
    if not isinstance(dt_obj, datetime):
        dt_obj = dateutil_parse(str(dt_obj))

    target_tz = pytz.timezone(tz)
    if dt_obj.tzinfo is None:
        dt_obj = pytz.utc.localize(dt_obj).astimezone(target_tz)
    else:
        dt_obj = dt_obj.astimezone(target_tz)
    
    return dt_obj.strftime('%A, %B %d at %I:%M %p (%Z)')

def get_google_calendar_service():
    creds = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        with open(GOOGLE_TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.error(f"Failed to refresh Google token: {e}. Please re-run generate_google_token.py")
                return None
        else:
            logger.error("Google credentials are not valid. Please run generate_google_token.py to authenticate.")
            return None
            
        with open(GOOGLE_TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
            
    try:
        service = build('calendar', 'v3', credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Failed to build Google Calendar service: {e}", exc_info=True)
        return None

def create_google_meet_event(summary: str, start_time: datetime, attendee_emails: list, tz: str = 'Asia/Kolkata'):
    service = get_google_calendar_service()
    if not service:
        logger.error("Cannot create event, Google Calendar service is unavailable.")
        return None
        
    end_time = start_time + timedelta(hours=1)

    event = {
        'summary': summary,
        'description': 'This interview was scheduled automatically by the HR Interview Scheduler.',
        'start': {'dateTime': start_time.isoformat(), 'timeZone': tz},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': tz},
        'attendees': [{'email': email} for email in attendee_emails],
        'conferenceData': {
            'createRequest': {
                'requestId': f'interview-{datetime.now().timestamp()}',
                'conferenceSolutionKey': {'type': 'hangoutsMeet'}
            }
        },
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 60},
                {'method': 'popup', 'minutes': 15},
            ],
        },
    }
    
    try:
        created_event = service.events().insert(
            calendarId='primary', 
            body=event, 
            sendNotifications=True, 
            conferenceDataVersion=1
        ).execute()
        
        meet_link = created_event.get('hangoutLink')
        logger.info(f"Successfully created event for '{summary}'. Meet Link: {meet_link}")
        return meet_link
    except Exception as e:
        logger.error(f"Failed to create Google Calendar event: {e}", exc_info=True)
        return None

def generate_future_slots(num_slots: int = 3, min_future_hours: int = 24, slot_duration_minutes: int = 30,
                          preferred_start_hour: int = 10, preferred_end_hour: int = 17,
                          slot_interval_minutes: int = 60, 
                          start_from_datetime: Optional[datetime] = None,
                          exclude_dates: Optional[List[datetime.date]] = None) -> List[datetime]: 
    generated_slots = []
    now_utc = datetime.now(timezone.utc)
    exclude_dates_set: Set[datetime.date] = set(exclude_dates) if exclude_dates else set()
    potential_start_point = now_utc + timedelta(hours=min_future_hours)

    if start_from_datetime:
        if start_from_datetime.tzinfo is None:
            start_from_datetime = pytz.utc.localize(start_from_datetime)
        else:
            start_from_datetime = start_from_datetime.astimezone(timezone.utc)
        potential_start_point = max(potential_start_point, start_from_datetime + timedelta(minutes=slot_duration_minutes))

    current_time_for_generation = potential_start_point.replace(second=0, microsecond=0)

    if current_time_for_generation.minute % slot_interval_minutes != 0:
        current_time_for_generation += timedelta(minutes=(slot_interval_minutes - (current_time_for_generation.minute % slot_interval_minutes)))

    if current_time_for_generation.hour >= preferred_end_hour or current_time_for_generation.hour < preferred_start_hour:
        current_day = current_time_for_generation.date() + timedelta(days=1)
        current_time_for_generation = datetime.combine(current_day, datetime.min.time().replace(hour=preferred_start_hour), tzinfo=timezone.utc)
    else:
        if current_time_for_generation.hour < preferred_start_hour:
            current_time_for_generation = current_time_for_generation.replace(hour=preferred_start_hour)

    max_days_to_search = 30 
    days_searched = 0

    while len(generated_slots) < num_slots and days_searched < max_days_to_search:
        if current_time_for_generation.date() in exclude_dates_set:
            current_time_for_generation = datetime.combine(
                current_time_for_generation.date() + timedelta(days=1),
                datetime.min.time().replace(hour=preferred_start_hour),
                tzinfo=timezone.utc
            )
            days_searched +=1 
        if current_time_for_generation.hour >= preferred_end_hour:
            current_time_for_generation = datetime.combine(
                current_time_for_generation.date() + timedelta(days=1),
                datetime.min.time().replace(hour=preferred_start_hour),
                tzinfo=timezone.utc
            )
            days_searched +=1
            continue 
        if preferred_start_hour <= current_time_for_generation.hour < preferred_end_hour:
            generated_slots.append(current_time_for_generation)

        current_time_for_generation += timedelta(minutes=slot_interval_minutes)

    if len(generated_slots) < num_slots:
        logger.warning(f"Could not generate {num_slots} unique slots within {max_days_to_search} days due to exclusions/constraints.")
    
    return generated_slots