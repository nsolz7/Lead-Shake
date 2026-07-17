from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.connectors.base import RawRecord
from app.models import (
    AccountGroup, Brand, BusinessEvent, ContactPoint, CoverageEvidence, CrawlPage, ExposureEvidence,
    FieldAssertion, LegalEntity, Location, OwnershipRelationship, PermitLicense, PersonRole,
    ServiceOffering, SourceRun, SourceSpec, Trigger, utcnow,
)
from app.services.classification import ClassificationDecision, POLICY_VERSION, classify_business
from app.services.normalization import (
    content_hash, hmac_policy_id, normalize_address, normalize_domain, normalize_email,
    normalize_name, normalize_phone, normalize_operating_status, parse_date,
)
from app.services.scoring import score_account


GOOGLE_ALLOWED = {"place_id"}
SINGLETON_ASSERTIONS = {
    "vertical", "naics", "website", "domain", "ownership_status", "franchise_signal",
    "corporate_control_signal", "pe_signal", "public_company_signal",
}


def _find_account(db: Session, record: RawRecord) -> AccountGroup | None:
    if record.extra.get("account_id"):
        account = db.get(AccountGroup, record.extra["account_id"])
        if account:
            return account
    domain = normalize_domain(record.domain or record.website)
    phone = normalize_phone(record.phone)
    name = normalize_name(record.brand_name or record.legal_name)
    if record.entity_external_id:
        jurisdiction = record.state or None
        query = select(LegalEntity).where(LegalEntity.external_id == record.entity_external_id)
        if jurisdiction:
            query = query.where(LegalEntity.jurisdiction == jurisdiction)
        entity = db.scalar(query)
        if entity:
            return db.get(AccountGroup, entity.account_id)
    if record.permit_number:
        permit = db.scalar(select(PermitLicense).where(
            PermitLicense.external_id == record.permit_number,
        ))
        if permit:
            return db.get(AccountGroup, permit.account_id)
    if domain:
        account = db.scalar(select(AccountGroup).where(AccountGroup.domain == domain))
        if account:
            return account
    if phone:
        account = db.scalar(select(AccountGroup).where(AccountGroup.primary_phone == phone))
        if account:
            return account
    if name:
        candidates = db.scalars(select(AccountGroup).where(AccountGroup.normalized_name == name)).all()
        if record.state and record.city:
            normalized_location = normalize_address(record.address1, record.city, record.state, record.postal_code)
            for candidate in candidates:
                if any(location.normalized_address == normalized_location for location in candidate.locations):
                    return candidate
    return None


def ingest_record(db: Session, source: SourceSpec, record: RawRecord, run: SourceRun | None = None) -> tuple[AccountGroup | None, bool]:
    payload = record.model_dump(mode="json", exclude_none=True)
    if source.id == "google_places_ids" and any(
        key not in GOOGLE_ALLOWED | {"source_record_id", "source_url", "retrieved_at", "confidence", "extra"}
        for key in record.model_fields_set
    ):
        raise ValueError("Google Places persistence allowlist violation")

    account = _find_account(db, record)
    created = False
    display_name = record.brand_name or record.legal_name
    classification = classify_business(record.category, display_name, record.naics)
    if record.vertical in {"hospitality_alcohol_events", "fitness_recreation", "contractors_trades", "auto_services"}:
        classification = ClassificationDecision(
            record.vertical, "target", "explicit_source_vertical", 0.95, POLICY_VERSION,
        )
    if account is None and display_name:
        trusted_website = record.website if source.authority in {"official", "first_party"} else None
        classification_status = "excluded" if record.franchise_signal else classification.status
        classification_reason = "confirmed_franchise" if record.franchise_signal else classification.reason
        account = AccountGroup(
            name=display_name,
            normalized_name=normalize_name(display_name),
            vertical=record.vertical or classification.vertical,
            classification_status=classification_status,
            classification_reason=classification_reason,
            classification_policy_version=classification.policy_version,
            classification_confidence=classification.confidence,
            naics=record.naics,
            operating_status=normalize_operating_status(record.operating_status),
            ownership_status=record.ownership_status or "unknown",
            website=trusted_website,
            domain=normalize_domain(record.domain or trusted_website),
            primary_phone=normalize_phone(record.phone),
            primary_email=normalize_email(record.email),
            franchise_signal=record.franchise_signal,
            corporate_control_signal=record.corporate_control_signal,
            pe_signal=record.pe_signal,
            public_company_signal=record.public_company_signal,
            data_status="quarantined" if classification_status == "excluded" else "active",
        )
        db.add(account)
        db.flush()
        created = True

    if account is None:
        # IDs-only validation cannot create a lead without independently sourced identity data.
        return None, False

    if record.place_id:
        account.google_place_id = record.place_id

    page = record.extra.get("crawl_page")
    if isinstance(page, dict) and page.get("canonical_url"):
        crawl_page = db.scalar(select(CrawlPage).where(
            CrawlPage.account_id == account.id, CrawlPage.canonical_url == page["canonical_url"],
        ))
        if crawl_page is None:
            crawl_page = CrawlPage(account_id=account.id, url=page.get("url") or page["canonical_url"], canonical_url=page["canonical_url"])
            db.add(crawl_page)
        crawl_page.fetched_at = record.retrieved_at
        crawl_page.status_code = page.get("status_code")
        crawl_page.content_type = page.get("content_type")
        crawl_page.content_hash = page.get("content_hash") or crawl_page.content_hash
        crawl_page.etag = page.get("etag") or crawl_page.etag
        crawl_page.last_modified = page.get("last_modified") or crawl_page.last_modified
        crawl_page.robots_status = page.get("robots_status") or "allowed"
        crawl_page.error = page.get("error")
    if record.website and not account.website and source.authority in {"official", "first_party"}:
        account.website = record.website
        account.domain = normalize_domain(record.website)
    if record.phone and not account.primary_phone:
        account.primary_phone = normalize_phone(record.phone)
    if record.email and not account.primary_email:
        account.primary_email = normalize_email(record.email)
    if record.vertical and account.vertical == "unknown":
        account.vertical = record.vertical
    if record.ownership_status in {"confirmed", "likely"}:
        if account.ownership_status != "confirmed":
            account.ownership_status = record.ownership_status
    account.franchise_signal = account.franchise_signal or record.franchise_signal
    account.corporate_control_signal = account.corporate_control_signal or record.corporate_control_signal
    account.pe_signal = account.pe_signal or record.pe_signal
    account.public_company_signal = account.public_company_signal or record.public_company_signal
    protected_classification = account.review_status != "new" or bool(account.sales_activities)
    if not protected_classification:
        if record.franchise_signal:
            account.classification_status = "excluded"
            account.classification_reason = "confirmed_franchise"
            account.classification_confidence = max(account.classification_confidence, 0.99)
            account.data_status = "quarantined"
        elif classification.status == "excluded":
            account.classification_status = classification.status
            account.classification_reason = classification.reason
            account.classification_policy_version = classification.policy_version
            account.classification_confidence = classification.confidence
            account.data_status = "quarantined"
        elif account.classification_status != "target" and classification.status == "target":
            account.vertical = record.vertical or classification.vertical
            account.classification_status = "target"
            account.classification_reason = classification.reason
            account.classification_policy_version = classification.policy_version
            account.classification_confidence = classification.confidence

    brand_name = record.brand_name or account.name
    normalized_brand = normalize_name(brand_name)
    brand = db.scalar(select(Brand).where(Brand.account_id == account.id, Brand.normalized_name == normalized_brand))
    if brand is None:
        brand = Brand(account_id=account.id, name=brand_name, normalized_name=normalized_brand, domain=normalize_domain(record.website))
        db.add(brand)
        db.flush()

    location = None
    if record.address1 or (record.city and record.state):
        normalized_address = normalize_address(record.address1, record.city, record.state, record.postal_code)
        location = db.scalar(select(Location).where(Location.account_id == account.id, Location.normalized_address == normalized_address))
        if location is None:
            location = Location(
                account_id=account.id,
                brand_id=brand.id,
                source_id=source.id,
                name=brand_name,
                address1=record.address1,
                address2=record.address2,
                city=record.city,
                state=(record.state or "").upper()[:2] or None,
                postal_code=record.postal_code,
                county=record.county,
                normalized_address=normalized_address,
                latitude=record.latitude,
                longitude=record.longitude,
                phone=normalize_phone(record.phone),
                operating_status=normalize_operating_status(record.operating_status),
                physical=record.physical,
                authoritative=source.authority in {"official", "first_party"},
                confidence=record.confidence,
            )
            db.add(location)
            db.flush()
        else:
            location.authoritative = location.authoritative or source.authority in {"official", "first_party"}
            location.confidence = max(location.confidence, record.confidence)
            location.operating_status = normalize_operating_status(record.operating_status)
            if record.state:
                location.scope_status = "in_scope"

    if record.legal_name:
        legal_name = normalize_name(record.legal_name)
        query = select(LegalEntity).where(LegalEntity.account_id == account.id, LegalEntity.normalized_name == legal_name)
        if record.entity_external_id:
            query = select(LegalEntity).where(LegalEntity.jurisdiction == (record.state or source.jurisdiction), LegalEntity.external_id == record.entity_external_id)
        entity = db.scalar(query)
        if entity is None:
            db.add(LegalEntity(
                account_id=account.id,
                source_id=source.id,
                legal_name=record.legal_name,
                normalized_name=legal_name,
                entity_type=record.entity_type,
                jurisdiction=record.state or source.jurisdiction,
                external_id=record.entity_external_id,
                status=record.entity_status,
                formed_on=record.formed_on,
                registered_agent_name=record.registered_agent_name,
                registered_agent_type=record.registered_agent_type,
            ))

    person = None
    if record.person_name:
        normalized_person = normalize_name(record.person_name)
        person = db.scalar(select(PersonRole).where(PersonRole.account_id == account.id, PersonRole.normalized_name == normalized_person))
        if person is None:
            person = PersonRole(
                account_id=account.id,
                source_id=source.id,
                name=record.person_name,
                normalized_name=normalized_person,
                role=record.person_role,
                ownership_signal=record.ownership_signal,
                confidence=record.confidence,
                professional_profile_url=record.professional_profile_url,
            )
            db.add(person)
            db.flush()

    for item in record.extra.get("people", []):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        normalized_person = normalize_name(name)
        existing_person = db.scalar(select(PersonRole).where(
            PersonRole.account_id == account.id, PersonRole.normalized_name == normalized_person,
        ))
        if existing_person is None:
            db.add(PersonRole(
                account_id=account.id, source_id=source.id, name=name, normalized_name=normalized_person,
                role=item.get("role"), professional_profile_url=item.get("profile"), confidence=record.confidence,
            ))

    for kind, value, scope in (
        ("email", record.email, "professional" if person else "business"),
        ("phone", record.phone, "business"),
        ("contact_form", record.contact_form_url, "business"),
        ("profile", record.professional_profile_url, "professional"),
    ):
        normalized = normalize_email(value) if kind == "email" else (normalize_phone(value) if kind == "phone" else value)
        if not normalized:
            continue
        existing = db.scalar(select(ContactPoint).where(ContactPoint.account_id == account.id, ContactPoint.kind == kind, ContactPoint.normalized_value == normalized))
        if existing is None:
            db.add(ContactPoint(
                account_id=account.id,
                person_role_id=person.id if person else None,
                source_id=source.id,
                kind=kind,
                value=value,
                normalized_value=normalized,
                scope=scope,
                confidence=record.confidence,
                verification_status=record.email_verification_status or "unverified" if kind == "email" else "unverified",
            ))
        elif kind == "email" and record.email_verification_status:
            existing.verification_status = record.email_verification_status
            existing.confidence = max(existing.confidence, record.email_verification_score or record.confidence)

    if record.permit_kind:
        permit = None
        if record.permit_number:
            permit = db.scalar(select(PermitLicense).where(PermitLicense.source_id == source.id, PermitLicense.external_id == record.permit_number))
        if permit is None:
            db.add(PermitLicense(
                account_id=account.id,
                location_id=location.id if location else None,
                source_id=source.id,
                kind=record.permit_kind,
                external_id=record.permit_number,
                status=record.permit_status,
                issued_on=record.permit_issued_on,
                expires_on=record.permit_expires_on,
                classifications=record.permit_classifications,
            ))

    if record.coverage_type:
        policy_hmac, policy_masked = hmac_policy_id(record.policy_identifier)
        existing = db.scalar(select(CoverageEvidence).where(
            CoverageEvidence.account_id == account.id,
            CoverageEvidence.source_id == source.id,
            CoverageEvidence.coverage_type == record.coverage_type,
            or_(CoverageEvidence.policy_hmac == policy_hmac, CoverageEvidence.policy_hmac.is_(None)),
        ))
        if existing is None:
            db.add(CoverageEvidence(
                account_id=account.id,
                source_id=source.id,
                coverage_type=record.coverage_type,
                carrier=record.carrier,
                policy_hmac=policy_hmac,
                policy_masked=policy_masked,
                effective_on=record.coverage_effective_on,
                expires_on=record.coverage_expires_on,
                coverage_as_of=record.coverage_as_of,
                confidence=record.coverage_confidence or "unknown",
            ))
            if record.coverage_expires_on:
                account.x_date = record.coverage_expires_on
                account.timing_confidence = "exact"
                account.x_date_kind = "policy_expiration"

    if record.trigger_kind:
        db.add(Trigger(
            account_id=account.id,
            source_id=source.id,
            kind=record.trigger_kind,
            occurred_on=record.trigger_date,
            label=record.trigger_label or record.trigger_kind.replace("_", " ").title(),
            risk_review_only=record.trigger_risk_review_only,
            details=record.extra,
        ))

    for item in record.services:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        normalized = normalize_name(name)
        existing = db.scalar(select(ServiceOffering).where(
            ServiceOffering.account_id == account.id, ServiceOffering.source_id == source.id,
            ServiceOffering.normalized_name == normalized,
        ))
        if not existing:
            db.add(ServiceOffering(
                account_id=account.id, source_id=source.id, name=name, normalized_name=normalized,
                category=item.get("category"), confidence=float(item.get("confidence", record.confidence)),
                verification_status="verified" if source.authority in {"official", "first_party"} else "proposed",
            ))

    for item in record.exposures:
        kind = str(item.get("kind") or "").strip()
        basis = str(item.get("basis") or "").strip()[:500]
        if not kind or not basis:
            continue
        existing = db.scalar(select(ExposureEvidence).where(
            ExposureEvidence.account_id == account.id, ExposureEvidence.source_id == source.id,
            ExposureEvidence.kind == kind, ExposureEvidence.basis == basis,
        ))
        if not existing:
            db.add(ExposureEvidence(
                account_id=account.id, source_id=source.id, kind=kind, basis=basis,
                confidence=float(item.get("confidence", record.confidence)),
                verification_status="verified" if source.authority in {"official", "first_party"} else "proposed",
            ))

    for item in record.ownership_relationships:
        subject = str(item.get("subject_name") or account.name).strip()
        relation = str(item.get("relationship_type") or "owned_by").strip()
        owner = str(item.get("object_name") or "").strip()
        if not owner:
            continue
        existing = db.scalar(select(OwnershipRelationship).where(
            OwnershipRelationship.account_id == account.id, OwnershipRelationship.source_id == source.id,
            OwnershipRelationship.subject_name == subject,
            OwnershipRelationship.relationship_type == relation,
            OwnershipRelationship.object_name == owner,
        ))
        if not existing:
            db.add(OwnershipRelationship(
                account_id=account.id, source_id=source.id, subject_name=subject,
                relationship_type=relation, object_name=owner,
                confidence=float(item.get("confidence", record.confidence)),
                verification_status="verified" if source.authority in {"official", "first_party"} else "proposed",
            ))

    for item in record.business_events:
        label = str(item.get("label") or "").strip()
        kind = str(item.get("kind") or "business_event").strip()
        if not label:
            continue
        event_date = parse_date(item.get("date"))
        exists = db.scalar(select(BusinessEvent).where(
            BusinessEvent.account_id == account.id, BusinessEvent.source_id == source.id,
            BusinessEvent.kind == kind, BusinessEvent.label == label,
            BusinessEvent.occurred_on == event_date,
        ))
        if not exists:
            db.add(BusinessEvent(
                account_id=account.id, source_id=source.id, kind=kind, label=label,
                occurred_on=event_date, details=item.get("details") or {},
                confidence=float(item.get("confidence", record.confidence)),
                verification_status="verified" if source.authority in {"official", "first_party"} else "proposed",
            ))

    assertion_payload = {
        key: value for key, value in payload.items()
        if key not in {"source_record_id", "source_url", "retrieved_at", "confidence", "evidence_excerpt", "extra"}
    }
    if source.id == "google_places_ids":
        assertion_payload = {"place_id": record.place_id}
    for field_name, value in assertion_payload.items():
        digest = content_hash(value)
        exists = db.scalar(select(FieldAssertion.id).where(
            FieldAssertion.source_id == source.id,
            FieldAssertion.source_record_id == record.source_record_id,
            FieldAssertion.field_name == field_name,
            FieldAssertion.content_hash == digest,
        ))
        if not exists:
            assertion = FieldAssertion(
                account_id=account.id,
                subject_type="account_group",
                subject_id=account.id,
                source_id=source.id,
                source_run_id=run.id if run else None,
                source_record_id=record.source_record_id,
                source_url=None if source.id == "google_places_ids" else record.source_url,
                field_name=field_name,
                value_json=value,
                authority=source.authority,
                confidence=record.confidence,
                retrieved_at=record.retrieved_at,
                parser_version="1",
                content_hash=digest,
                retention_class=source.retention_policy,
                evidence_excerpt=(record.evidence_excerpt or "")[:500] or None,
            )
            if field_name in SINGLETON_ASSERTIONS:
                conflicts = db.scalars(select(FieldAssertion).where(
                    FieldAssertion.account_id == account.id,
                    FieldAssertion.field_name == field_name,
                    FieldAssertion.content_hash != digest,
                )).all()
                if conflicts:
                    assertion.conflict = True
                    for conflict in conflicts:
                        conflict.conflict = True
            db.add(assertion)
    account.last_verified_at = utcnow()
    db.flush()
    # FK assignment does not refresh already-loaded relationship collections in the
    # same transaction. Reload every input used by qualification/scoring so results
    # reflect the just-ingested evidence rather than a stale identity-map snapshot.
    db.expire(account, [
        "locations", "people", "contacts", "permits", "coverages", "triggers", "assertions",
    ])
    score_account(db, account)
    return account, created
