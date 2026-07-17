import hashlib

from app.config import get_settings
from app.models import AccountGroup, SourceSpec
from app.services.tabular_import import import_tabular


def test_official_import_is_content_addressed_and_risk_flags_do_not_add_timing(db, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    content = (
        "source_record_id,establishment,address,city,state,zip,naics,inspection_date\n"
        "OSHA-1,Triangle Roofing,10 Trade St,Raleigh,NC,27601,238160,2026-06-15\n"
    ).encode()
    source = db.get(SourceSpec, "osha")
    run = import_tabular(db, source, content, "osha.csv")
    digest = hashlib.sha256(content).hexdigest()
    assert run.status == "completed"
    assert run.scope["content_hash"] == digest
    assert (tmp_path / "raw" / "osha" / f"{digest}.csv").read_bytes() == content
    account = db.query(AccountGroup).one()
    assert account.triggers[0].risk_review_only is True
    timing = next(item for item in account.score_contributions if item.factor == "business_events")
    assert timing.points == 0
