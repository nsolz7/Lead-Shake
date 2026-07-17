from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import (
    AccountGroup,
    CalendarConnection,
    ContactPoint,
    CoverageEvidence,
    FieldAssertion,
    Location,
    Meeting,
    PersonRole,
    ReadinessDecision,
    ResearchAssessment,
    ResearchRun,
    SalesActivity,
    SalesTask,
)
from app.services import calendar
from app import tasks
from app.services.normalization import content_hash, normalize_address
from app.services.research import _propose_asserted_websites, assess_research


def account_record(name: str = "Ready Roofing") -> AccountGroup:
    return AccountGroup(
        name=name,
        normalized_name=name.lower(),
        vertical="contractors_trades",
        classification_status="target",
        classification_reason="matched_vertical",
        classification_confidence=0.95,
        operating_status="active",
        ownership_status="likely",
        location_count_verified=3,
        eligible=True,
        website="https://readyroofing.example",
        domain="readyroofing.example",
        review_status="needs_research",
        data_status="active",
    )


def add_contact_ready_evidence(db, account: AccountGroup) -> None:
    db.add(PersonRole(
        account_id=account.id,
        source_id="manual_research",
        name="Robin Owner",
        normalized_name="robin owner",
        role="Owner",
        ownership_signal=True,
        confidence=0.9,
    ))
    db.add(ContactPoint(
        account_id=account.id,
        source_id="manual_research",
        kind="email",
        value="office@readyroofing.example",
        normalized_value="office@readyroofing.example",
        scope="business",
        verification_status="verified",
        confidence=0.9,
    ))
    db.flush()


@contextmanager
def authorized_client(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post("/api/auth/login", json={"username": "admin", "password": "change-me-now"})
            assert response.status_code == 200
            yield client
    finally:
        app.dependency_overrides.clear()


def test_versioned_assessment_counts_attempts_and_gates_contact(db):
    account = account_record()
    db.add(account)
    db.flush()
    add_contact_ready_evidence(db, account)

    initial = assess_research(db, account)
    assert initial.ready is False
    assert initial.dimensions["legal_licenses"]["status"] == "not_started"

    run = ResearchRun(account_id=account.id, mode="free_public", status="completed")
    db.add(run)
    db.flush()
    completed = assess_research(db, account, run)
    db.commit()

    assert completed.id != initial.id
    assert completed.completeness == 100
    assert completed.dimensions["legal_licenses"]["status"] == "attempted_no_evidence"
    assert completed.dimensions["freshness_conflicts"]["status"] == "found"
    assert completed.ready is True
    assert account.research_state == "ready"
    assert account.contact_ready_at is not None
    assert len(db.scalars(select(ResearchAssessment).where(ResearchAssessment.account_id == account.id)).all()) == 2


def test_automatic_free_research_queue_is_bounded_and_skips_active_runs(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_research_enabled", True)
    monkeypatch.setattr(settings, "auto_research_batch_size", 2)
    monkeypatch.setattr(settings, "auto_research_stale_days", 30)
    accounts = [account_record(f"Queue Roofing {index}") for index in range(4)]
    db.add_all(accounts)
    db.commit()
    db.add(ResearchRun(account_id=accounts[0].id, mode="free_public", status="running"))
    db.commit()

    class KeepOpen:
        def __enter__(self):
            return db

        def __exit__(self, *args):
            return None

    queued_ids: list[str] = []
    monkeypatch.setattr(tasks, "SessionLocal", lambda: KeepOpen())
    monkeypatch.setattr(tasks.execute_research_run, "delay", lambda run_id, *args: queued_ids.append(run_id))
    assert tasks.queue_due_research() == 2
    assert len(queued_ids) == 2
    batch = db.scalar(select(tasks.ResearchBatch).order_by(tasks.ResearchBatch.created_at.desc()))
    assert batch and batch.mode == "free_public" and len(batch.account_ids) == 2
    assert accounts[0].id not in batch.account_ids


def test_crm_lifecycle_followup_privacy_and_append_only_policy_history(db, monkeypatch):
    account = account_record("Lifecycle Roofing")
    db.add(account)
    db.commit()
    with authorized_client(db) as client:
        rejected_private_data = client.post(f"/api/leads/{account.id}/people", json={
            "name": "Robin Owner", "role": "Owner", "home_address": "1 Private Lane",
        })
        assert rejected_private_data.status_code == 422

        person = client.post(f"/api/leads/{account.id}/people", json={
            "name": "Robin Owner", "role": "Owner", "preferred_name": "Robin",
            "is_primary_contact": True, "communication_preference": "email",
            "relationship_notes": "Prefers an agenda before meetings",
        })
        assert person.status_code == 200
        assert person.json()["preferred_name"] == "Robin"

        activity = client.post(f"/api/leads/{account.id}/activities", json={
            "kind": "conversation", "subject": "Renewal planning", "direction": "inbound",
            "notes": "Discussed next-quarter review", "person_role_id": person.json()["id"],
            "follow_up": {
                "title": "Send exposure checklist", "kind": "email", "priority": "high",
                "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            },
        })
        assert activity.status_code == 200
        changed = client.patch(f"/api/activities/{activity.json()['id']}", json={"notes": "Corrected CRM note"})
        assert changed.json()["notes"] == "Corrected CRM note"
        follow_up = db.scalar(select(SalesTask).where(SalesTask.activity_id == activity.json()["id"]))
        assert follow_up and follow_up.title == "Send exposure checklist" and follow_up.priority == "high"

        won = client.patch(f"/api/leads/{account.id}/sales-stage", json={"stage": "won", "notes": "Bound"})
        assert won.status_code == 200
        assert won.json()["relationship_status"] == "active_client"

        first = client.post(f"/api/leads/{account.id}/policies", json={
            "coverage_type": "general_liability", "carrier": "Example Mutual",
            "policy_identifier": "GL-SECRET-1234", "policy_status": "active",
            "renewal_status": "reviewing", "source_kind": "customer_reported",
            "observed_on": date.today().isoformat(), "confidence": "exact",
        })
        assert first.status_code == 200
        assert "GL-SECRET-1234" not in json.dumps(first.json())
        replacement = client.post(f"/api/policies/{first.json()['id']}/supersede", json={
            "coverage_type": "general_liability", "carrier": "Example Mutual",
            "policy_identifier": "GL-SECRET-5678", "policy_status": "active",
            "renewal_status": "bound", "source_kind": "producer_entered",
            "observed_on": date.today().isoformat(), "confidence": "exact",
        })
        assert replacement.status_code == 200
        assert replacement.json()["supersedes_id"] == first.json()["id"]

        detail = client.get(f"/api/leads/{account.id}").json()
        current = [item for item in detail["coverages"] if item["current"]]
        assert len(current) == 1 and current[0]["id"] == replacement.json()["id"]
        assert len(detail["coverages"]) == 2


def test_paid_batch_has_independent_total_and_per_lead_hard_ceiling(db):
    account = account_record("Budget Roofing")
    db.add(account)
    db.commit()
    with authorized_client(db) as client:
        insufficient_total = client.post("/api/research/batches", json={
            "mode": "ai_analysis", "account_ids": [account.id],
            "approved_sources": ["openai_web_research"],
            "per_lead_budget_cents": 20, "total_budget_cents": 10,
        })
        assert insufficient_total.status_code == 400
        unapproved_source = client.post("/api/research/batches", json={
            "mode": "ai_analysis", "account_ids": [account.id],
            "per_lead_budget_cents": 20, "total_budget_cents": 20,
        })
        assert unapproved_source.status_code == 400
        paid_free_batch = client.post("/api/research/batches", json={
            "mode": "free_public", "account_ids": [account.id], "total_budget_cents": 1,
        })
        assert paid_free_batch.status_code == 400


def test_aggregator_website_requires_exact_phone_and_location_identity_match(db):
    account = account_record("Identity Match Roofing")
    account.website = None
    account.domain = None
    account.primary_phone = "+19195550100"
    db.add(account)
    db.flush()
    db.add(Location(
        account_id=account.id, source_id="manual_research", name=account.name,
        address1="1 Main Street", city="Raleigh", state="NC", postal_code="27601",
        normalized_address=normalize_address("1 Main Street", "Raleigh", "NC", "27601"),
        phone="+19195550100", authoritative=True, confidence=1.0,
    ))
    run = ResearchRun(account_id=account.id, mode="free_public", status="running")
    db.add(run)
    db.flush()
    values = {
        "website": "https://identity-match.example",
        "phone": "(919) 555-0100",
        "address1": "1 Main Street", "city": "Raleigh", "state": "NC", "postal_code": "27601",
    }
    for field, value in values.items():
        db.add(FieldAssertion(
            account_id=account.id, subject_type="account_group", subject_id=account.id,
            source_id="overture_places", source_record_id="overture-1",
            field_name=field, value_json=value, authority="open_aggregator",
            confidence=.9, content_hash=content_hash(value),
        ))
    db.flush()
    db.expire(account, ["assertions", "locations"])
    assert _propose_asserted_websites(db, run, account) == 0
    assert account.website == "https://identity-match.example"

    account.website = None
    account.domain = None
    phone_assertion = db.scalar(select(FieldAssertion).where(
        FieldAssertion.account_id == account.id, FieldAssertion.field_name == "phone",
    ))
    phone_assertion.value_json = "919-555-9999"
    db.flush()
    db.expire(account, ["assertions"])
    assert _propose_asserted_websites(db, run, account) == 1
    assert account.website is None
    db.flush()
    assert run.findings[0].status == "proposed"


def test_meeting_readiness_gate_requires_audited_override(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "calendar_enabled", False)
    account = account_record("Meeting Roofing")
    account.contact_ready_at = None
    db.add(account)
    db.commit()
    payload = {
        "title": "Introduction",
        "start_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "end_at": (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat(),
        "timezone": "America/New_York",
        "private_prep_notes": "Ask about operations; never put this in Google.",
    }
    with authorized_client(db) as client:
        blocked = client.post(f"/api/leads/{account.id}/meetings", json=payload)
        assert blocked.status_code == 409
        created = client.post(f"/api/leads/{account.id}/meetings", json={
            **payload, "readiness_override_reason": "Existing producer relationship confirms contact is appropriate",
        })
        assert created.status_code == 200
        assert created.json()["sync_status"] == "pending_sync"
        assert created.json()["private_prep_notes"] == payload["private_prep_notes"]
        decision = db.scalar(select(ReadinessDecision).where(ReadinessDecision.account_id == account.id))
        assert decision and decision.decision == "override" and decision.decided_by == "admin"


def test_calendar_token_encryption_state_and_private_event_boundary(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_calendar_token_encryption_key", "test-only-dedicated-calendar-key")
    token = "refresh-token-secret"
    first = calendar.encrypt_refresh_token(token)
    second = calendar.encrypt_refresh_token(token)
    assert first != second
    assert token not in first
    assert calendar.decrypt_refresh_token(first) == token

    state = calendar.create_oauth_state("admin")
    assert calendar.decode_oauth_state(state) == "admin"
    wrong_purpose = jwt.encode({"sub": "admin", "purpose": "wrong"}, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(ValueError):
        calendar.decode_oauth_state(wrong_purpose)

    account = account_record("Private Notes Roofing")
    db.add(account)
    db.flush()
    meeting = Meeting(
        account_id=account.id, title="Introduction",
        start_at=datetime.now(timezone.utc) + timedelta(days=1),
        end_at=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
        timezone="America/New_York", attendees=[{"email": "owner@example.com"}],
        google_event_id="mdeterministic", private_prep_notes="PRIVATE POLICY CONTEXT",
    )
    db.add(meeting)
    db.flush()
    payload = calendar._event_payload(meeting, account)
    serialized = json.dumps(payload)
    assert payload["id"] == "mdeterministic"
    assert "PRIVATE POLICY CONTEXT" not in serialized
    assert payload["extendedProperties"]["private"]["leadintelMeetingId"] == meeting.id


@pytest.mark.asyncio
async def test_calendar_insert_recovers_idempotently_from_existing_event(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_calendar_token_encryption_key", "test-only-dedicated-calendar-key")
    account = account_record("Idempotent Roofing")
    db.add(account)
    db.flush()
    meeting = Meeting(
        account_id=account.id, title="Introduction",
        start_at=datetime(2026, 7, 20, 14, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 20, 15, tzinfo=timezone.utc),
        timezone="America/New_York", google_event_id="mexistingevent", sync_status="pending_sync",
    )
    connection = CalendarConnection(
        username="admin", calendar_id="primary", status="connected",
        encrypted_refresh_token=calendar.encrypt_refresh_token("refresh-token"),
    )
    db.add_all([meeting, connection])
    db.commit()

    async def access_token(_connection):
        return "access-token"

    calls = {"post": 0, "get": 0}
    event = {
        "id": meeting.google_event_id, "etag": '"etag-1"', "status": "confirmed",
        "htmlLink": "https://calendar.google.com/event?id=example",
        "start": {"dateTime": "2026-07-20T10:00:00-04:00", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-07-20T11:00:00-04:00", "timeZone": "America/New_York"},
        "extendedProperties": {"private": {"leadintelManaged": "true", "leadintelMeetingId": meeting.id}},
    }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            calls["post"] += 1
            return httpx.Response(409, request=httpx.Request("POST", url))

        async def get(self, url, **kwargs):
            calls["get"] += 1
            return httpx.Response(200, json=event, request=httpx.Request("GET", url))

    monkeypatch.setattr(calendar, "_access_token", access_token)
    monkeypatch.setattr(calendar.httpx, "AsyncClient", FakeClient)
    result = await calendar.sync_meeting(db, meeting)
    assert calls == {"post": 1, "get": 1}
    assert result.sync_status == "synced"
    assert result.google_event_id == "mexistingevent"
    assert result.google_etag == '"etag-1"'


@pytest.mark.asyncio
async def test_incremental_calendar_sync_recovers_from_expired_sync_token(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_calendar_token_encryption_key", "test-only-dedicated-calendar-key")
    connection = CalendarConnection(
        username="admin", calendar_id="primary", status="connected", sync_token="expired-token",
        encrypted_refresh_token=calendar.encrypt_refresh_token("refresh-token"),
    )
    db.add(connection)
    db.commit()

    async def access_token(_connection):
        return "access-token"

    calls: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            calls.append(kwargs["params"])
            if len(calls) == 1:
                return httpx.Response(410, request=httpx.Request("GET", url))
            return httpx.Response(200, json={"items": [], "nextSyncToken": "fresh-token"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(calendar, "_access_token", access_token)
    monkeypatch.setattr(calendar.httpx, "AsyncClient", FakeClient)
    assert await calendar.sync_managed_events(db, connection) == 0
    assert calls[0]["syncToken"] == "expired-token"
    assert "syncToken" not in calls[1]
    assert calls[1]["privateExtendedProperty"] == "leadintelManaged=true"
    assert connection.sync_token == "fresh-token"
