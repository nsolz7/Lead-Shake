from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.connectors.base import ConnectorScope, RawRecord
from app.connectors.overture import OvertureConnector
from app.database import get_db
from app.main import app
from app.models import AccountGroup, ProviderRateCard, ResearchFinding, ResearchStep, SalesTask, SourceSpec
from app.services import research
from app.services.ingestion import ingest_record
from app.services.research import create_research_run, decide_finding, execute_research_run
from app.services.normalization import content_hash
from app.repair_overture import repair_overture_geography


class _DuckConnection:
    def __init__(self, rows):
        self.rows = rows
        self.description = []
        self.query = ""
        self.params = []
        self.closed = False

    def execute(self, query, params=None):
        self.query = query
        self.params = params or []
        self.description = [(name,) for name in (
            "id", "names_json", "categories_json", "websites_json", "emails_json",
            "phones_json", "addresses_json", "brand_json", "operating_status",
            "confidence", "longitude", "latitude",
        )]
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return (0, 0)

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_overture_filters_state_before_limit_and_normalizes_open(monkeypatch):
    address = [{"freeform": "1 Main St", "locality": "Raleigh", "region": "nc", "country": "us", "postcode": "27601"}]
    row = (
        "place-1", json.dumps({"primary": "Example Restaurant"}), json.dumps({"primary": "restaurant"}),
        json.dumps(["https://example.test"]), "[]", "[]", json.dumps(address), "{}", "open",
        0.91, -78.64, 35.78,
    )
    connection = _DuckConnection([row])
    monkeypatch.setattr("app.connectors.overture.duckdb.connect", lambda: connection)
    connector = OvertureConnector()

    records = [record async for record in connector.discover(ConnectorScope(
        states=["nc"], limit=1, parameters={"parquet_uri": "local.parquet"},
    ))]

    assert len(records) == 1
    assert records[0].state == "NC"
    assert records[0].operating_status == "active"
    assert "upper(addresses[1].country) = 'US'" in connection.query
    assert "upper(addresses[1].region) = ?" in connection.query
    assert connection.params[5] == "NC"
    assert connection.closed is True


@pytest.mark.asyncio
async def test_public_research_completes_without_paid_or_ai_steps(db):
    account = AccountGroup(
        name="Research Target", normalized_name="research target",
        vertical="contractors_trades", review_status="needs_research",
    )
    db.add(account)
    db.commit()
    run = create_research_run(db, account)

    await execute_research_run(db, run)

    steps = {step.kind: step for step in db.scalars(select(ResearchStep).where(
        ResearchStep.research_run_id == run.id,
    )).all()}
    assert run.status == "completed"
    assert "ai_web_research" not in steps
    assert steps["classify_business"].status == "completed"
    assert steps["rescore_and_brief"].status == "completed"
    assert run.spent_cents == 0
    assert run.calculated_cost_microusd == 0


@pytest.mark.asyncio
async def test_background_ai_polling_releases_worker_between_provider_checks(db, monkeypatch):
    account = AccountGroup(name="AI Target", normalized_name="ai target", vertical="contractors_trades")
    db.add(account)
    db.commit()
    run = create_research_run(db, account, mode="ai_analysis", budget_cents=500)
    step = db.scalar(select(ResearchStep).where(
        ResearchStep.research_run_id == run.id,
        ResearchStep.kind == "ai_identity_footprint",
    ))
    card = ProviderRateCard(
        id="test-ai-rate", provider="openai", model="test-model",
        effective_on=__import__("datetime").date(2026, 1, 1),
        input_usd_per_million=1, cached_input_usd_per_million=0.1,
        output_usd_per_million=6, web_search_usd_per_thousand=10,
        source_url="https://example.test/rates",
    )
    monkeypatch.setattr(research, "get_settings", lambda: SimpleNamespace(
        openai_research_model="test-model", openai_api_key="test-key", ai_research_max_tool_calls=4,
    ))
    monkeypatch.setattr(research, "validate_ai_configuration", lambda *_: card)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "resp_background", "status": "in_progress"}

    class Client:
        posts = 0
        gets = 0

        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            Client.posts += 1
            return Response()

        async def get(self, *_args, **_kwargs):
            Client.gets += 1
            return Response()

    monkeypatch.setattr(research.httpx, "AsyncClient", Client)

    with pytest.raises(research.ProviderResponsePending):
        await research._run_openai_research(db, run, account, step)
    assert Client.posts == 1
    assert Client.gets == 0
    assert step.summary["provider_response_id"] == "resp_background"

    with pytest.raises(research.ProviderResponsePending):
        await research._run_openai_research(db, run, account, step)
    assert Client.posts == 1
    assert Client.gets == 1
    assert step.summary["provider_poll_count"] == 2


def test_sales_activity_follow_up_and_do_not_contact(db):
    source = db.get(SourceSpec, "overture_places")
    account, _ = ingest_record(db, source, RawRecord(
        source_record_id="sales-1", brand_name="Sales Target", vertical="auto_services",
        address1="10 Sales Street", city="Raleigh", state="NC", postal_code="27601",
    ))
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            token = client.post(
                "/api/auth/login", json={"username": "admin", "password": "change-me-now"},
            ).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            due_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            task = client.post(
                f"/api/leads/{account.id}/tasks", headers=headers,
                json={"kind": "call", "due_at": due_at, "notes": "Ask for the owner"},
            )
            assert task.status_code == 200
            db.refresh(account)
            assert account.next_action_at is not None

            completed = client.patch(
                f"/api/tasks/{task.json()['id']}", headers=headers, json={"status": "completed"},
            )
            assert completed.status_code == 200
            assert completed.json()["status"] == "completed"
            assert db.get(SalesTask, task.json()["id"]).completed_at is not None

            activity = client.post(
                f"/api/leads/{account.id}/activities", headers=headers,
                json={"kind": "call", "disposition": "do_not_contact", "notes": "Requested no calls"},
            )
            assert activity.status_code == 200
            db.refresh(account)
            assert account.review_status == "suppressed"
            assert account.last_contact_at is not None
    finally:
        app.dependency_overrides.clear()


def test_repair_preserves_reviewed_account_and_is_idempotent(db):
    source = db.get(SourceSpec, "overture_places")
    account, _ = ingest_record(db, source, RawRecord(
        source_record_id="reviewed-ga", brand_name="Reviewed Target", vertical="auto_services",
        address1="10 Review Street", city="Atlanta", state="GA", postal_code="30303",
        operating_status="open",
    ))
    account.review_status = "needs_research"
    account.data_status = "quarantined"
    db.commit()
    factory = lambda: nullcontext(db)

    applied = repair_overture_geography({"NC"}, apply=True, session_factory=factory)
    repeated = repair_overture_geography({"NC"}, apply=False, session_factory=factory)

    db.refresh(account)
    assert applied["accounts_reactivated"] == 1
    assert account.data_status == "active"
    assert account.locations[0].scope_status == "out_of_scope"
    assert repeated["accounts_reactivated"] == 0
    assert repeated["locations_out_of_scope"] == 0
    assert repeated["statuses_normalized"] == 0


def test_accepting_website_finding_materializes_and_queues_one_followup(db):
    account = AccountGroup(
        name="Candidate Website Group", normalized_name="candidate website group",
        vertical="contractors_trades", classification_status="target", review_status="needs_research",
    )
    db.add(account); db.commit()
    run = create_research_run(db, account)
    finding = ResearchFinding(
        research_run_id=run.id, account_id=account.id, source_id="manual_research",
        field_name="website_candidate", value_json="https://candidate.example",
        source_url="https://candidate.example", evidence_excerpt="Same business name and address",
        content_hash=content_hash({"value": "https://candidate.example", "source_url": "https://candidate.example"}),
        authority="derived", confidence=0.8, status="proposed", parser_version="manual-candidate-v1",
    )
    db.add(finding); db.commit()

    decided, followup = decide_finding(db, finding, "accept", "admin")
    db.refresh(account)
    assert decided.status == "accepted"
    assert account.domain == "candidate.example"
    assert followup and followup.mode == "first_party_followup"

    repeated, duplicate = decide_finding(db, finding, "accept", "admin")
    assert repeated.status == "accepted"
    assert duplicate is None
