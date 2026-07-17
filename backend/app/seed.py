from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.connectors.base import RawRecord
from app.database import Base, SessionLocal, engine
from app.models import AccountGroup, SourceRun, SourceSpec, utcnow
from app.services.ingestion import ingest_record
from app.services.scoring import score_account
from app.source_catalog import seed_source_catalog


DEMO_MARKER = "synthetic-three-state-v1"


def _location(
    source_record_id: str,
    name: str,
    website: str,
    address: str,
    city: str,
    state: str,
    postal_code: str,
    vertical: str,
    **extra,
) -> RawRecord:
    return RawRecord(
        source_record_id=source_record_id,
        source_url=f"{website}/locations",
        brand_name=name,
        website=website,
        address1=address,
        city=city,
        state=state,
        postal_code=postal_code,
        vertical=vertical,
        confidence=0.98,
        **extra,
    )


def seed_demo() -> int:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_source_catalog(db)
        existing = next((item for item in db.scalars(select(SourceRun)).all() if item.scope.get("seed_marker") == DEMO_MARKER), None)
        if existing:
            return 0

        first_party = db.get_one(SourceSpec, "first_party_web")
        run = SourceRun(
            source_id=first_party.id,
            status="running",
            started_at=utcnow(),
            scope={"seed_marker": DEMO_MARKER, "synthetic": True, "states": ["NC", "SC", "VA"]},
        )
        db.add(run)
        db.flush()
        accounts: list[AccountGroup] = []

        nc_records = [
            _location(
                "demo:nc:oak-ember:1", "Oak & Ember Hospitality", "https://oakember.example",
                "301 Glenwood Avenue", "Raleigh", "NC", "27603", "hospitality_alcohol_events",
                legal_name="Oak & Ember Hospitality, LLC", entity_type="LLC", entity_status="active",
                entity_external_id="DEMO-NC-1001", ownership_status="confirmed",
                person_name="Amelia Carter", person_role="Founder and Managing Member", ownership_signal=True,
                email="amelia@oakember.example", phone="919-555-0142",
                evidence_excerpt="Founded and independently operated by Amelia Carter.",
            ),
            _location("demo:nc:oak-ember:2", "Oak & Ember Hospitality", "https://oakember.example", "2100 Hillsborough Street", "Raleigh", "NC", "27607", "hospitality_alcohol_events", phone="919-555-0143"),
            _location("demo:nc:oak-ember:3", "Oak & Ember Hospitality", "https://oakember.example", "118 East Main Street", "Durham", "NC", "27701", "hospitality_alcohol_events", phone="984-555-0108"),
        ]
        nc_account = None
        for record in nc_records:
            nc_account, _ = ingest_record(db, first_party, record, run)
        assert nc_account
        accounts.append(nc_account)
        nc_abc = db.get_one(type(first_party), "nc_abc")
        ingest_record(db, nc_abc, RawRecord(
            source_record_id="demo:ncabc:44120", source_url=nc_abc.base_url,
            brand_name=nc_account.name, permit_kind="alcohol_on_premises", permit_number="DEMO-ABC-44120",
            permit_status="active", permit_issued_on=date(2025, 11, 1), permit_expires_on=date(2026, 10, 31),
            confidence=1.0, extra={"account_id": nc_account.id},
        ), run)
        nc_wc = db.get_one(type(first_party), "nc_workers_comp")
        ingest_record(db, nc_wc, RawRecord(
            source_record_id="demo:ncwc:oak-2026", source_url=nc_wc.base_url,
            brand_name=nc_account.name, coverage_type="workers_comp", carrier="Carolina Mutual Insurance",
            policy_identifier="WC-DEMO-9843321", coverage_effective_on=date(2025, 10, 15),
            coverage_expires_on=date(2026, 10, 15), coverage_as_of=date(2026, 7, 10),
            coverage_confidence="exact", confidence=1.0, extra={"account_id": nc_account.id},
            evidence_excerpt="Synthetic fixture: portal returned an active policy period.",
        ), run)
        ingest_record(db, first_party, RawRecord(
            source_record_id="demo:nc:oak-trigger", brand_name=nc_account.name,
            trigger_kind="new_location", trigger_date=date(2026, 4, 18),
            trigger_label="Durham location opened", confidence=0.95,
            extra={"account_id": nc_account.id},
        ), run)

        sc_records = [
            _location(
                "demo:sc:piedmont:1", "Piedmont Mechanical Group", "https://piedmontmechanical.example",
                "7400 Rivers Avenue", "North Charleston", "SC", "29406", "contractors_trades",
                legal_name="Piedmont Mechanical Group, Inc.", entity_type="corporation", entity_status="active",
                entity_external_id="DEMO-SC-2201", ownership_status="likely",
                person_name="Marcus Reed", person_role="President", ownership_signal=True,
                email="mreed@piedmontmechanical.example", phone="843-555-0160",
                evidence_excerpt="Locally owned by the Reed family since 1998.",
            ),
            _location("demo:sc:piedmont:2", "Piedmont Mechanical Group", "https://piedmontmechanical.example", "1220 Two Notch Road", "Lexington", "SC", "29073", "contractors_trades", phone="803-555-0179"),
        ]
        sc_account = None
        for record in sc_records:
            sc_account, _ = ingest_record(db, first_party, record, run)
        assert sc_account
        accounts.append(sc_account)
        sc_llr = db.get_one(type(first_party), "sc_llr")
        ingest_record(db, sc_llr, RawRecord(
            source_record_id="demo:scllr:M-88022", source_url=sc_llr.base_url,
            brand_name=sc_account.name, permit_kind="mechanical_contractor", permit_number="M-DEMO-88022",
            permit_status="active", permit_expires_on=date(2027, 1, 31), permit_classifications=["HVAC", "plumbing"],
            confidence=1.0, extra={"account_id": sc_account.id},
        ), run)
        fmcsa = db.get_one(type(first_party), "fmcsa")
        ingest_record(db, fmcsa, RawRecord(
            source_record_id="demo:fmcsa:1881022", source_url=fmcsa.base_url,
            brand_name=sc_account.name, trigger_kind="fleet", trigger_date=date(2026, 6, 20),
            trigger_label="FMCSA census reports 12 power units", confidence=1.0,
            extra={"account_id": sc_account.id, "power_units": 12, "drivers": 14},
        ), run)

        va_records = [
            _location(
                "demo:va:blue-ridge:1", "Blue Ridge Movement Club", "https://blueridgemovement.example",
                "11 Campbell Avenue SE", "Roanoke", "VA", "24011", "fitness_recreation",
                legal_name="Blue Ridge Movement Club, LLC", entity_type="LLC", entity_status="active",
                entity_external_id="DEMO-VA-3301", ownership_status="confirmed",
                person_name="Jordan Ellis", person_role="Owner", ownership_signal=True,
                email="jordan@blueridgemovement.example", phone="540-555-0180",
                evidence_excerpt="Owner-operated regional fitness and recreation club.",
            ),
            _location("demo:va:blue-ridge:2", "Blue Ridge Movement Club", "https://blueridgemovement.example", "3901 Old Forest Road", "Lynchburg", "VA", "24501", "fitness_recreation", phone="434-555-0181"),
            _location("demo:va:blue-ridge:3", "Blue Ridge Movement Club", "https://blueridgemovement.example", "1440 South Main Street", "Blacksburg", "VA", "24060", "fitness_recreation", phone="540-555-0182"),
            _location("demo:va:blue-ridge:4", "Blue Ridge Movement Club", "https://blueridgemovement.example", "201 East Market Street", "Harrisonburg", "VA", "22801", "fitness_recreation", phone="540-555-0183"),
        ]
        va_account = None
        for record in va_records:
            va_account, _ = ingest_record(db, first_party, record, run)
        assert va_account
        accounts.append(va_account)

        franchise_account = None
        for index, (city, address, postal) in enumerate([
            ("Cary", "1010 Kildaire Farm Road", "27511"),
            ("Apex", "800 West Williams Street", "27502"),
            ("Raleigh", "6201 Capital Boulevard", "27616"),
        ], start=1):
            franchise_account, _ = ingest_record(db, first_party, _location(
                f"demo:excluded:franchise:{index}", "MetroFit Triangle", "https://metrofit-triangle.example",
                address, city, "NC", postal, "fitness_recreation",
                ownership_status="likely", franchise_signal=True,
            ), run)
        assert franchise_account
        accounts.append(franchise_account)

        six_account = None
        for index in range(1, 7):
            six_account, _ = ingest_record(db, first_party, _location(
                f"demo:excluded:six:{index}", "Commonwealth Auto Care", "https://commonwealthautocare.example",
                f"{100 + index} Commerce Drive", "Richmond", "VA", f"2322{index}", "auto_services",
                ownership_status="confirmed",
            ), run)
        assert six_account
        accounts.append(six_account)

        for account in accounts:
            score_account(db, account, today=date(2026, 7, 13))
            if account.eligible:
                account.review_status = "approved"
        run.records_seen = 3 + 3 + 2 + 2 + 4 + 3 + 6
        run.records_created = len(accounts)
        run.records_updated = run.records_seen - run.records_created
        run.status = "completed"
        run.finished_at = utcnow()
        db.commit()
        return len(accounts)


def main() -> None:
    count = seed_demo()
    print(f"Seeded {count} synthetic account groups." if count else "Synthetic seed already present.")


if __name__ == "__main__":
    main()
