from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from app.config import get_settings
from app.models import AccountGroup, CalendarConnection, Meeting, utcnow


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.owned",
]


def _configured() -> bool:
    settings = get_settings()
    return bool(
        settings.calendar_enabled and settings.google_calendar_client_id
        and settings.google_calendar_client_secret and settings.google_calendar_redirect_uri
        and settings.google_calendar_token_encryption_key
    )


def require_calendar_configuration() -> None:
    if not _configured():
        raise ValueError("Google Calendar is disabled or its OAuth/encryption settings are incomplete")


def _aes() -> AESGCM:
    secret = get_settings().google_calendar_token_encryption_key
    if not secret:
        raise ValueError("GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY is not configured")
    return AESGCM(hashlib.sha256(secret.encode("utf-8")).digest())


def encrypt_refresh_token(token: str) -> str:
    nonce = os.urandom(12)
    ciphertext = _aes().encrypt(nonce, token.encode("utf-8"), b"leadintel-google-calendar")
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_refresh_token(value: str) -> str:
    raw = base64.urlsafe_b64decode(value.encode("ascii"))
    return _aes().decrypt(raw[:12], raw[12:], b"leadintel-google-calendar").decode("utf-8")


def create_oauth_state(username: str) -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": username, "purpose": "google_calendar_oauth", "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
        settings.jwt_secret, algorithm="HS256",
    )


def decode_oauth_state(state: str) -> str:
    payload = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("purpose") != "google_calendar_oauth":
        raise ValueError("Invalid Google Calendar OAuth state")
    return str(payload["sub"])


def authorization_url(username: str) -> str:
    require_calendar_configuration()
    settings = get_settings()
    return f"{GOOGLE_AUTH_URL}?{urlencode({
        'client_id': settings.google_calendar_client_id,
        'redirect_uri': settings.google_calendar_redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'include_granted_scopes': 'true',
        'prompt': 'consent',
        'state': create_oauth_state(username),
    })}"


async def exchange_code(db, code: str, state: str) -> CalendarConnection:
    require_calendar_configuration()
    username = decode_oauth_state(state)
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code, "client_id": settings.google_calendar_client_id,
            "client_secret": settings.google_calendar_client_secret,
            "redirect_uri": settings.google_calendar_redirect_uri,
            "grant_type": "authorization_code",
        })
        response.raise_for_status()
        payload = response.json()
    refresh_token = payload.get("refresh_token")
    existing = db.scalar(select(CalendarConnection).where(CalendarConnection.username == username))
    if not refresh_token and not existing:
        raise ValueError("Google did not return an offline refresh token; reconnect and grant consent")
    connection = existing or CalendarConnection(
        username=username, encrypted_refresh_token=encrypt_refresh_token(refresh_token),
    )
    if refresh_token:
        connection.encrypted_refresh_token = encrypt_refresh_token(refresh_token)
    connection.calendar_id = settings.google_calendar_id
    connection.scopes = str(payload.get("scope") or " ".join(SCOPES)).split()
    connection.status = "connected"
    connection.connected_at = utcnow()
    connection.last_error = None
    if existing is None:
        db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


async def _access_token(connection: CalendarConnection) -> str:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": settings.google_calendar_client_id,
            "client_secret": settings.google_calendar_client_secret,
            "refresh_token": decrypt_refresh_token(connection.encrypted_refresh_token),
            "grant_type": "refresh_token",
        })
    if response.status_code in {400, 401}:
        connection.status = "auth_required"
        connection.last_error = "Google authorization expired or was revoked"
        raise PermissionError(connection.last_error)
    response.raise_for_status()
    return response.json()["access_token"]


def connection_dict(connection: CalendarConnection | None) -> dict:
    settings = get_settings()
    if connection is None:
        return {"configured": _configured(), "connected": False, "status": "disconnected", "calendar_id": settings.google_calendar_id}
    return {
        "configured": _configured(), "connected": connection.status == "connected",
        "status": connection.status, "calendar_id": connection.calendar_id,
        "google_account_email": connection.google_account_email,
        "scopes": connection.scopes, "connected_at": connection.connected_at,
        "last_synced_at": connection.last_synced_at, "last_error": connection.last_error,
    }


def meeting_dict(meeting: Meeting) -> dict:
    return {
        "id": meeting.id, "account_id": meeting.account_id, "person_role_id": meeting.person_role_id,
        "title": meeting.title, "start_at": meeting.start_at, "end_at": meeting.end_at,
        "timezone": meeting.timezone, "location": meeting.location, "attendees": meeting.attendees,
        "reminder_minutes": meeting.reminder_minutes, "create_meet": meeting.create_meet,
        "send_updates": meeting.send_updates, "status": meeting.status, "sync_status": meeting.sync_status,
        "google_event_id": meeting.google_event_id, "google_html_link": meeting.google_html_link,
        "google_meet_link": meeting.google_meet_link, "private_prep_notes": meeting.private_prep_notes,
        "last_synced_at": meeting.last_synced_at, "sync_error": meeting.sync_error,
        "created_by": meeting.created_by, "created_at": meeting.created_at,
    }


def _event_payload(meeting: Meeting, account: AccountGroup) -> dict:
    settings = get_settings()
    attendees = [{"email": item["email"], **({"displayName": item["name"]} if item.get("name") else {})}
                 for item in meeting.attendees if item.get("email")]
    payload = {
        "id": meeting.google_event_id or f"m{meeting.id.replace('-', '')}",
        "summary": meeting.title,
        "description": f"Lead: {account.name}\nResearch workspace: {settings.public_app_url.rstrip('/')}/?lead={account.id}",
        "start": {"dateTime": meeting.start_at.isoformat(), "timeZone": meeting.timezone},
        "end": {"dateTime": meeting.end_at.isoformat(), "timeZone": meeting.timezone},
        "location": meeting.location,
        "attendees": attendees,
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": meeting.reminder_minutes}]},
        "extendedProperties": {"private": {
            "leadintelManaged": "true", "leadintelMeetingId": meeting.id, "leadintelAccountId": meeting.account_id,
        }},
    }
    if meeting.create_meet:
        payload["conferenceData"] = {"createRequest": {
            "requestId": f"meet-{meeting.id}", "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }}
    return payload


def _apply_google_event(meeting: Meeting, event: dict) -> None:
    start = event.get("start") or {}
    end = event.get("end") or {}
    if start.get("dateTime"):
        meeting.start_at = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
    if end.get("dateTime"):
        meeting.end_at = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))
    meeting.timezone = start.get("timeZone") or meeting.timezone
    meeting.location = event.get("location")
    meeting.attendees = [{
        "email": item.get("email"), "name": item.get("displayName"),
        "response_status": item.get("responseStatus"),
    } for item in event.get("attendees", [])]
    meeting.google_event_id = event.get("id") or meeting.google_event_id
    meeting.google_etag = event.get("etag")
    meeting.google_html_link = event.get("htmlLink")
    meeting.google_meet_link = event.get("hangoutLink") or next((
        item.get("uri") for item in (event.get("conferenceData") or {}).get("entryPoints", [])
        if item.get("entryPointType") == "video"
    ), None)
    meeting.status = "cancelled" if event.get("status") == "cancelled" else "scheduled"
    meeting.sync_status = "synced"
    meeting.sync_error = None
    meeting.last_synced_at = utcnow()


async def sync_meeting(db, meeting: Meeting, *, patch: bool = False) -> Meeting:
    connection = db.scalar(select(CalendarConnection).where(CalendarConnection.status == "connected"))
    if not connection:
        meeting.sync_status = "auth_required"
        meeting.sync_error = "Connect Google Calendar before syncing this meeting"
        db.commit()
        return meeting
    account = db.get_one(AccountGroup, meeting.account_id)
    token = await _access_token(connection)
    event_id = meeting.google_event_id or f"m{meeting.id.replace('-', '')}"
    params = {"conferenceDataVersion": 1, "sendUpdates": "all" if meeting.send_updates else "none"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if patch and meeting.google_etag:
        headers["If-Match"] = meeting.google_etag
    url = f"{GOOGLE_CALENDAR_API}/calendars/{connection.calendar_id}/events"
    async with httpx.AsyncClient(timeout=30) as client:
        if patch and meeting.google_event_id:
            response = await client.patch(f"{url}/{event_id}", params=params, headers=headers, json=_event_payload(meeting, account))
            if response.status_code == 412:
                latest = await client.get(f"{url}/{event_id}", headers={"Authorization": f"Bearer {token}"})
                latest.raise_for_status()
                _apply_google_event(meeting, latest.json())
                meeting.sync_status = "conflict"
                meeting.sync_error = "Google changed this event; its scheduling fields were retained"
                db.commit()
                return meeting
        else:
            response = await client.post(url, params=params, headers=headers, json=_event_payload(meeting, account))
            if response.status_code == 409:
                response = await client.get(f"{url}/{event_id}", headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        _apply_google_event(meeting, response.json())
    connection.last_synced_at = utcnow()
    connection.last_error = None
    db.commit()
    return meeting


async def cancel_meeting(db, meeting: Meeting) -> Meeting:
    connection = db.scalar(select(CalendarConnection).where(CalendarConnection.status == "connected"))
    if connection and meeting.google_event_id:
        token = await _access_token(connection)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(
                f"{GOOGLE_CALENDAR_API}/calendars/{connection.calendar_id}/events/{meeting.google_event_id}",
                params={"sendUpdates": "all" if meeting.send_updates else "none"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code not in {204, 404, 410}:
                response.raise_for_status()
    meeting.status = "cancelled"
    meeting.sync_status = "synced"
    meeting.last_synced_at = utcnow()
    db.commit()
    return meeting


async def sync_managed_events(db, connection: CalendarConnection) -> int:
    token = await _access_token(connection)
    headers = {"Authorization": f"Bearer {token}"}
    params: dict[str, object] = {"showDeleted": "true", "singleEvents": "true"}
    if connection.sync_token:
        params["syncToken"] = connection.sync_token
    else:
        params["privateExtendedProperty"] = "leadintelManaged=true"
        params["timeMin"] = (utcnow() - timedelta(days=365)).isoformat()
    updated = 0
    next_page = None
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            request_params = {**params, **({"pageToken": next_page} if next_page else {})}
            response = await client.get(
                f"{GOOGLE_CALENDAR_API}/calendars/{connection.calendar_id}/events",
                params=request_params, headers=headers,
            )
            if response.status_code == 410:
                connection.sync_token = None
                db.commit()
                return await sync_managed_events(db, connection)
            response.raise_for_status()
            payload = response.json()
            for event in payload.get("items", []):
                private = ((event.get("extendedProperties") or {}).get("private") or {})
                meeting_id = private.get("leadintelMeetingId")
                meeting = db.get(Meeting, meeting_id) if meeting_id else None
                if meeting:
                    _apply_google_event(meeting, event)
                    updated += 1
            next_page = payload.get("nextPageToken")
            if not next_page:
                connection.sync_token = payload.get("nextSyncToken") or connection.sync_token
                break
    connection.last_synced_at = utcnow()
    connection.last_error = None
    db.commit()
    return updated
