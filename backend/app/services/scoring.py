from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import AccountGroup, ScoreContribution, SourceSpec
from app.services.qualification import qualify_account


SCORE_VERSION = "rules-v2"


def infer_exposure_kinds(account: AccountGroup) -> set[str]:
    count = account.location_count_verified or 0
    exposure_kinds: set[str] = set()
    exposure_kinds.update(
        exposure.kind for exposure in account.exposures
        if exposure.verification_status in {"verified", "accepted"} and exposure.confidence >= 0.6
    )
    if count >= 2:
        exposure_kinds.update({"property", "general_liability", "workers_comp"})
    if any("alcohol" in permit.kind.lower() or "abc" in permit.kind.lower() for permit in account.permits):
        exposure_kinds.add("liquor_liability")
    if any(trigger.kind in {"fleet", "fmcsa", "commercial_auto"} for trigger in account.triggers):
        exposure_kinds.add("commercial_auto")
    if account.vertical == "contractors_trades":
        exposure_kinds.update({"equipment", "inland_marine", "commercial_auto"})
    if account.vertical == "auto_services":
        exposure_kinds.update({"garagekeepers", "commercial_auto"})
    if account.vertical == "hospitality_alcohol_events":
        exposure_kinds.update({"event_liability", "cyber"})
    if account.vertical == "fitness_recreation":
        exposure_kinds.update({"professional_liability", "abuse_molestation"})
    return exposure_kinds


def _add(
    db: Session,
    account: AccountGroup,
    category: str,
    factor: str,
    points: int,
    max_points: int,
    explanation: str,
    evidence_ids: list[str] | None = None,
) -> None:
    db.add(ScoreContribution(
        account_id=account.id,
        score_version=SCORE_VERSION,
        category=category,
        factor=factor,
        points=max(0, min(points, max_points)),
        max_points=max_points,
        explanation=explanation,
        evidence_ids=evidence_ids or [],
    ))


def score_account(db: Session, account: AccountGroup, today: date | None = None) -> AccountGroup:
    today = today or date.today()
    qualify_account(db, account)
    db.execute(delete(ScoreContribution).where(ScoreContribution.account_id == account.id))
    db.expire(account, ["score_contributions"])

    vertical_points = 10 if account.vertical != "unknown" else 0
    _add(db, account, "fit", "target_vertical", vertical_points, 10, f"Vertical is {account.vertical}.")

    count = account.location_count_verified or 0
    complexity_points = 10 if count in (3, 4) else (8 if count in (2, 5) else 0)
    _add(db, account, "fit", "operational_complexity", complexity_points, 10, f"Verified physical location count is {count or 'unknown'}.")

    ownership_points = 6 if account.ownership_status == "confirmed" else (4 if account.ownership_status == "likely" else 0)
    _add(db, account, "fit", "independent_control", ownership_points, 6, f"Independent-control evidence is {account.ownership_status}.")

    states = {location.state for location in account.locations if location.state}
    proximity_points = 4 if "NC" in states else (3 if states & {"SC", "VA"} else 0)
    _add(db, account, "fit", "serviceability", proximity_points, 4, f"Operating states: {', '.join(sorted(states)) or 'unknown'}.")

    timing_points = 0
    timing_explanation = "No dated insurance or business trigger."
    next_action = None
    if account.x_date:
        days = (account.x_date - today).days
        if account.timing_confidence == "exact":
            timing_points = 15 if 60 <= days <= 150 else (10 if 0 <= days <= 180 else (5 if 181 <= days <= 365 else 0))
            if days >= 0:
                next_action = max(today, account.x_date - timedelta(days=120))
        elif account.timing_confidence == "inferred_anniversary":
            timing_points = 10 if 45 <= days <= 150 else (5 if 0 <= days <= 180 else 0)
            if days >= 0:
                next_action = max(today, account.x_date - timedelta(days=90))
        timing_explanation = f"{account.timing_confidence} timing date is {account.x_date.isoformat()}."
    _add(db, account, "timing", "renewal_timing", timing_points, 15, timing_explanation)

    recent_triggers = [
        t for t in account.triggers
        if t.occurred_on and not t.risk_review_only and 0 <= (today - t.occurred_on).days <= 365
    ]
    recent_business_events = [
        event for event in account.business_events
        if event.occurred_on and event.verification_status in {"verified", "accepted"}
        and 0 <= (today - event.occurred_on).days <= 365
    ]
    event_count = len(recent_triggers) + len(recent_business_events)
    trigger_points = min(10, event_count * 4)
    _add(db, account, "timing", "business_events", trigger_points, 10, f"{event_count} accepted non-risk business event(s) in the last year.")
    if next_action is None and event_count:
        next_action = today

    exposure_kinds = infer_exposure_kinds(account)
    exposure_points = min(25, len(exposure_kinds) * 4)
    _add(db, account, "coverage_opportunity", "verified_exposures", exposure_points, 25, f"Verified or strongly inferred exposures: {', '.join(sorted(exposure_kinds)) or 'none'}.")

    named_people = [p for p in account.people if p.confidence >= 0.6]
    usable_contacts = [c for c in account.contacts if not c.suppressed and c.scope in {"business", "professional"}]
    contact_points = min(10, (4 if named_people else 0) + min(6, len(usable_contacts) * 2))
    _add(db, account, "contactability", "decision_maker_paths", contact_points, 10, f"{len(named_people)} named person(s), {len(usable_contacts)} usable contact path(s).")

    assertions = account.assertions
    authoritative = sum(1 for a in assertions if a.authority in {"official", "first_party"})
    conflicts = sum(1 for a in assertions if a.conflict)
    source_specs = {source_id: db.get(SourceSpec, source_id) for source_id in {a.source_id for a in assertions}}
    stale = sum(
        1 for assertion in assertions
        if (today - assertion.retrieved_at.date()).days > (source_specs[assertion.source_id].freshness_days if source_specs.get(assertion.source_id) else 90)
    )
    evidence_points = min(10, authoritative * 2 + min(4, len({a.source_id for a in assertions})))
    evidence_points = max(0, evidence_points - min(4, conflicts * 2) - min(3, stale))
    _add(db, account, "evidence_quality", "authority_freshness_conflicts", evidence_points, 10, f"{authoritative} authoritative assertion(s), {stale} stale assertion(s), {conflicts} conflict(s).")

    db.flush()
    total = sum(
        contribution.points
        for contribution in db.query(ScoreContribution).filter(ScoreContribution.account_id == account.id).all()
    )
    account.score = total
    account.score_version = SCORE_VERSION
    account.tier = "HOLD" if not account.eligible or total < 50 else ("A" if total >= 80 else ("B" if total >= 65 else "C"))
    account.next_action_date = next_action
    account.best_pitch_angle = _pitch_angle(exposure_kinds, account.timing_confidence)
    db.flush()
    return account


def _pitch_angle(exposures: set[str], timing_confidence: str) -> str:
    ordered = [
        ("liquor_liability", "liquor liability and multi-location package review"),
        ("garagekeepers", "garagekeepers, auto, and property program review"),
        ("equipment", "equipment, auto, workers' compensation, and umbrella consolidation"),
        ("event_liability", "multi-location property, events, and umbrella consolidation"),
        ("professional_liability", "premises, professional liability, cyber, and umbrella review"),
    ]
    base = next((label for exposure, label in ordered if exposure in exposures), "multi-location coverage consolidation")
    return f"{base}; timed renewal review" if timing_confidence in {"exact", "inferred_anniversary"} else base


def rescore_all(db: Session) -> int:
    accounts = db.query(AccountGroup).all()
    for account in accounts:
        score_account(db, account)
    db.commit()
    return len(accounts)
