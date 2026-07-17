from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date, datetime
from urllib.parse import urlparse

import phonenumbers
import tldextract

from app.config import get_settings


LEGAL_SUFFIXES = {
    "llc", "l l c", "inc", "incorporated", "corp", "corporation", "company", "co",
    "ltd", "limited", "lp", "llp", "pllc", "pc", "the",
}


def normalize_operating_status(value: str | None) -> str:
    normalized = (value or "active").strip().lower().replace(" ", "_")
    if normalized in {"open", "operating", "active"}:
        return "active"
    if normalized in {"closed", "permanently_closed", "inactive", "dissolved"}:
        return "inactive"
    return normalized


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    tokens = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().lower()
    if "@" in candidate and "://" not in candidate:
        candidate = candidate.rsplit("@", 1)[-1]
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    extracted = tldextract.extract(host)
    return extracted.top_domain_under_public_suffix or host or None


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    try:
        number = phonenumbers.parse(value, "US")
        if phonenumbers.is_possible_number(number):
            return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    digits = re.sub(r"\D", "", value)
    return f"+1{digits}" if len(digits) == 10 else (f"+{digits}" if digits else None)


def normalize_email(value: str | None) -> str | None:
    return value.strip().lower() if value and "@" in value else None


def normalize_address(
    address1: str | None,
    city: str | None,
    state: str | None,
    postal_code: str | None,
) -> str:
    parts = [address1 or "", city or "", (state or "").upper(), (postal_code or "")[:5]]
    return "|".join(re.sub(r"[^a-z0-9]", "", part.lower()) for part in parts)


def content_hash(value: object) -> str:
    import json
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hmac_policy_id(policy_id: str | None) -> tuple[str | None, str | None]:
    if not policy_id:
        return None, None
    normalized = re.sub(r"\s+", "", policy_id.upper())
    digest = hmac.new(
        get_settings().policy_hmac_secret.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    visible = normalized[-4:] if len(normalized) >= 4 else normalized
    return digest, f"****{visible}"


def parse_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def classify_vertical(*values: str | None) -> str:
    from app.services.classification import classify_business

    category = values[0] if values else None
    name = " ".join(value for value in values[1:] if value) if len(values) > 1 else None
    return classify_business(category, name).vertical
