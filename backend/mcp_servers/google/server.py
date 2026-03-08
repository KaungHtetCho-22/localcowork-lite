"""
Google MCP Server — Gmail + Google Calendar via OAuth2
Tools: list_emails, search_emails, summarize_thread,
       list_events, create_event, find_free_slots, create_time_block
"""
from __future__ import annotations

import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from backend.agent_core.tool_router import register_tool

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]

CREDS_PATH  = Path(__file__).parent / "credentials.json"
TOKEN_PATH  = Path(__file__).parent / "token.json"


def _get_creds() -> Credentials:
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=8085, open_browser=True)
        TOKEN_PATH.write_text(creds.to_json())
    return creds

def _gmail():
    return build("gmail", "v1", credentials=_get_creds())


def _calendar():
    return build("calendar", "v3", credentials=_get_creds())


def _decode_body(payload) -> str:
    """Recursively extract plain text body from Gmail payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace") if data else ""
    for part in payload.get("parts", []):
        result = _decode_body(part)
        if result:
            return result
    return ""


def _parse_headers(headers: list) -> dict:
    return {h["name"]: h["value"] for h in headers}


# ── Gmail tools ───────────────────────────────────────────────────────────────

async def list_emails(max_results: int = 10, label: str = "INBOX") -> dict:
    """List recent emails from Gmail inbox."""
    service = _gmail()
    resp = service.users().messages().list(
        userId="me", maxResults=max_results, labelIds=[label]
    ).execute()

    messages = resp.get("messages", [])
    emails = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        headers = _parse_headers(msg["payload"]["headers"])
        emails.append({
            "id": m["id"],
            "thread_id": msg["threadId"],
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", "(no subject)"),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", "")[:10], 
        })

    return {"emails": emails, "count": len(emails), "label": label}


async def search_emails(query: str, max_results: int = 10) -> dict:
    """Search Gmail using Gmail search syntax (e.g. 'from:boss@company.com', 'subject:invoice')."""
    service = _gmail()
    resp = service.users().messages().list(
        userId="me", maxResults=max_results, q=query
    ).execute()

    messages = resp.get("messages", [])
    emails = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        headers = _parse_headers(msg["payload"]["headers"])
        emails.append({
            "id": m["id"],
            "thread_id": msg["threadId"],
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", "(no subject)"),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
        })

    return {"query": query, "results": emails, "count": len(emails)}


async def summarize_thread(thread_id: str) -> dict:
    """Read all messages in a Gmail thread and return full content for summarization."""
    service = _gmail()
    thread = service.users().threads().get(userId="me", id=thread_id).execute()

    messages = []
    for msg in thread["messages"]:
        headers = _parse_headers(msg["payload"]["headers"])
        body = _decode_body(msg["payload"])
        messages.append({
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "body": body[:1000],
        })

    return {
        "thread_id": thread_id,
        "message_count": len(messages),
        "messages": messages,
    }


async def send_email(to: str, subject: str, body: str, cc: Optional[str] = None) -> dict:
    """Send an email via Gmail API."""
    service = _gmail()

    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    msg.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    return {"status": "sent", "message_id": result["id"], "to": to, "subject": subject}


# ── Calendar tools ────────────────────────────────────────────────────────────

async def list_events(days_ahead: int = 7, max_results: int = 20) -> dict:
    """List upcoming Google Calendar events."""
    service = _calendar()
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)

    resp = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for e in resp.get("items", []):
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        end_t = e["end"].get("dateTime",   e["end"].get("date", ""))
        events.append({
            "id": e["id"],
            "title": e.get("summary", "(no title)"),
            "start": start,
            "end": end_t,
            "location": e.get("location", ""),
            "description": e.get("description", "")[:200],
        })

    return {"events": events, "count": len(events), "days_ahead": days_ahead}


async def create_event(
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    reminder_minutes: int = 1440,  # default 1 day before
) -> dict:
    service = _calendar()
    event = {
        "summary": title,
        "location": location,
        "description": description,
        "start": {"dateTime": start, "timeZone": "Asia/Bangkok"},
        "end":   {"dateTime": end,   "timeZone": "Asia/Bangkok"},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email",  "minutes": reminder_minutes},
                {"method": "popup",  "minutes": reminder_minutes},
            ],
        },
    }
    result = service.events().insert(calendarId="primary", body=event).execute()
    return {
        "status": "created",
        "event_id": result["id"],
        "title": title,
        "start": start,
        "end": end,
        "reminder_minutes_before": reminder_minutes,
        "link": result.get("htmlLink", ""),
    }


async def find_free_slots(date: str, duration_minutes: int = 60) -> dict:
    """Find free time slots on a given date (format: '2025-03-10')."""
    service = _calendar()
    day_start = datetime.fromisoformat(f"{date}T00:00:00+07:00")
    day_end   = datetime.fromisoformat(f"{date}T23:59:59+07:00")

    resp = service.freebusy().query(body={
        "timeMin": day_start.isoformat(),
        "timeMax": day_end.isoformat(),
        "items": [{"id": "primary"}],
    }).execute()

    busy = resp["calendars"]["primary"]["busy"]
    busy_ranges = [(b["start"], b["end"]) for b in busy]

    # Find gaps >= duration_minutes between 08:00–20:00
    work_start = datetime.fromisoformat(f"{date}T08:00:00+07:00")
    work_end   = datetime.fromisoformat(f"{date}T20:00:00+07:00")

    free_slots = []
    cursor = work_start
    for b_start, b_end in sorted(busy_ranges):
        b_s = datetime.fromisoformat(b_start)
        b_e = datetime.fromisoformat(b_end)
        if (b_s - cursor).seconds // 60 >= duration_minutes:
            free_slots.append({
                "start": cursor.isoformat(),
                "end": b_s.isoformat(),
                "duration_minutes": (b_s - cursor).seconds // 60,
            })
        cursor = max(cursor, b_e)
    if (work_end - cursor).seconds // 60 >= duration_minutes:
        free_slots.append({
            "start": cursor.isoformat(),
            "end": work_end.isoformat(),
            "duration_minutes": (work_end - cursor).seconds // 60,
        })

    return {"date": date, "free_slots": free_slots, "busy_count": len(busy_ranges)}


async def create_time_block(
    title: str,
    date: str,
    start_time: str,
    duration_minutes: int = 60,
) -> dict:
    """Block time on Google Calendar (e.g. deep work, focus time). date: '2025-03-10', start_time: '14:00'"""
    start_dt = f"{date}T{start_time}:00+07:00"
    end_dt_obj = datetime.fromisoformat(start_dt) + timedelta(minutes=duration_minutes)
    end_dt = end_dt_obj.isoformat()
    return await create_event(
        title=f"🔒 {title}",
        start=start_dt,
        end=end_dt,
        description="Time block created by LocalCowork",
        reminder_minutes=reminder_minutes,
    )


# ── Register ──────────────────────────────────────────────────────────────────

register_tool(
    server="google",
    name="list_emails",
    description="List recent emails from Gmail inbox.",
    parameters={
        "type": "object",
        "properties": {
            "max_results": {"type": "integer", "description": "Number of emails to return (default 10)", "default": 10},
            "label": {"type": "string", "description": "Gmail label e.g. INBOX, SENT, SPAM", "default": "INBOX"},
        },
    },
    handler=list_emails,
    risk="safe"
)

register_tool(
    server="google",
    name="search_emails",
    description="Search Gmail using Gmail query syntax e.g. 'from:boss@co.com', 'subject:invoice', 'is:unread'.",
    parameters={
        "type": "object",
        "properties": {
            "query":       {"type": "string",  "description": "Gmail search query"},
            "max_results": {"type": "integer", "description": "Max results (default 10)", "default": 10},
        },
        "required": ["query"],
    },
    handler=search_emails,
    risk="safe"
)

register_tool(
    server="google",
    name="summarize_thread",
    description="Read all messages in a Gmail thread by thread_id (from list_emails or search_emails).",
    parameters={
        "type": "object",
        "properties": {
            "thread_id": {"type": "string", "description": "Gmail thread ID"},
        },
        "required": ["thread_id"],
    },
    handler=summarize_thread,
    risk="safe"
)

register_tool(
    server="google",
    name="send_email",
    description="Send an email via Gmail.",
    parameters={
        "type": "object",
        "properties": {
            "to":      {"type": "string", "description": "Recipient email"},
            "subject": {"type": "string", "description": "Subject line"},
            "body":    {"type": "string", "description": "Email body"},
            "cc":      {"type": "string", "description": "CC address (optional)"},
        },
        "required": ["to", "subject", "body"],
    },
    handler=send_email,
    risk="destructive"
)

register_tool(
    server="google",
    name="list_events",
    description="List upcoming Google Calendar events.",
    parameters={
        "type": "object",
        "properties": {
            "days_ahead":  {"type": "integer", "description": "How many days ahead to look (default 7)", "default": 7},
            "max_results": {"type": "integer", "description": "Max events to return (default 20)", "default": 20},
        },
    },
    handler=list_events,
    risk="safe"
)

register_tool(
    server="google",
    name="create_event",
    description="Create a Google Calendar event.",
    parameters={
        "type": "object",
        "properties": {
            "title":       {"type": "string", "description": "Event title"},
            "start":       {"type": "string", "description": "Start datetime ISO format e.g. '2025-03-10T14:00:00+07:00'"},
            "end":         {"type": "string", "description": "End datetime ISO format"},
            "description": {"type": "string", "description": "Event description (optional)"},
            "location":    {"type": "string", "description": "Event location (optional)"},
        },
        "required": ["title", "start", "end"],
    },
    handler=create_event,
    risk="write"
)

register_tool(
    server="google",
    name="find_free_slots",
    description="Find free time slots on a given date based on existing calendar events.",
    parameters={
        "type": "object",
        "properties": {
            "date":             {"type": "string",  "description": "Date to check in format 'YYYY-MM-DD'"},
            "duration_minutes": {"type": "integer", "description": "Minimum slot duration in minutes (default 60)", "default": 60},
        },
        "required": ["date"],
    },
    handler=find_free_slots,
    risk="safe"
)

register_tool(
    server="google",
    name="create_time_block",
    description="Block focus time on Google Calendar e.g. deep work, no-meeting blocks.",
    parameters={
        "type": "object",
        "properties": {
            "title":            {"type": "string",  "description": "Block title e.g. 'Deep Work'"},
            "date":             {"type": "string",  "description": "Date in format 'YYYY-MM-DD'"},
            "start_time":       {"type": "string",  "description": "Start time in format 'HH:MM'"},
            "duration_minutes": {"type": "integer", "description": "Duration in minutes (default 60)", "default": 60},
        },
        "required": ["title", "date", "start_time"],
    },
    handler=create_time_block,
    risk="write"
)