from __future__ import annotations

import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import AccountGroup
from app.services.normalization import normalize_operating_status
from app.services.scoring import score_account


def repair_overture_geography(
    states: set[str], apply: bool = False, session_factory=SessionLocal,
) -> dict[str, int | list[str]]:
    allowed = {state.upper() for state in states}
    report: dict[str, int | list[str]] = {
        "allowed_states": sorted(allowed),
        "locations_out_of_scope": 0,
        "accounts_quarantined": 0,
        "accounts_reactivated": 0,
        "accounts_preserved": 0,
        "statuses_normalized": 0,
    }
    with session_factory() as db:
        accounts = db.scalars(select(AccountGroup).options(
            selectinload(AccountGroup.locations),
            selectinload(AccountGroup.assertions),
            selectinload(AccountGroup.sales_activities),
            selectinload(AccountGroup.sales_tasks),
            selectinload(AccountGroup.people),
            selectinload(AccountGroup.contacts),
            selectinload(AccountGroup.permits),
            selectinload(AccountGroup.coverages),
            selectinload(AccountGroup.triggers),
            selectinload(AccountGroup.score_contributions),
        )).unique().all()
        for account in accounts:
            changed = False
            canonical_account_status = normalize_operating_status(account.operating_status)
            if canonical_account_status != account.operating_status:
                report["statuses_normalized"] = int(report["statuses_normalized"]) + 1
                if apply:
                    account.operating_status = canonical_account_status
                changed = True

            overture_locations = [location for location in account.locations if location.source_id == "overture_places"]
            for location in overture_locations:
                canonical_location_status = normalize_operating_status(location.operating_status)
                if canonical_location_status != location.operating_status:
                    report["statuses_normalized"] = int(report["statuses_normalized"]) + 1
                    if apply:
                        location.operating_status = canonical_location_status
                    changed = True
                desired_scope = "in_scope" if location.state in allowed else "out_of_scope"
                if location.scope_status != desired_scope:
                    if desired_scope == "out_of_scope":
                        report["locations_out_of_scope"] = int(report["locations_out_of_scope"]) + 1
                    if apply:
                        location.scope_status = desired_scope
                    changed = True

            has_in_scope_location = any(
                location.state in allowed and location.scope_status != "out_of_scope"
                for location in account.locations
            )
            has_non_overture_evidence = any(
                assertion.source_id != "overture_places" for assertion in account.assertions
            ) or any(location.source_id != "overture_places" for location in account.locations)
            protected = (
                account.review_status != "new"
                or bool(account.sales_activities)
                or bool(account.sales_tasks)
                or has_non_overture_evidence
            )
            should_quarantine = bool(overture_locations) and not has_in_scope_location and not protected
            if should_quarantine and account.data_status != "quarantined":
                report["accounts_quarantined"] = int(report["accounts_quarantined"]) + 1
                if apply:
                    account.data_status = "quarantined"
                changed = True
            elif protected and account.data_status == "quarantined":
                report["accounts_reactivated"] = int(report["accounts_reactivated"]) + 1
                report["accounts_preserved"] = int(report["accounts_preserved"]) + 1
                if apply:
                    account.data_status = "active"
                changed = True
            elif not should_quarantine and changed:
                report["accounts_preserved"] = int(report["accounts_preserved"]) + 1

            if apply and changed:
                db.flush()
                db.expire(account, ["locations", "assertions"])
                score_account(db, account)

        if apply:
            db.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or repair Overture geography and status data.")
    parser.add_argument("--states", nargs="+", default=["NC"], help="In-scope state codes")
    parser.add_argument("--apply", action="store_true", help="Apply changes; default is preview only")
    args = parser.parse_args()
    print(json.dumps(repair_overture_geography(set(args.states), apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
