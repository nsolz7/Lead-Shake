from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_CEILING
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.connectors.base import ConnectorScope
from app.connectors.website import WebsiteConnector
from app.connectors.registry import get_connector
from app.models import (
    AccountGroup, BusinessEvent, ExposureEvidence, FieldAssertion, Location,
    OwnershipRelationship, PersonRole, ProviderRateCard, ResearchFinding,
    ResearchAssessment, ResearchBatch, ResearchRun, ResearchStep, SalesTask,
    ServiceOffering, SourceSpec, utcnow,
)
from app.services.classification import classify_business
from app.services.entity_resolution import propose_links
from app.services.ingestion import ingest_record
from app.services.normalization import content_hash, normalize_address, normalize_domain, normalize_name, normalize_phone, parse_date
from app.services.scoring import infer_exposure_kinds, score_account


FREE_STEPS = [
    "validate_identity",
    "correlate_public_records",
    "classify_business",
    "website_candidates",
    "first_party_website",
    "free_api_enrichment",
    "rescore_and_brief",
    "manual_follow_up",
    "assess_readiness",
]
AI_STEPS = ["ai_identity_footprint", "ai_ownership_control", "ai_operations_exposures", "ai_people_events", "assess_readiness"]
FOLLOWUP_STEPS = ["first_party_followup", "rescore_and_brief", "assess_readiness"]
RUBRIC_VERSION = "readiness-v1"
DIMENSIONS = (
    "identity", "website", "footprint", "ownership", "decision_maker", "contacts",
    "legal_licenses", "operations_exposures", "insurance_timing", "recent_events", "freshness_conflicts",
)
CRITICAL_DIMENSIONS = ("identity", "website", "footprint", "ownership", "decision_maker", "contacts", "freshness_conflicts")
PROVIDER_POLL_LIMIT = 60


class ProviderResponsePending(RuntimeError):
    """Signal Celery to retry later without occupying a worker while OpenAI runs."""

    def __init__(self, provider_response_id: str):
        super().__init__(f"OpenAI response {provider_response_id} is still running")
        self.provider_response_id = provider_response_id

RATE_CARDS = {
    "gpt-5.6-luna": {
        "id": "openai-gpt-5.6-luna-2026-07-15",
        "effective_on": date(2026, 7, 15),
        "input": 1.0,
        "cached": 0.10,
        "output": 6.0,
        "web": 10.0,
        "source_url": "https://developers.openai.com/api/docs/pricing",
    },
}


def _steps_for_mode(mode: str) -> list[str]:
    if mode == "free_public":
        return FREE_STEPS
    if mode == "ai_analysis":
        return AI_STEPS
    if mode == "first_party_followup":
        return FOLLOWUP_STEPS
    if mode in {"public_first", "legacy_public_first"}:
        return FREE_STEPS
    raise ValueError(f"Unsupported research mode {mode!r}")


def create_research_run(
    db,
    account: AccountGroup,
    mode: str = "free_public",
    budget_cents: int = 0,
    dedupe_key: str | None = None,
    batch_id: str | None = None,
) -> ResearchRun:
    run = ResearchRun(
        account_id=account.id,
        status="queued",
        mode=mode,
        budget_cents=budget_cents,
        dedupe_key=dedupe_key,
        batch_id=batch_id,
    )
    db.add(run)
    db.flush()
    for position, kind in enumerate(_steps_for_mode(mode)):
        db.add(ResearchStep(research_run_id=run.id, kind=kind, position=position, status="queued"))
    db.commit()
    db.refresh(run)
    return run


def research_run_dict(run: ResearchRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "account_id": run.account_id,
        "status": run.status,
        "mode": run.mode,
        "budget_cents": run.budget_cents,
        "authorized_budget_cents": run.budget_cents,
        "spent_cents": run.spent_cents,
        "calculated_cost_microusd": run.calculated_cost_microusd,
        "calculated_cost_usd": run.calculated_cost_microusd / 1_000_000,
        "provider_usage": run.provider_usage,
        "rate_card_id": run.rate_card_id,
        "provider_response_id": run.provider_response_id,
        "summary": run.summary,
        "error": run.error,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
        "steps": [step_dict(step) for step in sorted(run.steps, key=lambda item: item.position)],
        "findings": [finding_dict(finding) for finding in sorted(run.findings, key=lambda item: item.created_at, reverse=True)],
    }


def step_dict(step: ResearchStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "kind": step.kind,
        "position": step.position,
        "status": step.status,
        "spent_cents": step.spent_cents,
        "calculated_cost_microusd": step.calculated_cost_microusd,
        "provider_usage": step.provider_usage,
        "summary": step.summary,
        "error": step.error,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
    }


def finding_dict(finding: ResearchFinding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "field": finding.field_name,
        "source_id": finding.source_id,
        "value": finding.value_json,
        "source_url": finding.source_url,
        "citation_label": finding.citation_label,
        "excerpt": finding.evidence_excerpt,
        "content_hash": finding.content_hash,
        "authority": finding.authority,
        "confidence": finding.confidence,
        "status": finding.status,
        "parser_version": finding.parser_version,
        "retrieved_at": finding.retrieved_at,
        "decided_at": finding.decided_at,
        "decided_by": finding.decided_by,
        "decision_notes": finding.decision_notes,
        "materialized_type": finding.materialized_type,
        "materialized_id": finding.materialized_id,
    }


def research_gaps(account: AccountGroup) -> tuple[int, list[str]]:
    accepted_exposures = [item for item in account.exposures if item.verification_status in {"verified", "accepted"}]
    checks = {
        "identity": bool(account.name and account.classification_status == "target"),
        "geography": any(location.scope_status == "in_scope" and location.state for location in account.locations),
        "website": bool(account.website and account.domain),
        "footprint": account.location_count_verified is not None,
        "ownership": account.ownership_status in {"confirmed", "likely"} or bool(account.ownership_relationships),
        "decision_maker": any(person.confidence >= 0.6 for person in account.people),
        "contacts": any(not contact.suppressed and contact.scope in {"business", "professional"} for contact in account.contacts),
        "licenses": bool(account.permits or account.legal_entities),
        "exposures": bool(accepted_exposures),
        "timing": bool(account.x_date or account.business_events or any(trigger.occurred_on for trigger in account.triggers)),
    }
    gaps = [name for name, complete in checks.items() if not complete]
    return round(100 * sum(checks.values()) / len(checks)), gaps


def _dimension(status: str, reason: str, evidence_ids: list[str] | None = None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "evidence_ids": evidence_ids or []}


def assess_research(db, account: AccountGroup, run: ResearchRun | None = None) -> ResearchAssessment:
    """Create an immutable readiness snapshot while caching the current state on the account."""
    attempted = bool(run and run.status in {"running", "completed", "partial"})
    assertions = list(account.assertions)
    conflicts = [item for item in assertions if item.conflict]
    now = utcnow()
    stale_assertions: list[FieldAssertion] = []
    for assertion in assertions:
        source = db.get(SourceSpec, assertion.source_id)
        retrieved = assertion.retrieved_at
        if retrieved and retrieved.tzinfo is None:
            retrieved = retrieved.replace(tzinfo=timezone.utc)
        if source and retrieved and (now - retrieved).days > source.freshness_days:
            stale_assertions.append(assertion)

    in_scope = [x for x in account.locations if x.scope_status == "in_scope" and x.operating_status == "active"]
    accepted_exposures = [x for x in account.exposures if x.verification_status in {"verified", "accepted"}]
    usable_contacts = [x for x in account.contacts if not x.suppressed and x.scope in {"business", "professional"}]
    people = [x for x in account.people if x.confidence >= 0.6]
    dimensions = {
        "identity": _dimension(
            "found" if account.operating_status == "active" and account.classification_status == "target" else "not_started",
            "Active target identity verified." if account.operating_status == "active" and account.classification_status == "target" else "Active target classification is unresolved.",
        ),
        "website": _dimension(
            "found" if account.website and account.domain else ("attempted_no_evidence" if attempted else "not_started"),
            "Accepted business website is present." if account.website and account.domain else "No accepted first-party domain was found.",
        ),
        "footprint": _dimension(
            "found" if account.location_count_verified is not None and 2 <= account.location_count_verified <= 5 else ("attempted_no_evidence" if attempted else "not_started"),
            f"Verified owner-controlled footprint: {account.location_count_verified}." if account.location_count_verified is not None else f"Observed {len(in_scope)} locations; owner-controlled count remains unverified.",
            [x.id for x in in_scope],
        ),
        "ownership": _dimension(
            "conflict" if any((account.franchise_signal, account.corporate_control_signal, account.pe_signal, account.public_company_signal)) else ("found" if account.ownership_status in {"confirmed", "likely"} else ("attempted_no_evidence" if attempted else "not_started")),
            "Independent control is supported." if account.ownership_status in {"confirmed", "likely"} else "Independent control is unresolved or contradicted.",
            [x.id for x in account.ownership_relationships],
        ),
        "decision_maker": _dimension(
            "found" if people else ("attempted_no_evidence" if attempted else "not_started"),
            "A named decision-maker is available." if people else "No sufficiently supported decision-maker was found.",
            [x.id for x in people],
        ),
        "contacts": _dimension(
            "found" if usable_contacts else ("attempted_no_evidence" if attempted else "not_started"),
            "A business or professional contact path is available." if usable_contacts else "No usable business/professional contact path was found.",
            [x.id for x in usable_contacts],
        ),
        "legal_licenses": _dimension(
            "found" if account.legal_entities or account.permits else ("attempted_no_evidence" if attempted else "not_started"),
            "Legal or licensing evidence is present." if account.legal_entities or account.permits else "Permitted legal/license sources were attempted without evidence.",
            [x.id for x in [*account.legal_entities, *account.permits]],
        ),
        "operations_exposures": _dimension(
            "found" if accepted_exposures or account.services else ("attempted_no_evidence" if attempted else "not_started"),
            "Operations or coverage exposures are documented." if accepted_exposures or account.services else "Operations/exposure sources were attempted without a supported finding.",
            [x.id for x in [*accepted_exposures, *account.services]],
        ),
        "insurance_timing": _dimension(
            "found" if account.coverages or account.x_date or account.business_events else ("attempted_no_evidence" if attempted else "not_started"),
            "Coverage or responsible timing evidence is present." if account.coverages or account.x_date or account.business_events else "Insurance/timing research was attempted; status remains unknown.",
            [x.id for x in [*account.coverages, *account.business_events]],
        ),
        "recent_events": _dimension(
            "found" if account.business_events or any(x.occurred_on for x in account.triggers) else ("attempted_no_evidence" if attempted else "not_started"),
            "Recent dated business activity is present." if account.business_events or any(x.occurred_on for x in account.triggers) else "Recent-event research was attempted without evidence.",
            [x.id for x in [*account.business_events, *account.triggers]],
        ),
        "freshness_conflicts": _dimension(
            "conflict" if conflicts else ("stale" if assertions and len(stale_assertions) == len(assertions) else ("found" if assertions or attempted else "not_started")),
            f"{len(conflicts)} unresolved conflicts." if conflicts else ("All material evidence is stale." if assertions and len(stale_assertions) == len(assertions) else "No unresolved material conflict."),
            [x.id for x in conflicts or stale_assertions],
        ),
    }
    completed = sum(item["status"] in {"found", "attempted_no_evidence"} for item in dimensions.values())
    completeness = round(100 * completed / len(DIMENSIONS))
    blockers = [name for name in CRITICAL_DIMENSIONS if dimensions[name]["status"] != "found"]
    ready = not blockers and account.eligible
    if not account.eligible and "qualification" not in blockers:
        blockers.insert(0, "qualification")
    assessment = ResearchAssessment(
        account_id=account.id, research_run_id=run.id if run else None,
        rubric_version=RUBRIC_VERSION, completeness=completeness, ready=ready,
        dimensions=dimensions, blockers=blockers, assessed_at=now,
    )
    db.add(assessment)
    account.research_completeness = completeness
    account.research_assessed_at = now
    account.research_state = "ready" if ready else ("blocked" if any(dimensions[x]["status"] == "conflict" for x in CRITICAL_DIMENSIONS) else "needs_review")
    account.contact_ready_at = now if ready else None
    db.flush()
    return assessment


def assessment_dict(assessment: ResearchAssessment) -> dict[str, Any]:
    return {
        "id": assessment.id, "account_id": assessment.account_id,
        "research_run_id": assessment.research_run_id, "rubric_version": assessment.rubric_version,
        "completeness": assessment.completeness, "ready": assessment.ready,
        "dimensions": assessment.dimensions, "blockers": assessment.blockers,
        "assessed_at": assessment.assessed_at.isoformat() if assessment.assessed_at else None,
    }


def batch_dict(batch: ResearchBatch) -> dict[str, Any]:
    return {
        "id": batch.id, "mode": batch.mode, "status": batch.status, "filters": batch.filters,
        "account_ids": batch.account_ids, "approved_sources": batch.approved_sources,
        "max_leads": batch.max_leads, "total_budget_cents": batch.total_budget_cents,
        "per_lead_budget_cents": batch.per_lead_budget_cents, "spent_cents": batch.spent_cents,
        "created_by": batch.created_by, "error": batch.error, "created_at": batch.created_at,
        "runs": [run.id for run in batch.runs],
    }


def _add_finding(
    db,
    run: ResearchRun,
    field_name: str,
    value: Any,
    *,
    source_url: str | None = None,
    citation_label: str | None = None,
    excerpt: str | None = None,
    confidence: float = 0.5,
    parser_version: str = "deterministic-v2",
    status: str = "proposed",
    source_id: str | None = None,
) -> ResearchFinding:
    digest = content_hash({"value": value, "source_url": source_url})
    existing = db.scalar(select(ResearchFinding).where(
        ResearchFinding.research_run_id == run.id,
        ResearchFinding.field_name == field_name,
        ResearchFinding.content_hash == digest,
    ))
    if existing:
        return existing
    finding = ResearchFinding(
        research_run_id=run.id,
        account_id=run.account_id,
        source_id=source_id,
        field_name=field_name,
        value_json=value,
        source_url=source_url,
        citation_label=citation_label,
        evidence_excerpt=(excerpt or "")[:500] or None,
        content_hash=digest,
        authority="derived",
        confidence=max(0, min(float(confidence), 0.95)),
        status=status,
        parser_version=parser_version,
    )
    db.add(finding)
    return finding


def _citation_properties(extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            **extra,
            "source_url": {"type": "string"},
            "excerpt": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": [*extra.keys(), "source_url", "excerpt", "confidence"],
        "additionalProperties": False,
    }


def _openai_schema() -> dict[str, Any]:
    nullable_vertical = {"type": ["string", "null"], "enum": [
        "hospitality_alcohol_events", "fitness_recreation", "contractors_trades", "auto_services", None,
    ]}
    return {
        "type": "object",
        "properties": {
            "classification_recommendations": {"type": "array", "items": _citation_properties({
                "kind": {"type": "string", "enum": ["wrong_vertical", "wrong_entity"]},
                "reason": {"type": "string"},
                "recommended_vertical": nullable_vertical,
            })},
            "official_website": _citation_properties({"value": {"type": ["string", "null"]}}),
            "decision_makers": {"type": "array", "items": _citation_properties({
                "name": {"type": "string"}, "role": {"type": ["string", "null"]},
            })},
            "ownership": {"type": "array", "items": _citation_properties({
                "subject_name": {"type": "string"}, "relationship_type": {"type": "string"},
                "object_name": {"type": "string"},
            })},
            "locations": {"type": "array", "items": _citation_properties({
                "name": {"type": ["string", "null"]}, "address1": {"type": "string"},
                "city": {"type": "string"}, "state": {"type": "string"},
                "postal_code": {"type": ["string", "null"]}, "location_role": {"type": "string"},
            })},
            "services": {"type": "array", "items": _citation_properties({
                "name": {"type": "string"}, "category": {"type": ["string", "null"]},
            })},
            "exposures": {"type": "array", "items": _citation_properties({
                "kind": {"type": "string"}, "basis": {"type": "string"},
            })},
            "business_events": {"type": "array", "items": _citation_properties({
                "kind": {"type": "string"}, "label": {"type": "string"},
                "date": {"type": ["string", "null"]},
            })},
            "sales_brief": _citation_properties({
                "reason_to_call": {"type": "string"}, "suggested_opener": {"type": "string"},
                "qualifying_questions": {"type": "array", "items": {"type": "string"}},
                "unresolved_gaps": {"type": "array", "items": {"type": "string"}},
            }),
        },
        "required": [
            "classification_recommendations", "official_website", "decision_makers", "ownership",
            "locations", "services", "exposures", "business_events", "sales_brief",
        ],
        "additionalProperties": False,
    }


def _response_text_and_citations(payload: dict[str, Any]) -> tuple[str, set[str], int]:
    texts: list[str] = []
    citations: set[str] = set()
    search_calls = 0
    for output in payload.get("output", []):
        if output.get("type") == "web_search_call":
            search_calls += 1
            for source in (output.get("action") or {}).get("sources", []):
                if source.get("url"):
                    citations.add(source["url"])
        for item in output.get("content", []):
            if item.get("type") == "output_text" and item.get("text"):
                texts.append(item["text"])
            for annotation in item.get("annotations", []):
                url = annotation.get("url") or (annotation.get("url_citation") or {}).get("url")
                if url:
                    citations.add(url)
    return "\n".join(texts) or payload.get("output_text", ""), citations, search_calls


def ensure_rate_card(db, model: str) -> ProviderRateCard:
    spec = RATE_CARDS.get(model)
    if not spec:
        raise ValueError(f"No enabled rate card exists for model {model!r}; AI analysis is disabled fail-closed")
    card = db.get(ProviderRateCard, spec["id"])
    if card is None:
        card = ProviderRateCard(
            id=spec["id"], provider="openai", model=model, effective_on=spec["effective_on"],
            input_usd_per_million=spec["input"],
            cached_input_usd_per_million=spec["cached"],
            output_usd_per_million=spec["output"],
            web_search_usd_per_thousand=spec["web"], source_url=spec["source_url"], enabled=True,
        )
        db.add(card)
        db.flush()
    if not card.enabled:
        raise ValueError(f"Rate card {card.id} is disabled")
    return card


def calculate_openai_cost_microusd(usage: dict[str, Any], web_search_calls: int, card: ProviderRateCard) -> int:
    input_tokens = int(usage.get("input_tokens") or 0)
    cached_tokens = int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)
    uncached_tokens = max(0, input_tokens - cached_tokens)
    output_tokens = int(usage.get("output_tokens") or 0)
    amount = (
        Decimal(uncached_tokens) * Decimal(str(card.input_usd_per_million))
        + Decimal(cached_tokens) * Decimal(str(card.cached_input_usd_per_million))
        + Decimal(output_tokens) * Decimal(str(card.output_usd_per_million))
        + Decimal(web_search_calls) * Decimal(str(card.web_search_usd_per_thousand)) * Decimal(1000)
    )
    return int(amount.quantize(Decimal("1"), rounding=ROUND_CEILING))


def _known_evidence(account: AccountGroup) -> str:
    accepted = [
        f"- {assertion.field_name}: {assertion.value_json} ({assertion.source_url or assertion.source_id})"
        for assertion in sorted(account.assertions, key=lambda item: item.retrieved_at, reverse=True)[:40]
        if assertion.authority in {"official", "first_party", "open_aggregator"}
    ]
    return "\n".join(accepted) or "- No accepted evidence beyond the lead identity."


def _ai_prompt(account: AccountGroup, focus: str = "complete") -> str:
    locations = "; ".join(
        f"{location.address1 or ''}, {location.city or ''}, {location.state or ''}"
        for location in account.locations if location.scope_status == "in_scope"
    )
    return f"""
Research the public business identity of {account.name}. Known locations: {locations or 'unknown'}.
Accepted website: {account.website or 'unknown'}.
Research focus: {focus.replace('_', ' ')}. Concentrate tool calls on this focus and leave unrelated arrays empty.

Accepted/free evidence:
{_known_evidence(account)}

Return only business or professional facts supported by cited public pages. Recommend wrong_vertical or
wrong_entity when supported, but do not make database changes. Do not infer or report insurance carrier,
policy number, policy date, renewal date, personal phone, home address, or private personal data.
Every non-null claim must include a cited URL and a short supporting excerpt. Distinguish similarly named
businesses. Leave unsupported arrays empty and unsupported website value null.
""".strip()


def _request_limits(prompt: str, schema: dict[str, Any], budget_cents: int, card: ProviderRateCard) -> tuple[int, int]:
    settings = get_settings()
    max_output_tokens = 1200
    # One UTF-8 byte per token plus a fixed tool/schema allowance is intentionally
    # conservative; the actual provider usage is calculated after the response.
    input_upper = len(prompt.encode("utf-8")) + len(json.dumps(schema).encode("utf-8")) + 4000
    fixed = (
        Decimal(input_upper) * Decimal(str(card.input_usd_per_million))
        + Decimal(max_output_tokens) * Decimal(str(card.output_usd_per_million))
    )
    budget_microusd = Decimal(budget_cents * 10_000)
    per_search = Decimal(str(card.web_search_usd_per_thousand)) * Decimal(1000)
    available_calls = int(max(Decimal(0), budget_microusd - fixed) // per_search) if per_search else settings.ai_research_max_tool_calls
    max_tool_calls = min(settings.ai_research_max_tool_calls, available_calls)
    if max_tool_calls < 1:
        minimum_cents = math.ceil((fixed + per_search) / Decimal(10_000))
        raise ValueError(f"Approved ceiling is too low for the bounded AI request; minimum is {minimum_cents} cents")
    return max_output_tokens, max_tool_calls


def validate_ai_configuration(db, account: AccountGroup, budget_cents: int) -> ProviderRateCard:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    if settings.ai_research_max_budget_cents <= 0:
        raise ValueError("AI analysis is disabled by AI_RESEARCH_MAX_BUDGET_CENTS")
    if budget_cents <= 0 or budget_cents > settings.ai_research_max_budget_cents:
        raise ValueError(f"Budget must be between 1 and {settings.ai_research_max_budget_cents} cents")
    card = ensure_rate_card(db, settings.openai_research_model)
    _request_limits(_ai_prompt(account), _openai_schema(), budget_cents, card)
    return card


def _valid_cited_item(item: dict[str, Any], cited_urls: set[str]) -> bool:
    return bool(item.get("source_url") in cited_urls and str(item.get("excerpt") or "").strip())


async def _run_openai_research(db, run: ResearchRun, account: AccountGroup, step: ResearchStep) -> None:
    settings = get_settings()
    card = validate_ai_configuration(db, account, run.budget_cents)
    schema = _openai_schema()
    spent_microusd = sum(item.calculated_cost_microusd for item in run.steps if item.id != step.id)
    remaining_cents = max(0, run.budget_cents - math.ceil(spent_microusd / 10_000))
    if remaining_cents <= 0:
        raise ValueError("The approved AI ceiling has been exhausted")
    prompt = _ai_prompt(account, step.kind)
    max_output_tokens, max_tool_calls = _request_limits(prompt, schema, remaining_cents, card)
    request = {
        "model": settings.openai_research_model,
        "store": False,
        "input": prompt,
        "tools": [{"type": "web_search", "filters": {"blocked_domains": ["linkedin.com", "facebook.com", "instagram.com"]}}],
        "max_tool_calls": max_tool_calls,
        "max_output_tokens": max_output_tokens,
        "include": ["web_search_call.action.sources"],
        "background": True,
        "text": {"format": {"type": "json_schema", "name": "lead_research", "strict": True, "schema": schema}},
    }
    provider_state = step.summary or {}
    provider_id = provider_state.get("provider_response_id")
    poll_count = int(provider_state.get("provider_poll_count") or 0)
    async with httpx.AsyncClient(timeout=120) as client:
        if provider_id:
            response = await client.get(
                f"https://api.openai.com/v1/responses/{provider_id}",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
        else:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=request,
            )
        response.raise_for_status()
        payload = response.json()
        provider_id = payload.get("id") or provider_id
        if not provider_id:
            raise RuntimeError("OpenAI background response did not return a provider ID")
        run.provider_response_id = provider_id
        if payload.get("status") in {"queued", "in_progress"}:
            poll_count += 1
            step.summary = {
                **provider_state,
                "provider_response_id": provider_id,
                "provider_status": payload.get("status"),
                "provider_poll_count": poll_count,
            }
            db.commit()
            if poll_count >= PROVIDER_POLL_LIMIT:
                raise RuntimeError("OpenAI background response did not finish within the bounded polling window")
            raise ProviderResponsePending(provider_id)
        if payload.get("status") not in {None, "completed"}:
            raise RuntimeError(f"OpenAI background response ended with status {payload.get('status')}")
    text, cited_urls, search_calls = _response_text_and_citations(payload)
    if not text:
        raise RuntimeError("OpenAI response contained no structured output")
    result = json.loads(text)
    parser = f"openai:{settings.openai_research_model}"

    mappings = {
        "classification_recommendations": lambda item: (f"{item['kind']}_recommendation", {
            "reason": item["reason"], "recommended_vertical": item.get("recommended_vertical"),
        }),
        "decision_makers": lambda item: ("decision_maker_candidate", {"name": item["name"], "role": item.get("role")}),
        "ownership": lambda item: ("ownership_candidate", {key: item[key] for key in ("subject_name", "relationship_type", "object_name")}),
        "locations": lambda item: ("location_candidate", {key: item.get(key) for key in ("name", "address1", "city", "state", "postal_code", "location_role")}),
        "services": lambda item: ("service_candidate", {"name": item["name"], "category": item.get("category")}),
        "exposures": lambda item: ("exposure_candidate", {"kind": item["kind"], "basis": item["basis"]}),
        "business_events": lambda item: ("business_event_candidate", {"kind": item["kind"], "label": item["label"], "date": item.get("date")}),
    }
    for group, mapper in mappings.items():
        for item in result.get(group, []):
            if not _valid_cited_item(item, cited_urls):
                continue
            field, value = mapper(item)
            _add_finding(
            db, run, field, value, source_url=item["source_url"], excerpt=item["excerpt"],
                confidence=item.get("confidence", 0.5), parser_version=parser, source_id="openai_web_research",
            )
    website = result.get("official_website") or {}
    if website.get("value") and _valid_cited_item(website, cited_urls):
        _add_finding(
            db, run, "website_candidate", website["value"], source_url=website["source_url"],
            excerpt=website["excerpt"], confidence=website.get("confidence", 0.5), parser_version=parser,
            source_id="openai_web_research",
        )
    brief = result.get("sales_brief") or {}
    if _valid_cited_item(brief, cited_urls):
        value = {key: brief.get(key) for key in ("reason_to_call", "suggested_opener", "qualifying_questions", "unresolved_gaps")}
        _add_finding(
            db, run, "sales_brief_candidate", value, source_url=brief["source_url"],
            excerpt=brief["excerpt"], confidence=brief.get("confidence", 0.5), parser_version=parser,
            source_id="openai_web_research",
        )

    usage = payload.get("usage") or {}
    actual_microusd = calculate_openai_cost_microusd(usage, search_calls, card)
    if spent_microusd + actual_microusd > run.budget_cents * 10_000:
        raise RuntimeError("Provider usage exceeded the authorized ceiling; no additional calls will run")
    usage_record = {**usage, "web_search_calls": search_calls, "max_tool_calls": max_tool_calls}
    step.calculated_cost_microusd = actual_microusd
    step.spent_cents = math.ceil(actual_microusd / 10_000) if actual_microusd else 0
    step.provider_usage = usage_record
    step.summary = {
        "citations": len(cited_urls), "provider_usage": usage_record,
        "calculated_cost_microusd": actual_microusd,
        "proposed_findings": len(run.findings),
        "provider_response_id": provider_id,
        "provider_status": "completed",
        "provider_poll_count": poll_count,
    }
    run.rate_card_id = card.id
    run.provider_response_id = payload.get("id")


def _format_sales_brief(account: AccountGroup) -> str:
    completeness, gaps = research_gaps(account)
    exposures = ", ".join(sorted(infer_exposure_kinds(account))) or "not yet verified"
    lines = [
        f"Account: {account.name}",
        f"Opportunity: {account.best_pitch_angle or 'Complete discovery before selecting a pitch.'}",
        f"Verified business exposures: {exposures}",
        f"Research completeness: {completeness}%",
        f"Open questions: {', '.join(gaps) or 'none'}",
    ]
    return "\n".join(lines)


def _source_is_free_approved(source: SourceSpec) -> bool:
    return bool(
        source.enabled and source.automation_allowed and source.policy_status == "approved"
        and source.cost_class in {"open", "free_key"} and not source.overage_possible
    )


def _propose_asserted_websites(db, run: ResearchRun, account: AccountGroup) -> int:
    count = 0
    for assertion in account.assertions:
        if assertion.field_name != "website" or not assertion.value_json or assertion.source_id == "first_party_web":
            continue
        candidate = str(assertion.value_json)
        if account.domain and normalize_domain(candidate) == account.domain:
            continue
        source = db.get(SourceSpec, assertion.source_id)
        if source and source.authority == "official":
            account.website = candidate
            account.domain = normalize_domain(candidate)
            continue
        if source and source.authority == "open_aggregator":
            sibling_assertions = db.scalars(select(FieldAssertion).where(
                FieldAssertion.account_id == account.id,
                FieldAssertion.source_id == assertion.source_id,
                FieldAssertion.source_record_id == assertion.source_record_id,
            )).all()
            values = {item.field_name: item.value_json for item in sibling_assertions}
            known_phones = {
                value for value in [normalize_phone(account.primary_phone), *(normalize_phone(item.phone) for item in account.locations)]
                if value
            }
            candidate_phone = normalize_phone(str(values.get("phone") or ""))
            candidate_address = normalize_address(
                values.get("address1"), values.get("city"), values.get("state"), values.get("postal_code"),
            )
            known_addresses = {item.normalized_address for item in account.locations if item.normalized_address}
            if candidate_phone in known_phones and candidate_address in known_addresses:
                account.website = candidate
                account.domain = normalize_domain(candidate)
                continue
        _add_finding(
            db, run, "website_candidate", candidate, source_url=assertion.source_url,
            excerpt=assertion.evidence_excerpt or f"Website supplied by {assertion.source_id}",
            confidence=min(assertion.confidence, 0.8), parser_version="free-evidence-v1",
            source_id=assertion.source_id,
        )
        count += 1
    return count


async def _crawl_accepted_website(db, account: AccountGroup) -> int:
    if not account.website:
        return 0
    source = db.get_one(SourceSpec, "first_party_web")
    if not _source_is_free_approved(source):
        raise RuntimeError("First-party crawl source is not approved for free automation")
    connector = WebsiteConnector()
    seen = 0
    page_cache = {item.canonical_url: {
        "etag": item.etag, "last_modified": item.last_modified, "content_hash": item.content_hash,
    } for item in account.crawl_pages}
    async for record in connector.discover(ConnectorScope(
        states=[location.state for location in account.locations if location.state],
        limit=100,
        parameters={"websites": [account.website], "page_cache": page_cache},
    )):
        record.extra["account_id"] = account.id
        ingest_record(db, source, record)
        seen += 1
    return seen


async def _run_free_api_enrichment(db, account: AccountGroup) -> dict[str, Any]:
    if not get_settings().free_api_research_enabled:
        return {"status": "skipped", "reason": "FREE_API_RESEARCH_ENABLED is false"}
    attempts: dict[str, Any] = {}
    known_names = {normalize_name(account.name), *(normalize_name(x.legal_name) for x in account.legal_entities)}
    states = sorted({x.state for x in account.locations if x.state}) or ["NC", "SC", "VA"]
    for source_id in ("sam_gov", "usaspending", "sec_edgar", "gleif"):
        source = db.get(SourceSpec, source_id)
        if not source or not _source_is_free_approved(source) or not source.connector_key:
            attempts[source_id] = {"status": "skipped", "reason": "source is not enabled and approved for free automation"}
            continue
        connector = get_connector(source.connector_key)
        matched = 0
        seen = 0
        try:
            async for record in connector.discover(ConnectorScope(states=states, queries=[account.name], limit=10)):
                seen += 1
                candidate_name = normalize_name(record.legal_name or record.brand_name)
                if not candidate_name or candidate_name not in known_names:
                    continue
                record.extra["account_id"] = account.id
                ingest_record(db, source, record)
                matched += 1
            source.last_success_at = utcnow()
            source.last_error = None
            attempts[source_id] = {"status": "completed", "seen": seen, "matched": matched}
        except (ValueError, httpx.HTTPError) as exc:
            source.last_error_at = utcnow()
            source.last_error = str(exc)[:4000]
            attempts[source_id] = {"status": "unavailable", "reason": str(exc)[:500]}
    return attempts


async def execute_research_run(db, run: ResearchRun, only_step: str | None = None) -> None:
    account = db.get(AccountGroup, run.account_id)
    if not account:
        raise ValueError("Research account no longer exists")
    steps = db.scalars(select(ResearchStep).where(
        ResearchStep.research_run_id == run.id,
    ).order_by(ResearchStep.position)).all()
    run.status = "running"
    run.started_at = run.started_at or utcnow()
    run.error = None
    db.commit()
    for step in steps:
        if only_step and step.kind != only_step:
            continue
        if not only_step and step.status == "completed":
            continue
        step.status = "running"
        step.started_at = utcnow()
        step.error = None
        db.commit()
        try:
            if step.kind == "validate_identity":
                invalid = [location.id for location in account.locations if location.scope_status != "in_scope"]
                step.summary = {"in_scope_locations": len(account.locations) - len(invalid), "excluded_locations": len(invalid)}
            elif step.kind == "correlate_public_records":
                step.summary = {"proposed_links": propose_links(db), "note": "Matches already-imported approved public records."}
            elif step.kind == "classify_business":
                if account.vertical in {"hospitality_alcohol_events", "fitness_recreation", "contractors_trades", "auto_services"}:
                    account.classification_status = "target"
                    account.classification_reason = account.classification_reason or "existing_target_vertical"
                    account.classification_confidence = max(account.classification_confidence, 0.8)
                decision = classify_business(None, account.name, account.naics)
                if account.classification_status != "target" and decision.status == "target":
                    account.vertical = decision.vertical
                    account.classification_status = decision.status
                    account.classification_reason = decision.reason
                    account.classification_confidence = decision.confidence
                step.summary = {
                    "status": account.classification_status, "vertical": account.vertical,
                    "reason": account.classification_reason, "policy": account.classification_policy_version,
                }
            elif step.kind == "website_candidates":
                step.summary = {"proposed": _propose_asserted_websites(db, run, account)}
            elif step.kind in {"first_party_website", "first_party_followup"}:
                seen = await _crawl_accepted_website(db, account) if account.website else 0
                step.summary = {"pages_ingested": seen, "blocked": None if account.website else "No accepted website."}
            elif step.kind == "free_api_enrichment":
                step.summary = {"sources": await _run_free_api_enrichment(db, account)}
            elif step.kind.startswith("ai_") and step.kind != "assess_readiness":
                await _run_openai_research(db, run, account, step)
            elif step.kind == "rescore_and_brief":
                score_account(db, account)
                account.research_completeness, gaps = research_gaps(account)
                account.sales_brief = _format_sales_brief(account)
                step.summary = {"score": account.score, "tier": account.tier, "completeness": account.research_completeness, "gaps": gaps}
            elif step.kind == "manual_follow_up":
                states = sorted({location.state for location in account.locations if location.state})
                created = 0
                for state in states:
                    note = f"Permitted manual SOS and workers' compensation verification for {state}"
                    existing = db.scalar(select(SalesTask).where(
                        SalesTask.account_id == account.id, SalesTask.kind == "research",
                        SalesTask.status == "open", SalesTask.notes == note,
                    ))
                    if not existing:
                        db.add(SalesTask(
                            account_id=account.id, kind="research", status="open",
                            due_at=datetime.now(timezone.utc), notes=note, created_by="automation",
                        ))
                        created += 1
                step.summary = {"manual_tasks_created": created, "states": states}
            elif step.kind == "assess_readiness":
                assessment = assess_research(db, account, run)
                step.summary = assessment_dict(assessment)
            step.status = "completed"
        except ProviderResponsePending:
            step.status = "waiting_provider"
            step.finished_at = None
            run.status = "waiting_provider"
            run.error = None
            db.commit()
            raise
        except Exception as exc:
            step.status = "failed"
            step.error = str(exc)[:4000]
            run.error = step.error
        finally:
            if step.status in {"completed", "failed"}:
                step.finished_at = utcnow()
            db.commit()

    statuses = {step.status for step in steps}
    run.calculated_cost_microusd = sum(step.calculated_cost_microusd for step in steps)
    run.spent_cents = math.ceil(run.calculated_cost_microusd / 10_000) if run.calculated_cost_microusd else 0
    run.provider_usage = {
        step.kind: step.provider_usage for step in steps if step.provider_usage
    }
    run.status = "partial" if "failed" in statuses else "completed"
    existing_assessment = db.scalar(select(ResearchAssessment).where(ResearchAssessment.research_run_id == run.id))
    assessment = existing_assessment or assess_research(db, account, run)
    run.summary = {
        "completeness": assessment.completeness, "gaps": assessment.blockers,
        "ready": assessment.ready, "dimensions": assessment.dimensions,
        "free_only": run.mode != "ai_analysis",
    }
    run.finished_at = utcnow()
    if run.batch_id:
        batch = db.get(ResearchBatch, run.batch_id)
        if batch:
            batch.spent_cents = sum(item.spent_cents for item in batch.runs)
            statuses = {item.status for item in batch.runs}
            batch.status = "completed" if statuses and statuses <= {"completed", "partial"} else "running"
    db.commit()


def _finding_assertion(db, finding: ResearchFinding) -> FieldAssertion:
    source_id = finding.source_id or ("openai_web_research" if finding.parser_version.startswith("openai:") else "manual_research")
    assertion = db.scalar(select(FieldAssertion).where(
        FieldAssertion.source_id == source_id,
        FieldAssertion.source_record_id == finding.id,
        FieldAssertion.field_name == finding.field_name,
        FieldAssertion.content_hash == finding.content_hash,
    ))
    if assertion:
        return assertion
    assertion = FieldAssertion(
        account_id=finding.account_id,
        subject_type="account_group",
        subject_id=finding.account_id,
        source_id=source_id,
        source_record_id=finding.id,
        source_url=finding.source_url,
        field_name=finding.field_name,
        value_json=finding.value_json,
        authority="derived",
        confidence=finding.confidence,
        retrieved_at=finding.retrieved_at,
        parser_version=finding.parser_version,
        content_hash=finding.content_hash,
        retention_class="accepted_research_finding",
        evidence_excerpt=finding.evidence_excerpt,
    )
    db.add(assertion)
    db.flush()
    return assertion


def _schedule_followup_run(db, account: AccountGroup) -> ResearchRun | None:
    if not account.domain:
        return None
    freshness_bucket = date.today().toordinal() // 60
    key = f"first-party:{account.id}:{account.domain}:{freshness_bucket}"
    existing = db.scalar(select(ResearchRun).where(ResearchRun.dedupe_key == key))
    if existing:
        return existing
    try:
        return create_research_run(db, account, mode="first_party_followup", dedupe_key=key)
    except IntegrityError:
        db.rollback()
        return db.scalar(select(ResearchRun).where(ResearchRun.dedupe_key == key))


def decide_finding(
    db,
    finding: ResearchFinding,
    decision: str,
    decided_by: str,
    notes: str | None = None,
) -> tuple[ResearchFinding, ResearchRun | None]:
    if decision not in {"accept", "reject"}:
        raise ValueError("Decision must be accept or reject")
    desired_status = "accepted" if decision == "accept" else "rejected"
    if finding.status in {"accepted", "rejected"}:
        if finding.status != desired_status:
            raise RuntimeError("Finding already has a conflicting final decision")
        return finding, None
    if finding.status != "proposed":
        raise RuntimeError("Only proposed findings can be decided")
    finding.status = desired_status
    finding.decided_at = utcnow()
    finding.decided_by = decided_by
    finding.decision_notes = notes
    followup = None
    if decision == "reject":
        db.commit()
        return finding, None

    account = db.get_one(AccountGroup, finding.account_id)
    assertion = _finding_assertion(db, finding)
    value = finding.value_json
    if finding.field_name == "website_candidate":
        website = str(value).strip()
        if not urlparse(website).scheme:
            website = f"https://{website}"
        domain = normalize_domain(website)
        if not domain:
            raise ValueError("Website candidate has no valid domain")
        account.website = website
        account.domain = domain
        finding.materialized_type = "account_website"
        finding.materialized_id = account.id
    elif finding.field_name == "decision_maker_candidate":
        item = value if isinstance(value, dict) else {"name": str(value)}
        normalized_person = normalize_name(item["name"])
        person = db.scalar(select(PersonRole).where(
            PersonRole.account_id == account.id, PersonRole.normalized_name == normalized_person,
        ))
        if not person:
            person = PersonRole(
                account_id=account.id, source_id=assertion.source_id, name=item["name"],
                normalized_name=normalized_person, role=item.get("role"), confidence=finding.confidence,
            )
            db.add(person); db.flush()
        finding.materialized_type, finding.materialized_id = "person_role", person.id
    elif finding.field_name == "ownership_candidate":
        item = value
        relation = db.scalar(select(OwnershipRelationship).where(
            OwnershipRelationship.account_id == account.id, OwnershipRelationship.source_id == assertion.source_id,
            OwnershipRelationship.subject_name == item["subject_name"],
            OwnershipRelationship.relationship_type == item["relationship_type"],
            OwnershipRelationship.object_name == item["object_name"],
        ))
        if not relation:
            relation = OwnershipRelationship(
                account_id=account.id, source_id=assertion.source_id,
                subject_name=item["subject_name"], relationship_type=item["relationship_type"],
                object_name=item["object_name"], confidence=finding.confidence,
                verification_status="accepted", evidence_assertion_id=assertion.id,
            )
            db.add(relation); db.flush()
        account.ownership_status = "likely" if account.ownership_status == "unknown" else account.ownership_status
        finding.materialized_type, finding.materialized_id = "ownership_relationship", relation.id
    elif finding.field_name == "business_event_candidate":
        item = value
        event_kind = item.get("kind") or "business_event"
        event_date = parse_date(item.get("date"))
        event = db.scalar(select(BusinessEvent).where(
            BusinessEvent.account_id == account.id, BusinessEvent.source_id == assertion.source_id,
            BusinessEvent.kind == event_kind, BusinessEvent.label == item["label"],
            BusinessEvent.occurred_on == event_date,
        ))
        if not event:
            event = BusinessEvent(
                account_id=account.id, source_id=assertion.source_id, kind=event_kind,
                label=item["label"], occurred_on=event_date, confidence=finding.confidence,
                verification_status="accepted", evidence_assertion_id=assertion.id,
            )
            db.add(event); db.flush()
        finding.materialized_type, finding.materialized_id = "business_event", event.id
    elif finding.field_name == "location_candidate":
        item = value
        normalized = normalize_address(item.get("address1"), item.get("city"), item.get("state"), item.get("postal_code"))
        location = db.scalar(select(Location).where(Location.account_id == account.id, Location.normalized_address == normalized))
        if not location:
            location = Location(
                account_id=account.id, source_id=assertion.source_id, name=item.get("name") or account.name,
                address1=item.get("address1"), city=item.get("city"), state=str(item.get("state") or "").upper()[:2] or None,
                postal_code=item.get("postal_code"), normalized_address=normalized, location_role=item.get("location_role") or "operating",
                authoritative=False, confidence=finding.confidence, verification_status="accepted",
                evidence_assertion_id=assertion.id,
            )
            db.add(location); db.flush()
        finding.materialized_type, finding.materialized_id = "location", location.id
    elif finding.field_name == "service_candidate":
        item = value
        normalized_service = normalize_name(item["name"])
        service = db.scalar(select(ServiceOffering).where(
            ServiceOffering.account_id == account.id, ServiceOffering.source_id == assertion.source_id,
            ServiceOffering.normalized_name == normalized_service,
        ))
        if not service:
            service = ServiceOffering(
                account_id=account.id, source_id=assertion.source_id, name=item["name"],
                normalized_name=normalized_service, category=item.get("category"),
                confidence=finding.confidence, verification_status="accepted", evidence_assertion_id=assertion.id,
            )
            db.add(service); db.flush()
        finding.materialized_type, finding.materialized_id = "service_offering", service.id
    elif finding.field_name == "exposure_candidate":
        item = value
        exposure = db.scalar(select(ExposureEvidence).where(
            ExposureEvidence.account_id == account.id, ExposureEvidence.source_id == assertion.source_id,
            ExposureEvidence.kind == item["kind"], ExposureEvidence.basis == item["basis"],
        ))
        if not exposure:
            exposure = ExposureEvidence(
                account_id=account.id, source_id=assertion.source_id, kind=item["kind"], basis=item["basis"],
                confidence=finding.confidence, verification_status="accepted", evidence_assertion_id=assertion.id,
            )
            db.add(exposure); db.flush()
        finding.materialized_type, finding.materialized_id = "exposure_evidence", exposure.id
    elif finding.field_name == "wrong_entity_recommendation":
        account.classification_status = "excluded"
        account.classification_reason = "wrong_entity"
        account.classification_confidence = finding.confidence
        account.data_status = "quarantined"
        finding.materialized_type, finding.materialized_id = "account_quarantine", account.id
    elif finding.field_name == "wrong_vertical_recommendation":
        item = value if isinstance(value, dict) else {}
        recommended = item.get("recommended_vertical")
        if recommended:
            account.vertical = recommended
            account.classification_status = "target"
            account.classification_reason = "accepted_ai_reclassification"
        else:
            account.classification_status = "excluded"
            account.classification_reason = "wrong_vertical"
            account.data_status = "quarantined"
        account.classification_confidence = finding.confidence
        finding.materialized_type, finding.materialized_id = "account_classification", account.id
    elif finding.field_name == "sales_brief_candidate":
        item = value
        account.sales_brief = "\n".join(filter(None, [
            f"Reason to call: {item.get('reason_to_call', '')}",
            f"Suggested opener: {item.get('suggested_opener', '')}",
            "Qualifying questions: " + " | ".join(item.get("qualifying_questions", [])),
            "Unresolved gaps: " + ", ".join(item.get("unresolved_gaps", [])),
        ]))
        finding.materialized_type, finding.materialized_id = "sales_brief", account.id

    db.flush()
    db.expire(account, ["locations", "people", "assertions", "services", "exposures", "ownership_relationships", "business_events"])
    score_account(db, account)
    account.research_completeness, _ = research_gaps(account)
    if finding.field_name == "website_candidate":
        followup = _schedule_followup_run(db, account)
    db.commit()
    return finding, followup
