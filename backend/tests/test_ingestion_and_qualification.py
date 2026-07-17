from datetime import date

from sqlalchemy import func, select

from app.connectors.base import RawRecord
from app.models import AccountGroup, FieldAssertion, Location, SourceSpec
from app.services.ingestion import ingest_record
from app.services.scoring import score_account


def _location(record_id: str, address: str, *, domain: str = "sample.example", name: str = "Sample Group", **values):
    vertical = values.pop("vertical", "hospitality_alcohol_events")
    return RawRecord(
        source_record_id=record_id,
        brand_name=name,
        website=f"https://{domain}",
        address1=address,
        city="Raleigh",
        state="NC",
        postal_code="27601",
        vertical=vertical,
        confidence=0.95,
        **values,
    )


def test_shared_domain_branches_merge_and_reingestion_is_idempotent(db):
    source = db.get(SourceSpec, "first_party_web")
    first, created = ingest_record(db, source, _location(
        "site:1", "10 Main Street", ownership_status="confirmed",
        person_name="Avery Young", person_role="Owner", ownership_signal=True,
        email="avery@sample.example",
    ))
    second, second_created = ingest_record(db, source, _location("site:2", "20 Main Street"))
    db.commit()
    assert created is True and second_created is False
    assert first.id == second.id
    assert second.location_count_verified == 2
    assert second.eligible is True
    assert second.score == sum(item.points for item in second.score_contributions)

    before_locations = db.scalar(select(func.count(Location.id)))
    before_assertions = db.scalar(select(func.count(FieldAssertion.id)))
    ingest_record(db, source, _location("site:2", "20 Main Street"))
    db.commit()
    assert db.scalar(select(func.count(Location.id))) == before_locations
    assert db.scalar(select(func.count(FieldAssertion.id))) == before_assertions


def test_same_name_unrelated_businesses_stay_separate(db):
    source = db.get(SourceSpec, "overture_places")
    one, _ = ingest_record(db, source, _location("one", "1 North Street", domain="one.example", name="Common Name"))
    two, _ = ingest_record(db, source, RawRecord(
        source_record_id="two", brand_name="Common Name", website="https://two.example",
        address1="800 South Street", city="Richmond", state="VA", postal_code="23219",
        vertical="hospitality_alcohol_events", confidence=0.9,
    ))
    db.commit()
    assert one.id != two.id
    assert db.scalar(select(func.count(AccountGroup.id))) == 2


def test_corporate_form_is_allowed_but_franchise_and_six_locations_fail(db):
    source = db.get(SourceSpec, "first_party_web")
    corporate = None
    for i in range(2):
        corporate, _ = ingest_record(db, source, _location(
            f"corp:{i}", f"{100+i} Trade Street", domain="familycorp.example", name="Family Corporation",
            legal_name="Family Corporation, Inc.", entity_type="corporation",
            ownership_status="confirmed",
        ))
    assert corporate and corporate.eligible is True

    franchise = None
    for i in range(2):
        franchise, _ = ingest_record(db, source, _location(
            f"franchise:{i}", f"{200+i} Trade Street", domain="franchise.example", name="Local Franchise",
            ownership_status="confirmed", franchise_signal=True,
        ))
    assert franchise and franchise.eligible is False and franchise.exclusion_reason == "franchise"

    six = None
    for i in range(6):
        six, _ = ingest_record(db, source, _location(
            f"six:{i}", f"{300+i} Trade Street", domain="six.example", name="Six Site Auto",
            vertical="auto_services", ownership_status="confirmed",
        ))
    assert six and six.location_count_verified == 6
    assert six.eligible is False and six.exclusion_reason == "more_than_five_locations"


def test_open_discovery_requires_corroboration_for_location_total(db):
    overture = db.get(SourceSpec, "overture_places")
    account = None
    for i in range(2):
        account, _ = ingest_record(db, overture, _location(
            f"open:{i}", f"{400+i} Trade Street", domain="uncorroborated.example", name="Uncorroborated Group",
            ownership_status="likely",
        ))
    assert account and account.location_count_verified is None
    assert account.exclusion_reason == "location_count_unverified"

    first_party = db.get(SourceSpec, "first_party_web")
    for i in range(2):
        account, _ = ingest_record(db, first_party, _location(
            f"party:{i}", f"{400+i} Trade Street", domain="uncorroborated.example", name="Uncorroborated Group",
            ownership_status="likely",
        ))
    assert account.location_count_verified == 2
    assert account.eligible is True


def test_license_date_never_becomes_x_date_but_policy_expiration_does(db):
    source = db.get(SourceSpec, "first_party_web")
    account = None
    for i in range(2):
        account, _ = ingest_record(db, source, _location(
            f"timing:{i}", f"{500+i} Trade Street", domain="timing.example", name="Timing Group",
            ownership_status="confirmed",
        ))
    abc = db.get(SourceSpec, "nc_abc")
    ingest_record(db, abc, RawRecord(
        source_record_id="permit:1", brand_name=account.name, permit_kind="alcohol",
        permit_number="ABC-1", permit_expires_on=date(2026, 10, 1),
        confidence=1, extra={"account_id": account.id},
    ))
    assert account.x_date is None
    assert account.timing_confidence == "unknown"

    wc = db.get(SourceSpec, "nc_workers_comp")
    ingest_record(db, wc, RawRecord(
        source_record_id="wc:1", brand_name=account.name, coverage_type="workers_comp",
        policy_identifier="WC-SECRET-1234", coverage_expires_on=date(2026, 11, 1),
        coverage_confidence="exact", confidence=1, extra={"account_id": account.id},
    ))
    score_account(db, account, today=date(2026, 7, 13))
    assert account.x_date == date(2026, 11, 1)
    assert account.timing_confidence == "exact"
    assert account.coverages[0].policy_masked == "****1234"
    assert account.coverages[0].policy_hmac != "WC-SECRET-1234"
