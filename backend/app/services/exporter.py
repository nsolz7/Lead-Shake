from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import AccountGroup, ContactPoint, ExportBatch, SourceRun, SourceSpec, SuppressionEntry
from app.services.normalization import normalize_domain, normalize_email, normalize_phone
from app.services.scoring import infer_exposure_kinds


SHEETS = ["leads", "locations", "contacts", "licenses_coverage", "triggers_exposures", "evidence", "exclusions"]


def _serialize(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _suppressed(db: Session, account: AccountGroup, kind: str, value: str) -> bool:
    normalized = value
    if kind == "email":
        normalized = normalize_email(value)
    elif kind == "phone":
        normalized = normalize_phone(value)
    elif kind == "domain":
        normalized = normalize_domain(value)
    return bool(db.scalar(select(SuppressionEntry.id).where(
        SuppressionEntry.kind == kind,
        SuppressionEntry.normalized_value == normalized,
    ))) or bool(db.scalar(select(SuppressionEntry.id).where(
        SuppressionEntry.kind == "account",
        SuppressionEntry.normalized_value == account.id,
    )))


def build_rows(db: Session, accounts: Iterable[AccountGroup]) -> dict[str, list[dict]]:
    rows = {sheet: [] for sheet in SHEETS}
    for account in sorted(accounts, key=lambda item: (-item.score, item.name.lower(), item.id)):
        valid_locations = [location for location in account.locations if location.scope_status == "in_scope"]
        states = sorted({location.state for location in valid_locations if location.state})
        owner = next((person for person in account.people if person.ownership_signal), account.people[0] if account.people else None)
        primary_location = next((location for location in valid_locations if location.authoritative), valid_locations[0] if valid_locations else None)
        business_contacts = [
            contact for contact in account.contacts
            if not contact.suppressed and contact.scope in {"business", "professional"} and not _suppressed(db, account, contact.kind, contact.value)
        ]
        coverage = max(account.coverages, key=lambda item: (item.expires_on is not None, item.expires_on or datetime.min.date())) if account.coverages else None
        source_urls = sorted({a.source_url for a in account.assertions if a.source_url})
        exposure_kinds = infer_exposure_kinds(account)
        authoritative_assertions = [a for a in account.assertions if a.authority in {"official", "first_party"}]
        conflicts = [a for a in account.assertions if a.conflict]
        evidence_completeness = (
            (25 if account.location_count_verified else 0)
            + (20 if account.ownership_status in {"confirmed", "likely"} else 0)
            + (15 if owner else 0)
            + (15 if business_contacts else 0)
            + (15 if authoritative_assertions else 0)
            + (10 if account.assertions and not conflicts else 0)
        )
        base = {
            "lead_id": account.id,
            "rank_score": account.score,
            "tier": account.tier,
            "review_status": account.review_status,
            "brand_name": account.name,
            "legal_names": [entity.legal_name for entity in account.legal_entities],
            "vertical": account.vertical,
            "naics": account.naics,
            "verified_location_count": account.location_count_verified,
            "states": states,
            "ownership_status": account.ownership_status,
            "ownership_confidence": 1.0 if account.ownership_status == "confirmed" else (0.7 if account.ownership_status == "likely" else 0.0),
            "decision_maker": owner.name if owner else None,
            "decision_maker_role": owner.role if owner else None,
            "website": account.website,
            "domain": account.domain,
            "hq_address": primary_location.address1 if primary_location else None,
            "hq_city": primary_location.city if primary_location else None,
            "hq_state": primary_location.state if primary_location else None,
            "hq_postal_code": primary_location.postal_code if primary_location else None,
            "hq_confidence": "inferred_primary_location" if primary_location else "unknown",
            "business_email": next((c.value for c in business_contacts if c.kind == "email"), None),
            "business_phone": next((c.value for c in business_contacts if c.kind == "phone"), None),
            "contact_form": next((c.value for c in business_contacts if c.kind == "contact_form"), None),
            "carrier": coverage.carrier if coverage else None,
            "policy_masked": coverage.policy_masked if coverage else None,
            "coverage_effective_on": coverage.effective_on if coverage else None,
            "coverage_expires_on": coverage.expires_on if coverage else None,
            "permit_license_signals": sorted({permit.kind for permit in account.permits}),
            "coverage_opportunity_signals": sorted(exposure_kinds),
            "exposure_trigger_signals": sorted({trigger.kind for trigger in account.triggers if not trigger.risk_review_only}),
            "risk_review_flags": sorted({trigger.kind for trigger in account.triggers if trigger.risk_review_only}),
            "timing_date": account.x_date,
            "timing_confidence": account.timing_confidence,
            "timing_kind": account.x_date_kind,
            "best_pitch_angle": account.best_pitch_angle,
            "next_action_date": account.next_action_date,
            "evidence_count": len(account.assertions),
            "evidence_completeness": evidence_completeness,
            "evidence_conflict_count": len(conflicts),
            "source_urls": source_urls,
            "last_verified_at": account.last_verified_at,
            "exclusion_reason": account.exclusion_reason,
        }
        if account.eligible:
            rows["leads"].append(base)
        else:
            rows["exclusions"].append(base)
        for location in valid_locations:
            rows["locations"].append({
                "lead_id": account.id, "brand": location.name, "address1": location.address1,
                "city": location.city, "state": location.state, "postal_code": location.postal_code,
                "county": location.county, "latitude": location.latitude, "longitude": location.longitude,
                "status": location.operating_status, "physical": location.physical,
                "authoritative": location.authoritative, "confidence": location.confidence,
            })
        for contact in business_contacts:
            rows["contacts"].append({
                "lead_id": account.id, "kind": contact.kind, "value": contact.value,
                "scope": contact.scope, "verification_status": contact.verification_status,
                "confidence": contact.confidence, "person": contact.person.name if contact.person else None,
                "role": contact.person.role if contact.person else None,
            })
        for permit in account.permits:
            rows["licenses_coverage"].append({
                "lead_id": account.id, "record_type": "permit_license", "kind": permit.kind,
                "identifier": permit.external_id, "status": permit.status,
                "issued_on": permit.issued_on, "expires_on": permit.expires_on,
                "carrier": None, "classifications": permit.classifications,
            })
        for item in account.coverages:
            rows["licenses_coverage"].append({
                "lead_id": account.id, "record_type": "coverage", "kind": item.coverage_type,
                "identifier": item.policy_masked, "status": item.confidence,
                "issued_on": item.effective_on, "expires_on": item.expires_on,
                "carrier": item.carrier, "classifications": [],
            })
        for trigger in account.triggers:
            rows["triggers_exposures"].append({
                "lead_id": account.id, "record_type": "trigger", "kind": trigger.kind, "date": trigger.occurred_on,
                "label": trigger.label, "severity": trigger.severity,
                "risk_review_only": trigger.risk_review_only, "details": trigger.details,
            })
        for exposure in sorted(exposure_kinds):
            rows["triggers_exposures"].append({
                "lead_id": account.id, "record_type": "derived_exposure", "kind": exposure,
                "date": None, "label": exposure.replace("_", " ").title(), "severity": "info",
                "risk_review_only": False, "details": {"basis": "rules-v2"},
            })
        for assertion in account.assertions:
            rows["evidence"].append({
                "lead_id": account.id, "subject_type": assertion.subject_type,
                "source_id": assertion.source_id, "source_record_id": assertion.source_record_id,
                "source_url": assertion.source_url, "field": assertion.field_name,
                "value": assertion.value_json, "authority": assertion.authority,
                "confidence": assertion.confidence, "retrieved_at": assertion.retrieved_at,
                "content_hash": assertion.content_hash, "conflict": assertion.conflict,
                "excerpt": assertion.evidence_excerpt,
            })
    return rows


def _csv_bytes(rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    if not rows:
        return b""
    fields = list(rows[0].keys())
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _serialize(value) for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")


def create_export(db: Session, filters: dict) -> ExportBatch:
    batch = ExportBatch(status="running", filters=filters)
    db.add(batch)
    db.flush()
    query = select(AccountGroup).options(
        selectinload(AccountGroup.locations), selectinload(AccountGroup.legal_entities),
        selectinload(AccountGroup.people), selectinload(AccountGroup.contacts).selectinload(ContactPoint.person),
        selectinload(AccountGroup.permits), selectinload(AccountGroup.coverages),
        selectinload(AccountGroup.triggers), selectinload(AccountGroup.assertions),
        selectinload(AccountGroup.score_contributions),
    )
    query = query.where(AccountGroup.data_status == "active")
    tiers = filters.get("tiers", ["A", "B", "C"])
    if not filters.get("include_hold"):
        query = query.where(AccountGroup.tier.in_(tiers))
    review_statuses = filters.get("review_statuses", ["approved"])
    if review_statuses:
        query = query.where(AccountGroup.review_status.in_(review_statuses))
    accounts = db.scalars(query).unique().all()
    states = set(filters.get("states", []))
    if states:
        accounts = [account for account in accounts if any(location.state in states and location.scope_status == "in_scope" for location in account.locations)]
    rows = build_rows(db, accounts)

    used_source_ids = sorted({assertion.source_id for account in accounts for assertion in account.assertions})
    sources = db.scalars(select(SourceSpec).where(SourceSpec.id.in_(used_source_ids))).all() if used_source_ids else []
    used_run_ids = sorted({assertion.source_run_id for account in accounts for assertion in account.assertions if assertion.source_run_id})
    runs = db.scalars(select(SourceRun).where(SourceRun.id.in_(used_run_ids))).all() if used_run_ids else []
    source_versions = [{
        "source_id": source.id,
        "terms_reviewed_at": _serialize(source.terms_reviewed_at),
        "last_success_at": _serialize(source.last_success_at),
        "retention_policy": source.retention_policy,
    } for source in sorted(sources, key=lambda item: item.id)]
    source_runs = [{
        "run_id": run.id,
        "source_id": run.source_id,
        "status": run.status,
        "scope": {key: value for key, value in run.scope.items() if key != "snapshot_path"},
        "finished_at": _serialize(run.finished_at),
    } for run in sorted(runs, key=lambda item: item.id)]

    fingerprint_payload = json.dumps({sheet: [{k: _serialize(v) for k, v in row.items()} for row in values] for sheet, values in rows.items()}, sort_keys=True)
    fingerprint = hashlib.sha256(fingerprint_payload.encode()).hexdigest()
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": "1",
        "score_version": "rules-v1",
        "generated_at": generated_at,
        "filters": filters,
        "lead_count": len(rows["leads"]),
        "snapshot_fingerprint": fingerprint,
        "source_versions": source_versions,
        "source_runs": source_runs,
        "files": [f"{sheet}.csv" for sheet in SHEETS] + ["leads.xlsx"],
    }

    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in SHEETS:
        sheet = workbook.create_sheet(title=sheet_name[:31])
        sheet_rows = rows[sheet_name]
        if sheet_rows:
            fields = list(sheet_rows[0].keys())
            sheet.append(fields)
            for row in sheet_rows:
                sheet.append([_serialize(row.get(field)) for field in fields])
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
    workbook.properties.creator = "Lead Intelligence Workbench"
    workbook.properties.created = datetime(2000, 1, 1)
    workbook.properties.modified = datetime(2000, 1, 1)
    workbook_buffer = io.BytesIO()
    workbook.save(workbook_buffer)

    export_dir = get_settings().data_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"lead-evidence-{batch.id}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for sheet_name in SHEETS:
            archive.writestr(f"{sheet_name}.csv", _csv_bytes(rows[sheet_name]))
        archive.writestr("leads.xlsx", workbook_buffer.getvalue())
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    batch.status = "completed"
    batch.file_path = str(path)
    batch.lead_count = len(rows["leads"])
    batch.manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    db.commit()
    return batch
