from sqlalchemy.orm import Session

from app.models import AccountGroup


INDEPENDENT_STATUSES = {"confirmed", "likely"}


def qualify_account(db: Session, account: AccountGroup) -> AccountGroup:
    active_locations = [
        location for location in account.locations
        if location.physical and location.operating_status == "active" and location.scope_status == "in_scope"
    ]
    assertion_sources = {assertion.source_id for assertion in account.assertions}
    authoritative_list = bool(active_locations) and all(location.authoritative for location in active_locations)
    independently_corroborated = (
        bool(active_locations)
        and all(location.confidence >= 0.8 for location in active_locations)
        and len(assertion_sources) >= 2
    )
    account.location_count_verified = len(active_locations) if authoritative_list or independently_corroborated else None

    reason = None
    if account.classification_status == "excluded":
        reason = "franchise" if account.classification_reason == "confirmed_franchise" else (account.classification_reason or "wrong_vertical")
    elif account.data_status != "active":
        reason = "quarantined_data"
    elif account.operating_status != "active":
        reason = "inactive_account"
    elif account.location_count_verified is None:
        reason = "location_count_unverified"
    elif account.location_count_verified < 2:
        reason = "single_location"
    elif account.location_count_verified > 5:
        reason = "more_than_five_locations"
    elif account.ownership_status not in INDEPENDENT_STATUSES:
        reason = "ownership_unconfirmed"
    elif account.franchise_signal:
        reason = "franchise"
    elif account.corporate_control_signal:
        reason = "corporate_controlled"
    elif account.pe_signal:
        reason = "private_equity_controlled"
    elif account.public_company_signal:
        reason = "public_company"
    elif account.classification_status != "target" or account.vertical == "unknown":
        reason = "outside_v1_verticals"

    account.eligible = reason is None
    account.exclusion_reason = reason
    db.add(account)
    return account
