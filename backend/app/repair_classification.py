from __future__ import annotations

import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import AccountGroup
from app.services.classification import POLICY_VERSION, classify_business
from app.services.scoring import score_account


def _latest_asserted(account: AccountGroup, field: str):
    matches = [item for item in account.assertions if item.field_name == field]
    return max(matches, key=lambda item: item.retrieved_at).value_json if matches else None


def repair_classifications(apply: bool = False, session_factory=SessionLocal) -> dict:
    report: dict = {
        "policy_version": POLICY_VERSION,
        "accounts_scanned": 0,
        "accounts_targeted": 0,
        "accounts_quarantined": 0,
        "accounts_sent_to_review": 0,
        "accounts_unchanged": 0,
        "reason_counts": {},
        "samples": [],
    }
    with session_factory() as db:
        accounts = db.scalars(select(AccountGroup).options(
            selectinload(AccountGroup.assertions),
            selectinload(AccountGroup.locations),
            selectinload(AccountGroup.sales_activities),
            selectinload(AccountGroup.sales_tasks),
            selectinload(AccountGroup.people),
            selectinload(AccountGroup.contacts),
            selectinload(AccountGroup.permits),
            selectinload(AccountGroup.coverages),
            selectinload(AccountGroup.triggers),
            selectinload(AccountGroup.services),
            selectinload(AccountGroup.exposures),
            selectinload(AccountGroup.ownership_relationships),
            selectinload(AccountGroup.business_events),
            selectinload(AccountGroup.score_contributions),
        )).unique().all()
        for account in accounts:
            report["accounts_scanned"] = int(report["accounts_scanned"]) + 1
            category = _latest_asserted(account, "category")
            naics = _latest_asserted(account, "naics") or account.naics
            decision = classify_business(str(category) if category else None, account.name, str(naics) if naics else None)
            if account.franchise_signal:
                desired_status, desired_reason, confidence = "excluded", "confirmed_franchise", 0.99
            else:
                desired_status, desired_reason, confidence = decision.status, decision.reason, decision.confidence
            protected = (
                account.review_status != "new" or bool(account.sales_activities) or bool(account.sales_tasks)
                or any(assertion.source_id != "overture_places" for assertion in account.assertions)
            )
            current = (account.classification_status, account.classification_reason, account.vertical, account.data_status)
            if desired_status == "excluded" and protected:
                desired = ("review_required", f"proposed_exclusion:{desired_reason}", account.vertical, account.data_status)
                report["accounts_sent_to_review"] = int(report["accounts_sent_to_review"]) + int(current != desired)
            elif desired_status == "excluded":
                desired = ("excluded", desired_reason, "unknown", "quarantined")
                report["accounts_quarantined"] = int(report["accounts_quarantined"]) + int(current != desired)
            elif desired_status == "target":
                desired = ("target", desired_reason, decision.vertical, account.data_status)
                report["accounts_targeted"] = int(report["accounts_targeted"]) + int(current != desired)
            else:
                desired = ("review_required", desired_reason, account.vertical, account.data_status)
                report["accounts_sent_to_review"] = int(report["accounts_sent_to_review"]) + int(current != desired)
            if current == desired:
                report["accounts_unchanged"] = int(report["accounts_unchanged"]) + 1
                continue
            reason_counts = report["reason_counts"]
            reason_counts[desired[1]] = reason_counts.get(desired[1], 0) + 1
            if len(report["samples"]) < 30:
                report["samples"].append({
                    "account_id": account.id,
                    "name": account.name,
                    "asserted_category": category,
                    "current": {"status": current[0], "reason": current[1], "vertical": current[2], "data_status": current[3]},
                    "proposed": {"status": desired[0], "reason": desired[1], "vertical": desired[2], "data_status": desired[3]},
                    "protected": protected,
                })
            if apply:
                account.classification_status, account.classification_reason, account.vertical, account.data_status = desired
                account.classification_policy_version = POLICY_VERSION
                account.classification_confidence = confidence
                db.flush()
                score_account(db, account)
        if apply:
            db.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or repair versioned lead classifications.")
    parser.add_argument("--apply", action="store_true", help="Apply changes; default is preview only")
    args = parser.parse_args()
    print(json.dumps(repair_classifications(apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
