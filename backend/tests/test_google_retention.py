import pytest

from app.connectors.base import RawRecord
from app.models import SourceSpec
from app.services.ingestion import ingest_record


def test_google_accepts_only_place_id_and_never_persists_restricted_fields(db):
    first_party = db.get(SourceSpec, "first_party_web")
    account, _ = ingest_record(db, first_party, RawRecord(
        source_record_id="site:google-test", brand_name="Google Test Group",
        website="https://google-test.example", address1="1 Main St", city="Raleigh", state="NC",
        vertical="hospitality_alcohol_events", ownership_status="likely", confidence=0.95,
    ))
    google = db.get(SourceSpec, "google_places_ids")
    ingest_record(db, google, RawRecord(
        source_record_id="places/abc123", place_id="places/abc123",
        extra={"account_id": account.id}, confidence=1,
    ))
    db.commit()
    assert account.google_place_id == "places/abc123"
    assertions = [x for x in account.assertions if x.source_id == "google_places_ids"]
    assert [x.field_name for x in assertions] == ["place_id"]
    assert assertions[0].source_url is None
    assert google.attribution == "Google"

    with pytest.raises(ValueError, match="allowlist"):
        ingest_record(db, google, RawRecord(
            source_record_id="places/bad", place_id="places/bad", brand_name="Restricted Google name",
            extra={"account_id": account.id},
        ))


def test_email_verification_updates_existing_business_contact_with_evidence(db):
    first_party = db.get(SourceSpec, "first_party_web")
    account, _ = ingest_record(db, first_party, RawRecord(
        source_record_id="site:verify", brand_name="Verification Group",
        website="https://verify.example", email="owner@verify.example",
        address1="10 Main St", city="Raleigh", state="NC",
        vertical="hospitality_alcohol_events", ownership_status="likely", confidence=0.9,
    ))
    verifier = db.get(SourceSpec, "email_verifier")
    ingest_record(db, verifier, RawRecord(
        source_record_id="verification:owner@verify.example", domain="verify.example",
        email="owner@verify.example", email_verification_status="valid",
        email_verification_score=0.97, confidence=0.97, extra={"account_id": account.id},
    ))
    db.commit()
    contact = next(item for item in account.contacts if item.kind == "email")
    assert contact.verification_status == "valid"
    assert contact.confidence == 0.97
    assert any(item.field_name == "email_verification_status" for item in account.assertions if item.source_id == "email_verifier")
