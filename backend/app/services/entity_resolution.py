from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session
from rapidfuzz.fuzz import ratio

from app.models import (
    AccountGroup, Brand, ContactPoint, CoverageEvidence, EntityLink, FieldAssertion,
    LegalEntity, Location, Outcome, PermitLicense, PersonRole, ResearchFinding,
    ResearchRun, ReviewDecision, SalesActivity, SalesTask, ScoreContribution, Trigger, utcnow,
)
from app.services.scoring import score_account


def propose_links(db: Session, minimum_score: float = 72) -> int:
    accounts = db.scalars(select(AccountGroup).where(
        AccountGroup.data_status == "active",
    ).order_by(AccountGroup.normalized_name)).all()
    by_id = {account.id: account for account in accounts}
    buckets: dict[str, list[AccountGroup]] = defaultdict(list)
    for account in accounts:
        first_token = account.normalized_name.split(" ", 1)[0] if account.normalized_name else ""
        keys = {f"name:{first_token}"}
        if account.domain:
            keys.add(f"domain:{account.domain}")
        if account.primary_phone:
            keys.add(f"phone:{account.primary_phone}")
        keys.update(
            f"address:{location.normalized_address}"
            for location in account.locations if location.scope_status == "in_scope"
        )
        for key in keys:
            buckets[key].append(account)

    candidate_pairs: set[tuple[str, str]] = set()
    for bucket in buckets.values():
        for index, left in enumerate(bucket):
            for right in bucket[index + 1:]:
                candidate_pairs.add(tuple(sorted((left.id, right.id))))

    created = 0
    for low, high in sorted(candidate_pairs):
        left, right = by_id[low], by_id[high]
        reasons: list[str] = []
        score = 0.0
        if left.domain and left.domain == right.domain:
            score += 60
            reasons.append("shared_domain")
        if left.primary_phone and left.primary_phone == right.primary_phone:
            score += 50
            reasons.append("shared_phone")
        name_score = ratio(left.normalized_name, right.normalized_name)
        if name_score >= 90:
            score += 30
            reasons.append(f"name_similarity:{name_score}")
        left_addresses = {loc.normalized_address for loc in left.locations if loc.scope_status == "in_scope"}
        right_addresses = {loc.normalized_address for loc in right.locations if loc.scope_status == "in_scope"}
        if left_addresses & right_addresses:
            score += 35
            reasons.append("shared_address")
        if score < minimum_score:
            continue
        exists = db.scalar(select(EntityLink.id).where(EntityLink.left_account_id == low, EntityLink.right_account_id == high))
        if not exists:
            db.add(EntityLink(left_account_id=low, right_account_id=high, score=min(score, 100), reasons=reasons))
            created += 1
    db.commit()
    return created


def merge_accounts(db: Session, keep: AccountGroup, remove: AccountGroup) -> AccountGroup:
    for brand in list(remove.brands):
        duplicate = db.scalar(select(Brand).where(Brand.account_id == keep.id, Brand.normalized_name == brand.normalized_name))
        if duplicate:
            for location in list(remove.locations):
                if location.brand_id == brand.id:
                    location.brand_id = duplicate.id
            db.delete(brand)
        else:
            brand.account_id = keep.id

    for location in list(remove.locations):
        duplicate = db.scalar(select(Location).where(Location.account_id == keep.id, Location.normalized_address == location.normalized_address))
        if duplicate:
            duplicate.authoritative = duplicate.authoritative or location.authoritative
            duplicate.confidence = max(duplicate.confidence, location.confidence)
            db.delete(location)
        else:
            location.account_id = keep.id

    for contact in list(remove.contacts):
        duplicate = db.scalar(select(ContactPoint).where(
            ContactPoint.account_id == keep.id,
            ContactPoint.kind == contact.kind,
            ContactPoint.normalized_value == contact.normalized_value,
        ))
        if duplicate:
            duplicate.confidence = max(duplicate.confidence, contact.confidence)
            duplicate.suppressed = duplicate.suppressed or contact.suppressed
            db.delete(contact)
        else:
            contact.account_id = keep.id

    for model in (
        LegalEntity, PersonRole, PermitLicense, CoverageEvidence, Trigger, FieldAssertion,
        ReviewDecision, Outcome, ResearchRun, ResearchFinding, SalesActivity, SalesTask,
    ):
        for item in db.scalars(select(model).where(model.account_id == remove.id)).all():
            item.account_id = keep.id

    db.execute(delete(ScoreContribution).where(ScoreContribution.account_id.in_([keep.id, remove.id])))
    db.execute(delete(EntityLink).where(or_(
        EntityLink.left_account_id.in_([keep.id, remove.id]),
        EntityLink.right_account_id.in_([keep.id, remove.id]),
    )))
    keep.ownership_status = "confirmed" if "confirmed" in {keep.ownership_status, remove.ownership_status} else keep.ownership_status
    keep.franchise_signal = keep.franchise_signal or remove.franchise_signal
    keep.corporate_control_signal = keep.corporate_control_signal or remove.corporate_control_signal
    keep.pe_signal = keep.pe_signal or remove.pe_signal
    keep.public_company_signal = keep.public_company_signal or remove.public_company_signal
    db.delete(remove)
    db.flush()
    score_account(db, keep)
    db.commit()
    return keep


def decide_link(db: Session, link: EntityLink, decision: str, reviewer: str) -> AccountGroup | None:
    if decision == "accept":
        return merge_accounts(db, link.left, link.right)
    link.status = "rejected" if decision in {"reject", "split"} else decision
    link.decided_at = utcnow()
    link.decided_by = reviewer
    db.commit()
    return None
