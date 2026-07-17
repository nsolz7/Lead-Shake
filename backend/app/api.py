from __future__ import annotations

# Auth model: browser sessions use an HttpOnly cookie; API clients may still
# send "Authorization: Bearer <token>". Login is rate limited (app/ratelimit.py).
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    AccountGroup, ContactPoint, ContactProfile, CoverageEvidence, EntityLink, ExportBatch, Location, Meeting, Outcome,
    PersonRole, ReadinessDecision, ResearchAssessment, ResearchBatch, ResearchFinding, ResearchRun, ResearchStep,
    ReviewDecision, SalesActivity, SalesTask, SourceRun, SourceSpec, SuppressionEntry, utcnow,
)
from app.schemas import (
    AiAnalysisRunCreate, ClassificationRepairRequest, EnrichRequest, ExportRequest, FindingDecisionRequest,
    GoogleValidationRequest, LoginRequest, ManualCoverageCreate, MatchDecisionRequest, OutcomeCreate,
    PaidResearchApproval, ResearchRunCreate, ReviewRequest, RunCreate, WebsiteCandidateCreate,
    LeadProfileUpdate, MeetingCreate, MeetingUpdate, PersonCreate, PersonUpdate, PolicyCreate, PolicySupersede,
    ReadinessOverrideCreate, ResearchBatchCreate, SalesActivityCreate, SalesActivityUpdate, SalesStageUpdate,
    SalesTaskCreate, SalesTaskUpdate, SourcePolicyUpdate, SuppressionCreate,
)
from app.ratelimit import clear_failures, register_failure, too_many_failures
from app.security import (
    authenticate, clear_session_cookie, client_ip, create_token, require_user, set_session_cookie,
)
from app.services.entity_resolution import decide_link
from app.services.exporter import create_export
from app.services.ingestion import ingest_record
from app.services.normalization import content_hash, hmac_policy_id, normalize_domain, normalize_email, normalize_name, normalize_phone
from app.services.scoring import score_account
from app.services.tabular_import import import_tabular
from app.connectors.base import RawRecord
from app.connectors.google_places import live_validate_place
from app.tasks import execute_research_run, execute_source_run
from app.config import get_settings
from app.services.research import (
    assessment_dict, batch_dict, create_research_run, decide_finding, finding_dict, research_run_dict,
    validate_ai_configuration,
)
from app.services.calendar import (
    authorization_url, cancel_meeting, connection_dict, exchange_code, meeting_dict,
    sync_managed_events, sync_meeting,
)
from app.repair_classification import repair_classifications


router = APIRouter(prefix="/api")


def _source_dict(source: SourceSpec) -> dict:
    now = datetime.now(timezone.utc)
    stale = source.last_success_at is None or (now - source.last_success_at).days > source.freshness_days
    return {
        "id": source.id, "name": source.name, "jurisdiction": source.jurisdiction,
        "acquisition_mode": source.acquisition_mode, "authority": source.authority,
        "base_url": source.base_url, "enabled": source.enabled,
        "automation_allowed": source.automation_allowed, "commercial": source.commercial,
        "cost_class": source.cost_class, "credential_required": source.credential_required,
        "overage_possible": source.overage_possible, "license_name": source.license_name,
        "terms_url": source.terms_url, "policy_status": source.policy_status,
        "policy_evidence_url": source.policy_evidence_url,
        "policy_reviewed_by": source.policy_reviewed_by,
        "accepts_upload": source.connector_key == "tabular_import",
        "standalone_runnable": bool(source.connector_key and source.connector_key != "tabular_import"),
        "allowed_fields": source.allowed_fields, "retention_policy": source.retention_policy,
        "terms_reviewed_at": source.terms_reviewed_at, "freshness_days": source.freshness_days,
        "last_success_at": source.last_success_at, "last_error_at": source.last_error_at,
        "last_error": source.last_error, "stale": stale, "notes": source.notes,
    }


def _run_dict(run: SourceRun) -> dict:
    return {
        "id": run.id, "source_id": run.source_id, "source_name": run.source.name if run.source else run.source_id,
        "status": run.status, "scope": run.scope, "budget_cents": run.budget_cents,
        "spent_cents": run.spent_cents, "records_seen": run.records_seen,
        "records_created": run.records_created, "records_updated": run.records_updated,
        "records_rejected": run.records_rejected, "rejection_reasons": run.rejection_reasons,
        "started_at": run.started_at, "finished_at": run.finished_at, "error": run.error,
        "created_at": run.created_at,
    }


def _lead_summary(account: AccountGroup) -> dict:
    states = sorted({location.state for location in account.locations if location.state and location.scope_status == "in_scope"})
    latest_research = max(account.research_runs, key=lambda item: item.created_at) if account.research_runs else None
    latest_assessment = max(account.research_assessments, key=lambda item: item.assessed_at) if account.research_assessments else None
    return {
        "id": account.id, "name": account.name, "vertical": account.vertical, "naics": account.naics,
        "classification_status": account.classification_status,
        "classification_reason": account.classification_reason,
        "classification_policy_version": account.classification_policy_version,
        "classification_confidence": account.classification_confidence,
        "states": states, "location_count_verified": account.location_count_verified,
        "ownership_status": account.ownership_status, "eligible": account.eligible,
        "exclusion_reason": account.exclusion_reason, "score": account.score, "tier": account.tier,
        "review_status": account.review_status, "website": account.website, "domain": account.domain,
        "primary_phone": account.primary_phone, "primary_email": account.primary_email,
        "google_place_id": account.google_place_id,
        "timing_confidence": account.timing_confidence, "x_date": account.x_date,
        "best_pitch_angle": account.best_pitch_angle, "next_action_date": account.next_action_date,
        "evidence_count": len(account.assertions), "last_verified_at": account.last_verified_at,
        "data_status": account.data_status, "research_completeness": account.research_completeness,
        "research_status": latest_research.status if latest_research else None,
        "sales_stage": account.sales_stage, "sales_brief": account.sales_brief,
        "last_contact_at": account.last_contact_at, "next_action_at": account.next_action_at,
        "relationship_status": account.relationship_status, "research_state": account.research_state,
        "research_assessed_at": account.research_assessed_at, "contact_ready_at": account.contact_ready_at,
        "contact_ready": bool(account.contact_ready_at),
        "readiness_blockers": latest_assessment.blockers if latest_assessment else [],
    }


def _lead_query():
    return select(AccountGroup).options(
        selectinload(AccountGroup.locations), selectinload(AccountGroup.brands),
        selectinload(AccountGroup.legal_entities), selectinload(AccountGroup.people).selectinload(PersonRole.profile),
        selectinload(AccountGroup.contacts).selectinload(ContactPoint.person),
        selectinload(AccountGroup.permits), selectinload(AccountGroup.coverages),
        selectinload(AccountGroup.triggers), selectinload(AccountGroup.assertions),
        selectinload(AccountGroup.score_contributions),
        selectinload(AccountGroup.research_runs).selectinload(ResearchRun.steps),
        selectinload(AccountGroup.research_runs).selectinload(ResearchRun.findings),
        selectinload(AccountGroup.sales_activities), selectinload(AccountGroup.sales_tasks),
        selectinload(AccountGroup.services), selectinload(AccountGroup.exposures),
        selectinload(AccountGroup.ownership_relationships), selectinload(AccountGroup.business_events),
        selectinload(AccountGroup.research_assessments), selectinload(AccountGroup.readiness_decisions),
        selectinload(AccountGroup.crawl_pages), selectinload(AccountGroup.meetings),
    )


def _activity_dict(activity: SalesActivity) -> dict:
    return {
        "id": activity.id, "kind": activity.kind, "disposition": activity.disposition,
        "occurred_at": activity.occurred_at, "notes": activity.notes,
        "details": activity.details, "created_by": activity.created_by,
        "subject": activity.subject, "direction": activity.direction,
        "duration_minutes": activity.duration_minutes, "person_role_id": activity.person_role_id,
        "coverage_evidence_id": activity.coverage_evidence_id, "meeting_id": activity.meeting_id,
        "outcome": activity.outcome,
    }


def _task_dict(task: SalesTask) -> dict:
    return {
        "id": task.id, "kind": task.kind, "status": task.status, "due_at": task.due_at,
        "completed_at": task.completed_at, "notes": task.notes, "created_by": task.created_by,
        "title": task.title, "priority": task.priority, "person_role_id": task.person_role_id,
        "activity_id": task.activity_id, "meeting_id": task.meeting_id,
    }


def _person_dict(person: PersonRole) -> dict:
    profile = person.profile
    return {
        "id": person.id, "name": person.name, "role": person.role,
        "ownership_signal": person.ownership_signal, "confidence": person.confidence,
        "profile": person.professional_profile_url,
        "preferred_name": profile.preferred_name if profile else None,
        "is_primary_contact": profile.is_primary_contact if profile else False,
        "communication_preference": profile.communication_preference if profile else None,
        "timezone": profile.timezone if profile else None,
        "interests": profile.interests if profile else [], "tags": profile.tags if profile else [],
        "relationship_notes": profile.relationship_notes if profile else None,
    }


def _policy_dict(policy: CoverageEvidence, current_ids: set[str] | None = None) -> dict:
    return {
        "id": policy.id, "type": policy.coverage_type, "carrier": policy.carrier,
        "policy_masked": policy.policy_masked, "effective_on": policy.effective_on,
        "expires_on": policy.expires_on, "coverage_as_of": policy.coverage_as_of,
        "confidence": policy.confidence, "policy_status": policy.policy_status,
        "renewal_status": policy.renewal_status, "source_kind": policy.source_kind,
        "observed_on": policy.observed_on, "annual_premium": policy.annual_premium,
        "notes": policy.notes, "supersedes_id": policy.supersedes_id,
        "current": policy.id in current_ids if current_ids is not None else False,
    }


def _current_policy_ids(policies: list[CoverageEvidence]) -> set[str]:
    superseded = {item.supersedes_id for item in policies if item.supersedes_id}
    current: dict[str, CoverageEvidence] = {}
    for item in policies:
        if item.id in superseded:
            continue
        previous = current.get(item.coverage_type)
        item_date = item.observed_on or item.coverage_as_of or item.effective_on or date.min
        previous_date = (previous.observed_on or previous.coverage_as_of or previous.effective_on or date.min) if previous else date.min
        if previous is None or item_date >= previous_date:
            current[item.coverage_type] = item
    return {item.id for item in current.values()}


def _refresh_next_action(db: Session, account: AccountGroup) -> None:
    account.next_action_at = db.scalar(select(func.min(SalesTask.due_at)).where(
        SalesTask.account_id == account.id, SalesTask.status == "open",
    ))


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    ip_key = f"login:ip:{ip}"
    # Backstop bucket keyed on the direct peer, so rotating X-Forwarded-For
    # values cannot dodge the limit entirely.
    peer_key = f"login:peer:{request.client.host if request.client else 'unknown'}"
    settings = get_settings()
    if too_many_failures(ip_key) or too_many_failures(peer_key, limit=settings.login_max_failures * 6):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
        )
    if not authenticate(payload.username, payload.password):
        register_failure(ip_key)
        register_failure(peer_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    clear_failures(ip_key)
    token = create_token(payload.username)
    set_session_cookie(response, token)
    return {"access_token": token, "token_type": "bearer", "username": payload.username}


@router.post("/auth/logout")
def logout(response: Response, _: str = Depends(require_user)) -> dict:
    clear_session_cookie(response)
    return {"status": "signed_out"}


@router.get("/auth/me")
def me(user: str = Depends(require_user)) -> dict:
    return {"username": user}


@router.get("/system/health")
def system_health(_: str = Depends(require_user)) -> dict:
    """Detailed dependency status. Authenticated: keeps infra layout private."""
    from redis import Redis
    from sqlalchemy import text

    from app.database import engine

    settings = get_settings()
    dependencies = {"database": "ok", "redis": "ok"}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        dependencies["database"] = "error"
    try:
        Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
    except Exception:
        dependencies["redis"] = "error"
    status_value = "ok" if all(value == "ok" for value in dependencies.values()) else "degraded"
    return {"status": status_value, "dependencies": dependencies}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    today = tomorrow - timedelta(days=1)
    return {
        "total_leads": db.scalar(select(func.count(AccountGroup.id)).where(AccountGroup.data_status == "active")) or 0,
        "eligible_leads": db.scalar(select(func.count(AccountGroup.id)).where(AccountGroup.eligible.is_(True), AccountGroup.data_status == "active")) or 0,
        "approved_leads": db.scalar(select(func.count(AccountGroup.id)).where(AccountGroup.review_status == "approved", AccountGroup.data_status == "active")) or 0,
        "tier_a": db.scalar(select(func.count(AccountGroup.id)).where(AccountGroup.tier == "A", AccountGroup.data_status == "active")) or 0,
        "proposed_matches": db.scalar(select(func.count(EntityLink.id)).where(EntityLink.status == "proposed")) or 0,
        "failed_sources": db.scalar(select(func.count(SourceSpec.id)).where(SourceSpec.last_error.is_not(None))) or 0,
        "research_failures": db.scalar(select(func.count(ResearchRun.id)).where(ResearchRun.status.in_(["failed", "partial"]))) or 0,
        "followups_due": db.scalar(select(func.count(SalesTask.id)).where(SalesTask.status == "open", SalesTask.due_at <= now)) or 0,
        "research_new_or_stale": db.scalar(select(func.count(AccountGroup.id)).where(AccountGroup.research_state.in_(["not_started", "stale"]), AccountGroup.data_status == "active")) or 0,
        "contact_ready": db.scalar(select(func.count(AccountGroup.id)).where(AccountGroup.contact_ready_at.is_not(None), AccountGroup.data_status == "active")) or 0,
        "pending_findings": db.scalar(select(func.count(ResearchFinding.id)).where(ResearchFinding.status == "proposed")) or 0,
        "blocked_research": db.scalar(select(func.count(AccountGroup.id)).where(AccountGroup.research_state == "blocked")) or 0,
        "meetings_today": db.scalar(select(func.count(Meeting.id)).where(Meeting.start_at >= today, Meeting.start_at < tomorrow, Meeting.status != "cancelled")) or 0,
    }


@router.get("/model-readiness")
def model_readiness(db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    contacted = db.scalar(select(func.count(func.distinct(Outcome.account_id))).where(Outcome.stage == "contacted")) or 0
    positive = db.scalar(select(func.count(func.distinct(Outcome.account_id))).where(
        Outcome.stage.in_(["reply", "meeting", "quote", "won"]),
    )) or 0
    return {
        "contacted_accounts": contacted,
        "positive_accounts": positive,
        "minimum_contacted": 500,
        "minimum_positive": 50,
        "ready_for_time_split_evaluation": contacted >= 500 and positive >= 50,
        "rules_score_remains_primary": True,
    }


@router.get("/sources/health")
def sources_health(db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    return [_source_dict(source) for source in db.scalars(select(SourceSpec).order_by(SourceSpec.jurisdiction, SourceSpec.name)).all()]


@router.patch("/sources/{source_id}")
def update_source(source_id: str, enabled: bool, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    source = db.get(SourceSpec, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    source.enabled = enabled
    db.commit()
    return _source_dict(source)


@router.patch("/sources/{source_id}/policy")
def update_source_policy(
    source_id: str,
    payload: SourcePolicyUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    source = db.get(SourceSpec, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    source.policy_status = payload.policy_status
    source.policy_evidence_url = payload.policy_evidence_url
    source.policy_reviewed_by = user
    source.terms_reviewed_at = date.today()
    if payload.notes is not None:
        source.notes = payload.notes
    db.commit()
    return _source_dict(source)


@router.get("/runs")
def list_runs(db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    runs = db.scalars(select(SourceRun).options(selectinload(SourceRun.source)).order_by(SourceRun.created_at.desc()).limit(200)).all()
    return [_run_dict(run) for run in runs]


@router.post("/runs", status_code=202)
def create_run(payload: RunCreate, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    source = db.get(SourceSpec, payload.source_id)
    if not source or not source.enabled:
        raise HTTPException(404, "Source is unavailable or disabled")
    if source.commercial and (not payload.commercial_enabled or payload.budget_cents <= 0):
        raise HTTPException(400, "Commercial sources require opt-in and a positive per-run budget")
    run = SourceRun(
        source_id=source.id,
        status=(
            "awaiting_manual"
            if source.policy_status != "approved" or not source.automation_allowed or not source.connector_key
            else ("awaiting_upload" if source.connector_key == "tabular_import" else "queued")
        ),
        scope={
            "states": payload.states, "verticals": payload.verticals, "queries": payload.queries,
            "parameters": payload.parameters, "limit": payload.limit,
            "commercial_enabled": payload.commercial_enabled, "budget_cents": payload.budget_cents,
        },
        budget_cents=payload.budget_cents,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run.source = source
    if run.status == "queued":
        execute_source_run.delay(run.id)
    return _run_dict(run)


@router.post("/imports/tabular")
async def upload_tabular(
    source_id: str = Form(...),
    mapping_json: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    source = db.get(SourceSpec, source_id)
    if not source or source.connector_key != "tabular_import":
        raise HTTPException(400, "Source does not accept official tabular imports")
    content = await file.read()
    if len(content) > 250 * 1024 * 1024:
        raise HTTPException(413, "Import exceeds 250 MB")
    mapping = json.loads(mapping_json) if mapping_json else None
    run = import_tabular(db, source, content, file.filename or "import.csv", mapping)
    run.source = source
    return _run_dict(run)


@router.get("/leads")
def list_leads(
    q: str | None = None,
    state_filter: str | None = Query(None, alias="state"),
    vertical: str | None = None,
    tier: str | None = None,
    timing: str | None = None,
    review_status: str | None = None,
    eligible: bool | None = None,
    evidence_gap: bool = False,
    sales_stage: str | None = None,
    include_quarantined: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    query = _lead_query()
    if not include_quarantined:
        query = query.where(AccountGroup.data_status == "active")
    if q:
        query = query.where(AccountGroup.normalized_name.contains(q.lower()) | AccountGroup.domain.contains(q.lower()))
    if state_filter:
        query = query.join(Location).where(Location.state == state_filter.upper(), Location.scope_status == "in_scope").distinct()
    if vertical:
        query = query.where(AccountGroup.vertical == vertical)
    if tier:
        query = query.where(AccountGroup.tier == tier.upper())
    if timing:
        query = query.where(AccountGroup.timing_confidence == timing)
    if review_status:
        query = query.where(AccountGroup.review_status == review_status)
    if sales_stage:
        query = query.where(AccountGroup.sales_stage == sales_stage)
    if eligible is not None:
        query = query.where(AccountGroup.eligible.is_(eligible))
    if evidence_gap:
        query = query.where((AccountGroup.location_count_verified.is_(None)) | (AccountGroup.ownership_status == "unknown"))
    query = query.order_by(AccountGroup.score.desc(), AccountGroup.name).offset(offset).limit(limit)
    accounts = db.scalars(query).unique().all()
    return {"items": [_lead_summary(account) for account in accounts], "offset": offset, "limit": limit}


@router.get("/research/queue")
def research_queue(
    research_state: str | None = None,
    ready: bool | None = None,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    query = _lead_query().where(AccountGroup.data_status == "active")
    if research_state:
        query = query.where(AccountGroup.research_state == research_state)
    if ready is True:
        query = query.where(AccountGroup.contact_ready_at.is_not(None))
    elif ready is False:
        query = query.where(AccountGroup.contact_ready_at.is_(None))
    accounts = db.scalars(query.order_by(AccountGroup.contact_ready_at.desc(), AccountGroup.research_assessed_at.asc().nullsfirst(), AccountGroup.score.desc()).limit(limit)).unique().all()
    return {"items": [_lead_summary(account) for account in accounts]}


@router.get("/research/batches")
def list_research_batches(db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    batches = db.scalars(select(ResearchBatch).options(selectinload(ResearchBatch.runs)).order_by(ResearchBatch.created_at.desc()).limit(100)).all()
    return [batch_dict(batch) for batch in batches]


@router.post("/research/batches", status_code=202)
def create_research_batch(
    payload: ResearchBatchCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    query = _lead_query().where(AccountGroup.data_status == "active")
    if payload.account_ids:
        query = query.where(AccountGroup.id.in_(payload.account_ids))
    else:
        if payload.filters.get("research_state"):
            query = query.where(AccountGroup.research_state == payload.filters["research_state"])
        if payload.filters.get("review_status"):
            query = query.where(AccountGroup.review_status == payload.filters["review_status"])
        if payload.filters.get("eligible") is not None:
            query = query.where(AccountGroup.eligible.is_(bool(payload.filters["eligible"])))
    accounts = db.scalars(query.order_by(AccountGroup.score.desc()).limit(payload.max_leads)).unique().all()
    if not accounts:
        raise HTTPException(400, "The research batch selection contains no active leads")
    if payload.mode == "ai_analysis":
        settings = get_settings()
        if "openai_web_research" not in payload.approved_sources:
            raise HTTPException(400, "AI batches must explicitly approve openai_web_research")
        if payload.per_lead_budget_cents <= 0 or payload.total_budget_cents <= 0:
            raise HTTPException(400, "Paid research requires per-lead and total ceilings")
        if payload.per_lead_budget_cents > settings.ai_research_max_budget_cents:
            raise HTTPException(400, "Per-lead budget exceeds the configured maximum")
        if payload.per_lead_budget_cents * len(accounts) > payload.total_budget_cents:
            raise HTTPException(400, "The total ceiling must cover every selected per-lead ceiling")
    elif payload.total_budget_cents or payload.per_lead_budget_cents:
        raise HTTPException(400, "Free research batches cannot carry a paid budget")

    batch = ResearchBatch(
        mode=payload.mode, status="running", filters=payload.filters,
        account_ids=[x.id for x in accounts], approved_sources=payload.approved_sources,
        max_leads=payload.max_leads, total_budget_cents=payload.total_budget_cents,
        per_lead_budget_cents=payload.per_lead_budget_cents, created_by=user,
    )
    db.add(batch)
    db.flush()
    for account in accounts:
        active = db.scalar(select(ResearchRun).where(
            ResearchRun.account_id == account.id,
            ResearchRun.status.in_(["queued", "running", "awaiting_paid_approval"]),
        ))
        if active:
            continue
        if payload.mode == "ai_analysis":
            try:
                validate_ai_configuration(db, account, payload.per_lead_budget_cents)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        run = create_research_run(
            db, account, mode=payload.mode,
            budget_cents=payload.per_lead_budget_cents if payload.mode == "ai_analysis" else 0,
            batch_id=batch.id,
        )
        account.research_state = "queued"
        execute_research_run.delay(run.id)
    db.commit()
    db.refresh(batch)
    return batch_dict(batch)


@router.get("/leads/{account_id}/research-assessment")
def get_research_assessment(account_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    assessment = db.scalar(select(ResearchAssessment).where(
        ResearchAssessment.account_id == account_id,
    ).order_by(ResearchAssessment.assessed_at.desc()))
    if not assessment:
        raise HTTPException(404, "No research assessment exists for this lead")
    return assessment_dict(assessment)


@router.post("/leads/{account_id}/readiness-override")
def override_readiness(
    account_id: str,
    payload: ReadinessOverrideCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account:
        raise HTTPException(404, "Lead not found")
    assessment = db.scalar(select(ResearchAssessment).where(
        ResearchAssessment.account_id == account.id,
    ).order_by(ResearchAssessment.assessed_at.desc()))
    db.add(ReadinessDecision(
        account_id=account.id, assessment_id=assessment.id if assessment else None,
        decision="override", reason=payload.reason, decided_by=user,
    ))
    account.contact_ready_at = utcnow()
    account.research_state = "ready_override"
    db.commit()
    return _lead_summary(account)


@router.get("/leads/{account_id}")
def get_lead(account_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    account = db.scalar(_lead_query().where(AccountGroup.id == account_id))
    if not account:
        raise HTTPException(404, "Lead not found")
    current_policy_ids = _current_policy_ids(account.coverages)
    latest_assessment = max(account.research_assessments, key=lambda item: item.assessed_at) if account.research_assessments else None
    return {
        **_lead_summary(account),
        "brands": [{"id": b.id, "name": b.name, "domain": b.domain} for b in account.brands],
        "locations": [{
            "id": x.id, "name": x.name, "address1": x.address1, "city": x.city, "state": x.state,
            "postal_code": x.postal_code, "county": x.county, "latitude": x.latitude,
            "longitude": x.longitude, "status": x.operating_status, "physical": x.physical,
            "authoritative": x.authoritative, "confidence": x.confidence, "scope_status": x.scope_status,
            "location_role": x.location_role, "verification_status": x.verification_status,
            "first_seen_at": x.first_seen_at, "last_seen_at": x.last_seen_at,
        } for x in account.locations if x.scope_status == "in_scope"],
        "legal_entities": [{
            "id": x.id, "legal_name": x.legal_name, "entity_type": x.entity_type,
            "jurisdiction": x.jurisdiction, "external_id": x.external_id, "status": x.status,
            "formed_on": x.formed_on, "registered_agent_name": x.registered_agent_name,
            "registered_agent_type": x.registered_agent_type,
        } for x in account.legal_entities],
        "people": [_person_dict(x) for x in account.people],
        "contacts": [{"id": x.id, "kind": x.kind, "value": x.value, "scope": x.scope, "verification_status": x.verification_status, "confidence": x.confidence, "suppressed": x.suppressed} for x in account.contacts if x.scope in {"business", "professional"}],
        "permits": [{"id": x.id, "kind": x.kind, "number": x.external_id, "status": x.status, "issued_on": x.issued_on, "expires_on": x.expires_on, "classifications": x.classifications} for x in account.permits],
        "coverages": [_policy_dict(x, current_policy_ids) for x in sorted(account.coverages, key=lambda item: item.observed_on or item.coverage_as_of or item.effective_on or date.min, reverse=True)],
        "triggers": [{"id": x.id, "kind": x.kind, "date": x.occurred_on, "label": x.label, "severity": x.severity, "risk_review_only": x.risk_review_only, "details": x.details} for x in account.triggers],
        "services": [{"id": x.id, "name": x.name, "category": x.category, "verification_status": x.verification_status, "confidence": x.confidence} for x in account.services],
        "exposures": [{"id": x.id, "kind": x.kind, "basis": x.basis, "verification_status": x.verification_status, "confidence": x.confidence} for x in account.exposures],
        "ownership_relationships": [{"id": x.id, "subject_name": x.subject_name, "relationship_type": x.relationship_type, "object_name": x.object_name, "verification_status": x.verification_status, "confidence": x.confidence} for x in account.ownership_relationships],
        "business_events": [{"id": x.id, "kind": x.kind, "label": x.label, "date": x.occurred_on, "details": x.details, "verification_status": x.verification_status, "confidence": x.confidence} for x in account.business_events],
        "score_contributions": [{"category": x.category, "factor": x.factor, "points": x.points, "max_points": x.max_points, "explanation": x.explanation, "evidence_ids": x.evidence_ids} for x in sorted(account.score_contributions, key=lambda c: (c.category, c.factor))],
        "evidence": [{"id": x.id, "source_id": x.source_id, "source_record_id": x.source_record_id, "source_url": x.source_url, "field": x.field_name, "value": x.value_json, "authority": x.authority, "confidence": x.confidence, "retrieved_at": x.retrieved_at, "content_hash": x.content_hash, "conflict": x.conflict, "excerpt": x.evidence_excerpt} for x in sorted(account.assertions, key=lambda a: a.retrieved_at, reverse=True)],
        "activities": [_activity_dict(x) for x in sorted(account.sales_activities, key=lambda a: a.occurred_at, reverse=True)],
        "tasks": [_task_dict(x) for x in sorted(account.sales_tasks, key=lambda t: t.due_at)],
        "research_assessment": assessment_dict(latest_assessment) if latest_assessment else None,
        "readiness_decisions": [{"id": x.id, "decision": x.decision, "reason": x.reason, "decided_by": x.decided_by, "created_at": x.created_at} for x in sorted(account.readiness_decisions, key=lambda item: item.created_at, reverse=True)],
    }


@router.post("/leads/{account_id}/review")
def review_lead(account_id: str, payload: ReviewRequest, db: Session = Depends(get_db), user: str = Depends(require_user)) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account:
        raise HTTPException(404, "Lead not found")
    account.review_status = payload.decision
    db.add(ReviewDecision(
        account_id=account.id, decision=payload.decision, notes=payload.notes, reviewer=user,
        snapshot={"score": account.score, "tier": account.tier, "eligible": account.eligible, "exclusion_reason": account.exclusion_reason},
    ))
    if payload.decision == "suppressed":
        existing = db.scalar(select(SuppressionEntry).where(
            SuppressionEntry.kind == "account", SuppressionEntry.normalized_value == account.id,
        ))
        if not existing:
            db.add(SuppressionEntry(
                kind="account", normalized_value=account.id,
                reason=payload.notes or "manual_suppression", source=user,
            ))
    db.commit()
    return _lead_summary(account)


@router.post("/leads/{account_id}/research-runs", status_code=202)
def start_research(
    account_id: str,
    payload: ResearchRunCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account or account.data_status != "active":
        raise HTTPException(404, "Lead not found")
    if account.review_status != "needs_research":
        raise HTTPException(409, "Mark the lead Needs research before launching automation")
    active = db.scalar(select(ResearchRun).where(
        ResearchRun.account_id == account.id,
        ResearchRun.status.in_(["queued", "running", "awaiting_paid_approval"]),
    ))
    if active:
        raise HTTPException(409, "A research run is already active for this lead")
    run = create_research_run(db, account, mode=payload.mode)
    execute_research_run.delay(run.id)
    db.refresh(run)
    return research_run_dict(run)


@router.post("/leads/{account_id}/ai-analysis-runs", status_code=202)
def start_ai_analysis(
    account_id: str,
    payload: AiAnalysisRunCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account or account.data_status != "active":
        raise HTTPException(404, "Lead not found")
    active = db.scalar(select(ResearchRun).where(
        ResearchRun.account_id == account.id,
        ResearchRun.status.in_(["queued", "running"]),
    ))
    if active:
        raise HTTPException(409, "A research run is already active for this lead")
    try:
        card = validate_ai_configuration(db, account, payload.budget_cents)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    run = create_research_run(db, account, mode="ai_analysis", budget_cents=payload.budget_cents)
    run.rate_card_id = card.id
    db.commit()
    execute_research_run.delay(run.id)
    db.refresh(run)
    return research_run_dict(run)


@router.post("/research-findings/{finding_id}/decision")
def decide_research_finding(
    finding_id: str,
    payload: FindingDecisionRequest,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    finding = db.get(ResearchFinding, finding_id)
    if not finding:
        raise HTTPException(404, "Research finding not found")
    try:
        finding, followup = decide_finding(db, finding, payload.decision, user, payload.notes)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if followup and followup.status == "queued":
        execute_research_run.delay(followup.id)
    return {**finding_dict(finding), "followup_run_id": followup.id if followup else None}


@router.post("/leads/{account_id}/website-candidates", status_code=201)
def propose_website_candidate(
    account_id: str,
    payload: WebsiteCandidateCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account:
        raise HTTPException(404, "Lead not found")
    domain = normalize_domain(payload.url)
    if not domain:
        raise HTTPException(400, "Candidate URL has no valid domain")
    run = ResearchRun(
        account_id=account.id, status="completed", mode="manual_candidate",
        summary={"submitted_by": user}, started_at=utcnow(), finished_at=utcnow(),
    )
    db.add(run); db.flush()
    value_hash = content_hash({"value": payload.url, "source_url": payload.url})
    finding = ResearchFinding(
        research_run_id=run.id, account_id=account.id, field_name="website_candidate",
        source_id="manual_research",
        value_json=payload.url, source_url=payload.url, citation_label="Manually supplied candidate",
        evidence_excerpt=payload.notes, content_hash=value_hash, authority="derived",
        confidence=0.5, status="proposed", parser_version="manual-candidate-v1",
    )
    db.add(finding); db.commit()
    return finding_dict(finding)


@router.post("/admin/classification-repair")
def classification_repair(
    payload: ClassificationRepairRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    # The repair owns its transaction; close this request session's read transaction first.
    db.rollback()
    return repair_classifications(apply=payload.apply)


@router.get("/leads/{account_id}/research-runs")
def list_research_runs(account_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    if not db.get(AccountGroup, account_id):
        raise HTTPException(404, "Lead not found")
    runs = db.scalars(select(ResearchRun).options(
        selectinload(ResearchRun.steps), selectinload(ResearchRun.findings),
    ).where(ResearchRun.account_id == account_id).order_by(ResearchRun.created_at.desc())).all()
    return [research_run_dict(run) for run in runs]


@router.get("/research-runs/{run_id}")
def get_research_run(run_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    run = db.scalar(select(ResearchRun).options(
        selectinload(ResearchRun.steps), selectinload(ResearchRun.findings),
    ).where(ResearchRun.id == run_id))
    if not run:
        raise HTTPException(404, "Research run not found")
    return research_run_dict(run)


@router.post("/research-runs/{run_id}/approve-paid", status_code=202)
def approve_paid_research(
    run_id: str,
    payload: PaidResearchApproval,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    settings = get_settings()
    run = db.scalar(select(ResearchRun).options(selectinload(ResearchRun.steps), selectinload(ResearchRun.findings)).where(ResearchRun.id == run_id))
    if not run:
        raise HTTPException(404, "Research run not found")
    if settings.ai_research_max_budget_cents <= 0:
        raise HTTPException(400, "Paid AI research is disabled in configuration")
    if payload.budget_cents > settings.ai_research_max_budget_cents:
        raise HTTPException(400, f"Budget exceeds configured maximum of {settings.ai_research_max_budget_cents} cents")
    if not settings.openai_api_key:
        raise HTTPException(400, "OPENAI_API_KEY is not configured")
    run.budget_cents = payload.budget_cents
    run.status = "queued"
    run.finished_at = None
    for step in run.steps:
        if step.status == "awaiting_paid_approval":
            step.status = "queued"
    db.commit()
    execute_research_run.delay(run.id)
    return research_run_dict(run)


@router.post("/research-runs/{run_id}/steps/{step_kind}/retry", status_code=202)
def retry_research_step(
    run_id: str,
    step_kind: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    run = db.scalar(select(ResearchRun).options(selectinload(ResearchRun.steps), selectinload(ResearchRun.findings)).where(ResearchRun.id == run_id))
    if not run:
        raise HTTPException(404, "Research run not found")
    step = next((item for item in run.steps if item.kind == step_kind), None)
    if not step:
        raise HTTPException(404, "Research step not found")
    if step_kind == "ai_web_research" and run.budget_cents <= 0:
        raise HTTPException(400, "Paid step requires approval and a positive budget")
    step.status = "queued"
    step.error = None
    run.status = "queued"
    run.finished_at = None
    db.commit()
    execute_research_run.delay(run.id, step_kind)
    return research_run_dict(run)


@router.patch("/leads/{account_id}/sales-stage")
def update_sales_stage(
    account_id: str,
    payload: SalesStageUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account:
        raise HTTPException(404, "Lead not found")
    previous = account.sales_stage
    account.sales_stage = payload.stage
    if payload.stage == "won":
        account.relationship_status = "active_client"
    db.add(SalesActivity(
        account_id=account.id, kind="stage_change", occurred_at=utcnow(), notes=payload.notes,
        details={"from": previous, "to": payload.stage}, created_by=user,
    ))
    outcome_stage = {"connected": "reply", "meeting_scheduled": "meeting", "quote_in_progress": "quote", "won": "won", "lost": "lost"}.get(payload.stage)
    if outcome_stage:
        db.add(Outcome(account_id=account.id, stage=outcome_stage, occurred_on=date.today(), reason=payload.notes))
    db.commit()
    return _lead_summary(account)


@router.patch("/leads/{account_id}/profile")
def update_lead_profile(
    account_id: str,
    payload: LeadProfileUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    account = db.scalar(_lead_query().where(AccountGroup.id == account_id))
    if not account:
        raise HTTPException(404, "Lead not found")
    if payload.relationship_status is not None:
        account.relationship_status = payload.relationship_status
    if "best_pitch_angle" in payload.model_fields_set:
        account.best_pitch_angle = payload.best_pitch_angle
    db.commit()
    return _lead_summary(account)


def _set_primary_contact(db: Session, account_id: str, profile: ContactProfile) -> None:
    for other in db.scalars(select(ContactProfile).join(PersonRole).where(
        PersonRole.account_id == account_id, ContactProfile.id != profile.id,
    )).all():
        other.is_primary_contact = False


@router.post("/leads/{account_id}/people")
def add_person(
    account_id: str,
    payload: PersonCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account:
        raise HTTPException(404, "Lead not found")
    normalized = normalize_name(payload.name)
    if db.scalar(select(PersonRole).where(PersonRole.account_id == account.id, PersonRole.normalized_name == normalized)):
        raise HTTPException(409, "A person with this name already exists on the account")
    person = PersonRole(
        account_id=account.id, source_id="manual_research", name=payload.name,
        normalized_name=normalized, role=payload.role, confidence=1.0,
        professional_profile_url=payload.professional_profile_url,
    )
    db.add(person)
    db.flush()
    profile = ContactProfile(
        person_role_id=person.id, preferred_name=payload.preferred_name,
        is_primary_contact=payload.is_primary_contact,
        communication_preference=payload.communication_preference, timezone=payload.timezone,
        interests=payload.interests, tags=payload.tags, relationship_notes=payload.relationship_notes,
    )
    db.add(profile)
    db.flush()
    if profile.is_primary_contact:
        _set_primary_contact(db, account.id, profile)
    db.commit()
    db.refresh(person)
    return _person_dict(person)


@router.patch("/people/{person_id}")
def update_person(
    person_id: str,
    payload: PersonUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    person = db.scalar(select(PersonRole).options(selectinload(PersonRole.profile)).where(PersonRole.id == person_id))
    if not person:
        raise HTTPException(404, "Person not found")
    for field in ("name", "role", "professional_profile_url"):
        if field in payload.model_fields_set:
            value = getattr(payload, field)
            if field == "name" and value:
                person.normalized_name = normalize_name(value)
            setattr(person, field, value)
    profile = person.profile or ContactProfile(person_role_id=person.id)
    if person.profile is None:
        db.add(profile)
    for field in ("preferred_name", "is_primary_contact", "communication_preference", "timezone", "interests", "tags", "relationship_notes"):
        if field in payload.model_fields_set:
            setattr(profile, field, getattr(payload, field))
    db.flush()
    if profile.is_primary_contact:
        _set_primary_contact(db, person.account_id, profile)
    db.commit()
    return _person_dict(person)


@router.get("/leads/{account_id}/activities")
def list_activities(account_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    if not db.get(AccountGroup, account_id):
        raise HTTPException(404, "Lead not found")
    items = db.scalars(select(SalesActivity).where(
        SalesActivity.account_id == account_id,
    ).order_by(SalesActivity.occurred_at.desc())).all()
    return [_activity_dict(item) for item in items]


@router.post("/leads/{account_id}/activities")
def add_activity(
    account_id: str,
    payload: SalesActivityCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account:
        raise HTTPException(404, "Lead not found")
    activity = SalesActivity(
        account_id=account.id, kind=payload.kind, disposition=payload.disposition,
        occurred_at=payload.occurred_at or utcnow(), notes=payload.notes,
        details=payload.details, created_by=user, subject=payload.subject,
        direction=payload.direction, duration_minutes=payload.duration_minutes,
        person_role_id=payload.person_role_id, coverage_evidence_id=payload.coverage_evidence_id,
        meeting_id=payload.meeting_id, outcome=payload.outcome,
    )
    db.add(activity)
    if payload.kind in {"call", "email", "meeting"}:
        account.last_contact_at = activity.occurred_at
    if payload.disposition == "connected" and account.sales_stage in {"uncontacted", "attempting"}:
        account.sales_stage = "connected"
    if payload.disposition == "do_not_contact":
        account.review_status = "suppressed"
        existing = db.scalar(select(SuppressionEntry).where(
            SuppressionEntry.kind == "account", SuppressionEntry.normalized_value == account.id,
        ))
        if not existing:
            db.add(SuppressionEntry(kind="account", normalized_value=account.id, reason="do_not_contact", source=user))
    db.flush()
    if payload.follow_up:
        follow_up = payload.follow_up
        db.add(SalesTask(
            account_id=account.id, kind=follow_up.kind, status="open", title=follow_up.title,
            due_at=follow_up.due_at, priority=follow_up.priority, notes=follow_up.notes,
            person_role_id=payload.person_role_id, activity_id=activity.id,
            meeting_id=payload.meeting_id, created_by=user,
        ))
        db.flush()
        _refresh_next_action(db, account)
    db.commit()
    db.refresh(activity)
    return _activity_dict(activity)


@router.patch("/activities/{activity_id}")
def update_activity(
    activity_id: str,
    payload: SalesActivityUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    activity = db.get(SalesActivity, activity_id)
    if not activity:
        raise HTTPException(404, "Activity not found")
    for field in ("subject", "direction", "duration_minutes", "disposition", "outcome", "occurred_at", "notes", "details"):
        if field in payload.model_fields_set:
            setattr(activity, field, getattr(payload, field))
    db.commit()
    return _activity_dict(activity)


@router.get("/leads/{account_id}/tasks")
def list_tasks(account_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    if not db.get(AccountGroup, account_id):
        raise HTTPException(404, "Lead not found")
    items = db.scalars(select(SalesTask).where(
        SalesTask.account_id == account_id,
    ).order_by(SalesTask.status, SalesTask.due_at)).all()
    return [_task_dict(item) for item in items]


@router.post("/leads/{account_id}/tasks")
def add_task(
    account_id: str,
    payload: SalesTaskCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account:
        raise HTTPException(404, "Lead not found")
    task = SalesTask(
        account_id=account.id, kind=payload.kind, due_at=payload.due_at, notes=payload.notes,
        title=payload.title, priority=payload.priority, person_role_id=payload.person_role_id,
        activity_id=payload.activity_id, meeting_id=payload.meeting_id, created_by=user,
    )
    db.add(task)
    db.flush()
    _refresh_next_action(db, account)
    db.commit()
    db.refresh(task)
    return _task_dict(task)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    payload: SalesTaskUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    task = db.get(SalesTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if payload.status is not None:
        task.status = payload.status
        task.completed_at = utcnow() if payload.status == "completed" else None
    if payload.due_at is not None:
        task.due_at = payload.due_at
    if payload.notes is not None:
        task.notes = payload.notes
    if payload.title is not None:
        task.title = payload.title
    if payload.priority is not None:
        task.priority = payload.priority
    account = db.get_one(AccountGroup, task.account_id)
    db.flush()
    _refresh_next_action(db, account)
    db.commit()
    return _task_dict(task)


@router.post("/leads/{account_id}/enrich", status_code=202)
def enrich_lead(account_id: str, payload: EnrichRequest, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    account = db.get(AccountGroup, account_id)
    source = db.get(SourceSpec, payload.source_id)
    if not account or not source:
        raise HTTPException(404, "Lead or source not found")
    if source.commercial and (not payload.commercial_enabled or payload.budget_cents <= 0):
        raise HTTPException(400, "Commercial source requires per-run opt-in and budget")
    parameters: dict = {}
    queries: list[str] = []
    if payload.source_id == "first_party_web":
        if not account.website:
            raise HTTPException(400, "Lead has no website")
        parameters = {"websites": [account.website]}
    elif payload.source_id == "hunter":
        if not account.domain:
            raise HTTPException(400, "Lead has no domain")
        parameters = {"domains": [account.domain]}
    elif payload.source_id == "email_verifier":
        emails = [contact.value for contact in account.contacts if contact.kind == "email" and contact.scope in {"business", "professional"} and not contact.suppressed]
        if not emails:
            raise HTTPException(400, "Lead has no professional or business email to verify")
        parameters = {
            "account_id": account.id, "emails": emails,
            "cost_per_email_cents": max(1, payload.budget_cents // len(emails)),
        }
    else:
        query = payload.query or f"{account.name} {' '.join(sorted({l.state for l in account.locations if l.state}))}"
        parameters = {"account_queries": [{"account_id": account.id, "query": query}]}
        queries = [query]
    run = SourceRun(
        source_id=source.id, status="queued", budget_cents=payload.budget_cents,
        scope={"states": [l.state for l in account.locations if l.state], "queries": queries, "parameters": parameters, "limit": 100, "commercial_enabled": payload.commercial_enabled, "budget_cents": payload.budget_cents},
    )
    db.add(run)
    db.commit()
    execute_source_run.delay(run.id)
    run.source = source
    return _run_dict(run)


@router.post("/leads/{account_id}/coverage")
def add_manual_coverage(account_id: str, payload: ManualCoverageCreate, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    account = db.get(AccountGroup, account_id)
    source = db.get(SourceSpec, payload.source_id)
    if not account or not source:
        raise HTTPException(404, "Lead or source not found")
    record = RawRecord(
        source_record_id=payload.source_record_id, source_url=payload.source_url,
        brand_name=account.name, domain=account.domain, coverage_type=payload.coverage_type,
        carrier=payload.carrier, policy_identifier=payload.policy_identifier,
        coverage_effective_on=payload.effective_on, coverage_expires_on=payload.expires_on,
        coverage_as_of=payload.coverage_as_of, coverage_confidence=payload.confidence,
        confidence=1.0 if payload.confidence == "exact" else 0.75,
        evidence_excerpt=payload.evidence_excerpt,
        extra={"account_id": account.id},
    )
    ingest_record(db, source, record)
    db.commit()
    return get_lead(account_id, db, _)


def _create_policy_snapshot(account: AccountGroup, payload: PolicyCreate, supersedes_id: str | None = None) -> CoverageEvidence:
    policy_hmac, policy_masked = hmac_policy_id(payload.policy_identifier)
    return CoverageEvidence(
        account_id=account.id, source_id="client_reported", coverage_type=payload.coverage_type,
        carrier=payload.carrier, policy_hmac=policy_hmac, policy_masked=policy_masked,
        effective_on=payload.effective_on, expires_on=payload.expires_on,
        coverage_as_of=payload.coverage_as_of, confidence=payload.confidence,
        policy_status=payload.policy_status, renewal_status=payload.renewal_status,
        source_kind=payload.source_kind, observed_on=payload.observed_on,
        annual_premium=payload.annual_premium, notes=payload.notes,
        supersedes_id=supersedes_id,
    )


@router.post("/leads/{account_id}/policies")
def add_policy(
    account_id: str,
    payload: PolicyCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account:
        raise HTTPException(404, "Lead not found")
    policy = _create_policy_snapshot(account, payload)
    db.add(policy)
    if payload.expires_on and payload.confidence == "exact":
        account.x_date = payload.expires_on
        account.x_date_kind = "policy_expiration"
        account.timing_confidence = "exact"
    db.commit()
    db.refresh(policy)
    return _policy_dict(policy, {policy.id})


@router.post("/policies/{policy_id}/supersede")
def supersede_policy(
    policy_id: str,
    payload: PolicySupersede,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    existing = db.get(CoverageEvidence, policy_id)
    if not existing:
        raise HTTPException(404, "Policy snapshot not found")
    if db.scalar(select(CoverageEvidence).where(CoverageEvidence.supersedes_id == existing.id)):
        raise HTTPException(409, "Policy snapshot has already been superseded")
    account = db.get_one(AccountGroup, existing.account_id)
    replacement = _create_policy_snapshot(account, payload, supersedes_id=existing.id)
    db.add(replacement)
    db.commit()
    db.refresh(replacement)
    return _policy_dict(replacement, {replacement.id})


@router.get("/integrations/google-calendar/status")
def google_calendar_status(db: Session = Depends(get_db), user: str = Depends(require_user)) -> dict:
    from app.models import CalendarConnection
    connection = db.scalar(select(CalendarConnection).where(CalendarConnection.username == user))
    return connection_dict(connection)


@router.post("/integrations/google-calendar/connect")
def google_calendar_connect(user: str = Depends(require_user)) -> dict:
    try:
        return {"authorization_url": authorization_url(user)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/integrations/google-calendar/callback", include_in_schema=False)
async def google_calendar_callback(code: str, state: str, db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        await exchange_code(db, code, state)
    except (ValueError, httpx.HTTPError, jwt.PyJWTError) as exc:
        return RedirectResponse(f"{get_settings().public_app_url}?calendar=error")
    return RedirectResponse(f"{get_settings().public_app_url}?calendar=connected")


@router.delete("/integrations/google-calendar")
def google_calendar_disconnect(db: Session = Depends(get_db), user: str = Depends(require_user)) -> dict:
    from app.models import CalendarConnection
    connection = db.scalar(select(CalendarConnection).where(CalendarConnection.username == user))
    if connection:
        db.delete(connection)
        db.commit()
    return connection_dict(None)


@router.post("/integrations/google-calendar/sync")
async def google_calendar_sync(db: Session = Depends(get_db), user: str = Depends(require_user)) -> dict:
    from app.models import CalendarConnection
    connection = db.scalar(select(CalendarConnection).where(CalendarConnection.username == user))
    if not connection:
        raise HTTPException(409, "Google Calendar is not connected")
    try:
        updated = await sync_managed_events(db, connection)
    except PermissionError as exc:
        db.commit()
        raise HTTPException(401, str(exc)) from exc
    except httpx.HTTPError as exc:
        connection.last_error = str(exc)[:4000]
        db.commit()
        raise HTTPException(502, "Google Calendar synchronization failed") from exc
    return {"updated": updated, **connection_dict(connection)}


@router.get("/leads/{account_id}/meetings")
def list_meetings(account_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    if not db.get(AccountGroup, account_id):
        raise HTTPException(404, "Lead not found")
    meetings = db.scalars(select(Meeting).where(Meeting.account_id == account_id).order_by(Meeting.start_at.desc())).all()
    return [meeting_dict(item) for item in meetings]


@router.post("/leads/{account_id}/meetings")
async def create_meeting(
    account_id: str,
    payload: MeetingCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account:
        raise HTTPException(404, "Lead not found")
    if payload.end_at <= payload.start_at:
        raise HTTPException(400, "Meeting end must be after its start")
    if payload.person_role_id:
        person = db.get(PersonRole, payload.person_role_id)
        if not person or person.account_id != account.id:
            raise HTTPException(400, "Meeting person does not belong to this lead")
    latest_assessment = db.scalar(select(ResearchAssessment).where(
        ResearchAssessment.account_id == account.id,
    ).order_by(ResearchAssessment.assessed_at.desc()))
    if not account.contact_ready_at:
        if not payload.readiness_override_reason:
            blockers = latest_assessment.blockers if latest_assessment else ["research_assessment"]
            raise HTTPException(409, {"message": "Lead is not contact-ready", "blockers": blockers})
        db.add(ReadinessDecision(
            account_id=account.id, assessment_id=latest_assessment.id if latest_assessment else None,
            decision="override", reason=payload.readiness_override_reason, decided_by=user,
        ))
        account.contact_ready_at = utcnow()
        account.research_state = "ready_override"
    meeting = Meeting(
        account_id=account.id, person_role_id=payload.person_role_id, title=payload.title,
        start_at=payload.start_at, end_at=payload.end_at, timezone=payload.timezone,
        location=payload.location, attendees=payload.attendees,
        reminder_minutes=payload.reminder_minutes, create_meet=payload.create_meet,
        send_updates=payload.send_updates, private_prep_notes=payload.private_prep_notes,
        status="draft", sync_status="pending_sync", created_by=user,
    )
    db.add(meeting)
    db.flush()
    meeting.google_event_id = f"m{meeting.id.replace('-', '')}"
    db.commit()
    if get_settings().calendar_enabled:
        try:
            await sync_meeting(db, meeting)
        except (httpx.HTTPError, PermissionError, ValueError) as exc:
            meeting.sync_status = "auth_required" if isinstance(exc, PermissionError) else "pending_sync"
            meeting.sync_error = str(exc)[:4000]
            db.commit()
    if meeting.status == "scheduled" and account.sales_stage not in {"quote_in_progress", "won", "lost"}:
        previous = account.sales_stage
        account.sales_stage = "meeting_scheduled"
        db.add(SalesActivity(
            account_id=account.id, kind="stage_change", occurred_at=utcnow(),
            notes="Meeting scheduled", details={"from": previous, "to": "meeting_scheduled"},
            meeting_id=meeting.id, created_by=user,
        ))
        db.commit()
    return meeting_dict(meeting)


@router.patch("/meetings/{meeting_id}")
async def update_meeting(
    meeting_id: str,
    payload: MeetingUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    for field in ("title", "start_at", "end_at", "timezone", "location", "attendees", "reminder_minutes", "create_meet", "send_updates", "private_prep_notes"):
        if field in payload.model_fields_set:
            setattr(meeting, field, getattr(payload, field))
    if meeting.end_at <= meeting.start_at:
        raise HTTPException(400, "Meeting end must be after its start")
    meeting.sync_status = "pending_sync"
    db.commit()
    try:
        await sync_meeting(db, meeting, patch=True)
    except (httpx.HTTPError, PermissionError, ValueError) as exc:
        meeting.sync_error = str(exc)[:4000]
        db.commit()
    return meeting_dict(meeting)


@router.post("/meetings/{meeting_id}/sync")
async def sync_one_meeting(meeting_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    try:
        await sync_meeting(db, meeting, patch=bool(meeting.google_etag))
    except PermissionError as exc:
        db.commit()
        raise HTTPException(401, str(exc)) from exc
    except httpx.HTTPError as exc:
        meeting.sync_error = str(exc)[:4000]
        db.commit()
        raise HTTPException(502, "Google Calendar synchronization failed") from exc
    return meeting_dict(meeting)


@router.post("/meetings/{meeting_id}/cancel")
async def cancel_one_meeting(meeting_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    try:
        await cancel_meeting(db, meeting)
    except (httpx.HTTPError, PermissionError) as exc:
        meeting.sync_error = str(exc)[:4000]
        db.commit()
        raise HTTPException(502, "Google Calendar cancellation failed") from exc
    return meeting_dict(meeting)


@router.post("/leads/{account_id}/google-validation")
async def google_validation(
    account_id: str,
    payload: GoogleValidationRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_user),
) -> dict:
    account = db.get(AccountGroup, account_id)
    if not account or not account.google_place_id:
        raise HTTPException(404, "Lead has no retained Google Place ID")
    if not payload.confirm_live_request:
        raise HTTPException(400, "Explicit confirmation is required for a live Google request")
    try:
        return await live_validate_place(account.google_place_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except httpx.HTTPError as exc:
        # Never surface provider URLs/keys embedded in transport errors.
        raise HTTPException(503, "Live Google validation is temporarily unavailable") from exc


@router.post("/leads/{account_id}/outcomes")
def add_outcome(account_id: str, payload: OutcomeCreate, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    if not db.get(AccountGroup, account_id):
        raise HTTPException(404, "Lead not found")
    outcome = Outcome(account_id=account_id, **payload.model_dump())
    db.add(outcome)
    db.commit()
    return {"id": outcome.id, **payload.model_dump()}


@router.get("/matches")
def list_matches(status_filter: str = Query("proposed", alias="status"), db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    links = db.scalars(select(EntityLink).options(selectinload(EntityLink.left), selectinload(EntityLink.right)).where(EntityLink.status == status_filter).order_by(EntityLink.score.desc())).all()
    return [{"id": link.id, "status": link.status, "score": link.score, "reasons": link.reasons, "left": _lead_summary(link.left), "right": _lead_summary(link.right)} for link in links]


@router.post("/matches/{link_id}/decision")
def match_decision(link_id: str, payload: MatchDecisionRequest, db: Session = Depends(get_db), user: str = Depends(require_user)) -> dict:
    link = db.scalar(select(EntityLink).options(selectinload(EntityLink.left), selectinload(EntityLink.right)).where(EntityLink.id == link_id))
    if not link:
        raise HTTPException(404, "Match not found")
    merged = decide_link(db, link, payload.decision, user)
    return {"status": "merged" if merged else "decided", "account_id": merged.id if merged else None}


@router.get("/exports")
def list_exports(db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    batches = db.scalars(select(ExportBatch).order_by(ExportBatch.created_at.desc()).limit(100)).all()
    return [{"id": b.id, "status": b.status, "filters": b.filters, "lead_count": b.lead_count, "manifest_hash": b.manifest_hash, "created_at": b.created_at, "error": b.error} for b in batches]


@router.post("/exports")
def export_leads(payload: ExportRequest, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    batch = create_export(db, payload.model_dump())
    return {"id": batch.id, "status": batch.status, "lead_count": batch.lead_count, "manifest_hash": batch.manifest_hash, "download_url": f"/api/exports/{batch.id}/download"}


@router.get("/exports/{batch_id}/download")
def download_export(batch_id: str, db: Session = Depends(get_db), _: str = Depends(require_user)):
    batch = db.get(ExportBatch, batch_id)
    if not batch or batch.status != "completed" or not batch.file_path or not Path(batch.file_path).exists():
        raise HTTPException(404, "Export not available")
    return FileResponse(batch.file_path, media_type="application/zip", filename=f"lead-evidence-{batch.id}.zip")


@router.get("/suppressions")
def list_suppressions(db: Session = Depends(get_db), _: str = Depends(require_user)) -> list[dict]:
    return [{"id": s.id, "kind": s.kind, "value": s.normalized_value, "reason": s.reason, "source": s.source, "created_at": s.created_at} for s in db.scalars(select(SuppressionEntry).order_by(SuppressionEntry.created_at.desc())).all()]


@router.post("/suppressions")
def create_suppression(payload: SuppressionCreate, db: Session = Depends(get_db), _: str = Depends(require_user)) -> dict:
    value = payload.value
    if payload.kind == "email":
        value = normalize_email(value)
    elif payload.kind == "phone":
        value = normalize_phone(value)
    elif payload.kind == "domain":
        value = normalize_domain(value)
    if not value:
        raise HTTPException(400, "Invalid suppression value")
    existing = db.scalar(select(SuppressionEntry).where(SuppressionEntry.kind == payload.kind, SuppressionEntry.normalized_value == value))
    if existing:
        return {"id": existing.id, "kind": existing.kind, "value": existing.normalized_value}
    entry = SuppressionEntry(kind=payload.kind, normalized_value=value, reason=payload.reason, source=payload.source)
    db.add(entry)
    db.commit()
    return {"id": entry.id, "kind": entry.kind, "value": entry.normalized_value}
