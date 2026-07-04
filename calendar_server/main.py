from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "google-calendar.log"

logger = logging.getLogger("google-calendar")
logger.setLevel(logging.DEBUG)
logger.handlers.clear()
logger.propagate = False

stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.DEBUG)
stderr_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

logger.addHandler(stderr_handler)
logger.addHandler(file_handler)

logger.info("google-calendar MCP server bootstrap starting")
logger.info("Resolved project root: %s", PROJECT_ROOT)

from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

from shared.auth import GoogleAuth

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"

logger.info("Using client secrets file: %s", CLIENT_SECRETS)
logger.info("Client secrets exists: %s", CLIENT_SECRETS.exists())

mcp = FastMCP("google-calendar")


def get_calendar_service():
    logger.info("Initializing Calendar service")
    auth = GoogleAuth(
        client_secrets_file=str(CLIENT_SECRETS),
        scopes=SCOPES,
        token_prefix="calendar",
    )
    creds = auth.get_credentials()
    logger.info("Google Calendar credentials loaded successfully")
    return build("calendar", "v3", credentials=creds)


def _format_event(event: dict[str, Any]) -> dict[str, Any]:
    start = event.get("start", {}) or {}
    end = event.get("end", {}) or {}

    conference_data = event.get("conferenceData") or {}
    hangout_link = event.get("hangoutLink") or conference_data.get("entryPoints", [{}])[0].get("uri") if conference_data.get("entryPoints") else ""

    return {
        "id": event.get("id"),
        "summary": event.get("summary", ""),
        "description": event.get("description", ""),
        "location": event.get("location", ""),
        "start": start.get("dateTime") or start.get("date", ""),
        "end": end.get("dateTime") or end.get("date", ""),
        "timezone": start.get("timeZone", ""),
        "status": event.get("status", ""),
        "creator": event.get("creator", {}).get("email", ""),
        "organizer": event.get("organizer", {}).get("email", ""),
        "htmlLink": event.get("htmlLink", ""),
        "hangoutLink": hangout_link,
        "reminders": event.get("reminders", {}),
    }


@mcp.tool()
def list_calendars() -> list[dict[str, Any]]:
    """List all calendars accessible by the authenticated user."""
    logger.info("list_calendars called")
    try:
        service = get_calendar_service()
        res = service.calendarList().list().execute()
        items = res.get("items", []) or []
        out = []
        for cal in items:
            out.append({
                "id": cal.get("id"),
                "summary": cal.get("summary", ""),
                "description": cal.get("description", ""),
                "primary": cal.get("primary", False),
                "selected": cal.get("selected", False),
                "timeZone": cal.get("timeZone", ""),
                "accessRole": cal.get("accessRole", ""),
            })
        logger.info("list_calendars returned %s calendars", len(out))
        return out
    except Exception:
        logger.exception("list_calendars failed")
        raise


@mcp.tool()
def list_events(
    calendar_id: str = "primary",
    max_results: int = 20,
    days_ahead: int = 30,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """List upcoming events from a calendar.

    Args:
        calendar_id: Calendar ID (default 'primary' for the main calendar).
        max_results: Maximum number of events to return (default 20, max 100).
        days_ahead: How many days ahead to look (default 30).
        query: Optional free-text search filter.
    """
    logger.info(
        "list_events called calendar_id=%s max_results=%s days_ahead=%s",
        calendar_id, max_results, days_ahead,
    )
    try:
        service = get_calendar_service()
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days_ahead)

        params: dict[str, Any] = {
            "calendarId": calendar_id,
            "timeMin": now.isoformat(),
            "timeMax": time_max.isoformat(),
            "maxResults": min(max_results, 100),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if query:
            params["q"] = query

        res = service.events().list(**params).execute()
        events = res.get("items", []) or []
        out = [_format_event(e) for e in events]
        logger.info("list_events returned %s events", len(out))
        return out
    except Exception:
        logger.exception("list_events failed")
        raise


@mcp.tool()
def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str | None = None,
    location: str | None = None,
    calendar_id: str = "primary",
    timezone: str = "Europe/Rome",
    attendees: list[str] | None = None,
    remind_minutes: int = 30,
    add_google_meet: bool = False,
) -> dict[str, Any]:
    """Create a new calendar event.

    Args:
        summary: Event title.
        start_time: Start datetime in ISO format (e.g. '2026-07-10T09:00:00').
        end_time: End datetime in ISO format.
        description: Optional event description.
        location: Optional event location.
        calendar_id: Calendar ID (default 'primary').
        timezone: Timezone (default 'Europe/Rome').
        attendees: Optional list of attendee email addresses.
        remind_minutes: Minutes before event for a popup reminder (default 30, 0 = no reminder).
        add_google_meet: If True, automatically create a Google Meet conference link.
    """
    logger.info("create_event called summary=%s start=%s end=%s", summary, start_time, end_time)
    try:
        service = get_calendar_service()

        event_body: dict[str, Any] = {
            "summary": summary,
            "start": {
                "dateTime": start_time,
                "timeZone": timezone,
            },
            "end": {
                "dateTime": end_time,
                "timeZone": timezone,
            },
        }

        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if attendees:
            event_body["attendees"] = [{"email": a} for a in attendees]
        if remind_minutes > 0:
            event_body["reminders"] = {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": remind_minutes},
                ],
            }
        else:
            event_body["reminders"] = {"useDefault": False, "overrides": []}
        if add_google_meet:
            event_body["conferenceData"] = {
                "createRequest": {
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    "requestId": str(uuid.uuid4()),
                }
            }

        insert_params: dict[str, Any] = {
            "calendarId": calendar_id,
            "body": event_body,
        }
        if add_google_meet:
            insert_params["conferenceDataVersion"] = 1

        event = service.events().insert(**insert_params).execute()

        logger.info("create_event success id=%s", event.get("id"))
        return _format_event(event)
    except Exception:
        logger.exception("create_event failed")
        raise


@mcp.tool()
def update_event(
    event_id: str,
    calendar_id: str = "primary",
    summary: str | None = None,
    description: str | None = None,
    location: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    timezone: str = "Europe/Rome",
    attendees: list[str] | None = None,
    remind_minutes: int | None = None,
) -> dict[str, Any]:
    """Update an existing calendar event.

    Only provided fields will be updated. Set a field to empty string to clear it.

    Args:
        event_id: ID of the event to update.
        calendar_id: Calendar ID (default 'primary').
        summary: New event title.
        description: New description.
        location: New location.
        start_time: New start datetime (ISO format).
        end_time: New end datetime (ISO format).
        timezone: Timezone (default 'Europe/Rome').
        attendees: New list of attendee emails.
        remind_minutes: New reminder minutes before event.
    """
    logger.info("update_event called event_id=%s", event_id)
    try:
        service = get_calendar_service()

        event_body: dict[str, Any] = {}
        if summary is not None:
            event_body["summary"] = summary
        if description is not None:
            event_body["description"] = description
        if location is not None:
            event_body["location"] = location
        if start_time is not None:
            event_body.setdefault("start", {})["dateTime"] = start_time
            event_body.setdefault("start", {})["timeZone"] = timezone
        if end_time is not None:
            event_body.setdefault("end", {})["dateTime"] = end_time
            event_body.setdefault("end", {})["timeZone"] = timezone
        if attendees is not None:
            event_body["attendees"] = [{"email": a} for a in attendees]
        if remind_minutes is not None:
            event_body["reminders"] = {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": remind_minutes}] if remind_minutes > 0 else [],
            }

        event = service.events().patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=event_body,
        ).execute()

        logger.info("update_event success id=%s", event.get("id"))
        return _format_event(event)
    except Exception:
        logger.exception("update_event failed")
        raise


@mcp.tool()
def delete_event(event_id: str, calendar_id: str = "primary") -> dict[str, str]:
    """Delete a calendar event.

    Args:
        event_id: ID of the event to delete.
        calendar_id: Calendar ID (default 'primary').
    """
    logger.info("delete_event called event_id=%s calendar_id=%s", event_id, calendar_id)
    try:
        service = get_calendar_service()
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id,
        ).execute()
        logger.info("delete_event success event_id=%s", event_id)
        return {"status": "deleted", "event_id": event_id}
    except Exception:
        logger.exception("delete_event failed")
        raise


@mcp.tool()
def get_event(event_id: str, calendar_id: str = "primary") -> dict[str, Any]:
    """Get a single calendar event by ID.

    Args:
        event_id: ID of the event to retrieve.
        calendar_id: Calendar ID (default 'primary').
    """
    logger.info("get_event called event_id=%s", event_id)
    try:
        service = get_calendar_service()
        event = service.events().get(
            calendarId=calendar_id,
            eventId=event_id,
        ).execute()
        return _format_event(event)
    except Exception:
        logger.exception("get_event failed")
        raise


if __name__ == "__main__":
    try:
        logger.info("google-calendar MCP server started successfully")
        mcp.run()
    except KeyboardInterrupt:
        logger.info("google-calendar MCP server interrupted by user")
        raise
    except Exception:
        logger.exception("Fatal server error")
        raise
