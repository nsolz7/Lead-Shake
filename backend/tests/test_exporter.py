import json
import zipfile

from app.connectors.base import RawRecord
from app.config import get_settings
from app.models import SourceSpec, SuppressionEntry
from app.services.exporter import create_export
from app.services.ingestion import ingest_record


def test_export_pack_has_provenance_and_suppresses_personal_or_opted_out_contacts(db, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    source = db.get(SourceSpec, "first_party_web")
    account = None
    for index, address in enumerate(["10 Main Street", "20 Main Street"]):
        account, _ = ingest_record(db, source, RawRecord(
            source_record_id=f"export:{index}", source_url="https://export.example/locations",
            brand_name="Export Group", website="https://export.example", address1=address,
            city="Raleigh", state="NC", postal_code="27601", vertical="hospitality_alcohol_events",
            ownership_status="confirmed", person_name="Robin Owner" if index == 0 else None,
            person_role="Owner" if index == 0 else None, ownership_signal=index == 0,
            email="owner@export.example" if index == 0 else None,
            phone="919-555-0199" if index == 0 else None, confidence=0.98,
        ))
    account.review_status = "approved"
    db.add(SuppressionEntry(kind="email", normalized_value="owner@export.example", reason="opt_out"))
    db.commit()

    batch = create_export(db, {"tiers": [account.tier], "states": ["NC"], "review_statuses": ["approved"], "include_hold": False})
    assert batch.status == "completed" and batch.lead_count == 1
    with zipfile.ZipFile(batch.file_path) as archive:
        assert set(archive.namelist()) == {
            "leads.csv", "locations.csv", "contacts.csv", "licenses_coverage.csv",
            "triggers_exposures.csv", "evidence.csv", "exclusions.csv", "leads.xlsx", "manifest.json",
        }
        leads = archive.read("leads.csv").decode("utf-8-sig")
        contacts = archive.read("contacts.csv").decode("utf-8-sig")
        evidence = archive.read("evidence.csv").decode("utf-8-sig")
        manifest = json.loads(archive.read("manifest.json"))
    assert "Export Group" in leads
    assert "owner@export.example" not in leads and "owner@export.example" not in contacts
    assert "source_record_id" in evidence and "content_hash" in evidence
    assert manifest["score_version"] == "rules-v1"
    assert manifest["source_versions"][0]["source_id"] == "first_party_web"
    assert len(manifest["snapshot_fingerprint"]) == 64

    second_batch = create_export(db, {"tiers": [account.tier], "states": ["NC"], "review_statuses": ["approved"], "include_hold": False})
    with zipfile.ZipFile(second_batch.file_path) as archive:
        second_manifest = json.loads(archive.read("manifest.json"))
    assert second_manifest["snapshot_fingerprint"] == manifest["snapshot_fingerprint"]
