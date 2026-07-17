from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.connectors.base import ConnectorScope
from app.connectors.registry import get_connector
from app.database import SessionLocal
from app.config import get_settings
from app.models import AccountGroup, CalendarConnection, ResearchBatch, ResearchRun, SourceRun, SourceSpec, utcnow
from app.services.entity_resolution import propose_links
from app.services.ingestion import ingest_record
from app.services.scoring import rescore_all
from app.services.research import (
    ProviderResponsePending, create_research_run,
    execute_research_run as execute_research_workflow,
)
from app.services.calendar import sync_managed_events
from app.worker import celery_app


async def _execute_run(run_id: str) -> dict:
    with SessionLocal() as db:
        run = db.get(SourceRun, run_id)
        if run is None:
            raise ValueError(f"Unknown source run {run_id}")
        source = db.get(SourceSpec, run.source_id)
        if source is None or not source.enabled:
            raise RuntimeError("Source is unavailable or disabled")
        if source.policy_status != "approved" or not source.automation_allowed:
            run.status = "awaiting_manual"
            db.commit()
            return {"status": run.status}
        if not source.connector_key or source.connector_key == "tabular_import":
            run.status = "awaiting_upload"
            db.commit()
            return {"status": run.status}
        if source.commercial and (not run.scope.get("commercial_enabled") or run.budget_cents <= 0):
            raise RuntimeError("Commercial source requires explicit per-run opt-in and budget")

        run.status = "running"
        run.started_at = utcnow()
        db.commit()
        connector = get_connector(source.connector_key)
        scope = ConnectorScope(**run.scope)
        try:
            async for record in connector.discover(scope):
                run.records_seen += 1
                account, created = ingest_record(db, source, record, run)
                if account:
                    run.records_created += int(created)
                    run.records_updated += int(not created)
                    if account.classification_status == "excluded":
                        connector.reject("franchise" if account.classification_reason == "confirmed_franchise" else "wrong_vertical")
                if run.records_seen % 100 == 0:
                    run.spent_cents = connector.spent_cents
                    run.rejection_reasons = connector.rejection_counts
                    run.records_rejected = sum(connector.rejection_counts.values())
                    db.commit()
            run.spent_cents = connector.spent_cents
            run.rejection_reasons = connector.rejection_counts
            run.records_rejected = sum(connector.rejection_counts.values())
            if run.spent_cents > run.budget_cents:
                raise RuntimeError("Connector exceeded the configured per-run cost ceiling")
            run.status = "completed"
            run.finished_at = utcnow()
            source.last_success_at = utcnow()
            source.last_error = None
            db.commit()
            propose_links(db)
            return {
                "status": run.status,
                "seen": run.records_seen,
                "created": run.records_created,
                "updated": run.records_updated,
                "rejected": run.records_rejected,
            }
        except Exception as exc:
            run.rejection_reasons = connector.rejection_counts
            run.records_rejected = sum(connector.rejection_counts.values())
            run.status = "failed"
            run.error = str(exc)[:4000]
            run.finished_at = utcnow()
            source.last_error_at = utcnow()
            source.last_error = str(exc)[:4000]
            db.commit()
            raise


@celery_app.task(bind=True, name="app.tasks.execute_source_run", max_retries=3)
def execute_source_run(self, run_id: str) -> dict:
    try:
        return asyncio.run(_execute_run(run_id))
    except (httpx.HTTPError, OSError, ConnectionError) as exc:
        raise self.retry(exc=exc, countdown=min(300, 15 * (2 ** self.request.retries)))


@celery_app.task(bind=True, name="app.tasks.execute_research_run", max_retries=65)
def execute_research_run(self, run_id: str, only_step: str | None = None) -> dict:
    try:
        with SessionLocal() as db:
            run = db.get(ResearchRun, run_id)
            if not run:
                raise ValueError(f"Unknown research run {run_id}")
            asyncio.run(execute_research_workflow(db, run, only_step=only_step))
            return {"id": run.id, "status": run.status}
    except ProviderResponsePending as exc:
        raise self.retry(exc=exc, countdown=15)
    except (httpx.HTTPError, OSError, ConnectionError) as exc:
        raise self.retry(exc=exc, countdown=min(180, 15 * (2 ** self.request.retries)))


@celery_app.task(name="app.tasks.rescore_all_accounts")
def rescore_all_accounts() -> int:
    with SessionLocal() as db:
        return rescore_all(db)


@celery_app.task(name="app.tasks.refresh_source_health")
def refresh_source_health() -> int:
    with SessionLocal() as db:
        sources = db.scalars(select(SourceSpec)).all()
        # Source freshness is derived at read time; this task exists as a durable health heartbeat.
        return len(sources)


@celery_app.task(name="app.tasks.queue_due_research")
def queue_due_research() -> int:
    settings = get_settings()
    if not settings.auto_research_enabled:
        return 0
    cutoff = utcnow() - timedelta(days=settings.auto_research_stale_days)
    queued = 0
    with SessionLocal() as db:
        first_party = db.get(SourceSpec, "first_party_web")
        if not first_party or not (
            first_party.enabled and first_party.automation_allowed
            and first_party.policy_status == "approved" and first_party.cost_class in {"open", "free_key"}
            and not first_party.overage_possible
        ):
            return 0
        active_accounts = select(ResearchRun.account_id).where(ResearchRun.status.in_(["queued", "running", "awaiting_paid_approval"]))
        accounts = db.scalars(select(AccountGroup).where(
            AccountGroup.data_status == "active",
            AccountGroup.classification_status != "excluded",
            AccountGroup.id.not_in(active_accounts),
            (AccountGroup.research_assessed_at.is_(None)) | (AccountGroup.research_assessed_at < cutoff),
        ).order_by(AccountGroup.research_assessed_at.asc().nullsfirst(), AccountGroup.created_at).limit(settings.auto_research_batch_size)).all()
        if not accounts:
            return 0
        batch = ResearchBatch(
            mode="free_public", status="running", account_ids=[x.id for x in accounts],
            max_leads=len(accounts), created_by="automation",
            filters={"reason": "new_or_stale", "stale_before": cutoff.isoformat()},
        )
        db.add(batch)
        db.flush()
        for account in accounts:
            bucket = int(datetime.now(timezone.utc).timestamp()) // max(900, settings.auto_research_stale_days * 86400)
            run = create_research_run(db, account, mode="free_public", dedupe_key=f"auto-free:{account.id}:{bucket}", batch_id=batch.id)
            account.research_state = "queued"
            execute_research_run.delay(run.id)
            queued += 1
        db.commit()
    return queued


@celery_app.task(bind=True, name="app.tasks.sync_google_calendars", max_retries=3)
def sync_google_calendars(self) -> int:
    if not get_settings().calendar_enabled:
        return 0
    try:
        with SessionLocal() as db:
            connections = db.scalars(select(CalendarConnection).where(CalendarConnection.status == "connected")).all()
            return sum(asyncio.run(sync_managed_events(db, connection)) for connection in connections)
    except (httpx.HTTPError, OSError, ConnectionError) as exc:
        raise self.retry(exc=exc, countdown=min(300, 30 * (2 ** self.request.retries)))
