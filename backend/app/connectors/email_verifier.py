from __future__ import annotations

import asyncio
from typing import AsyncIterator

import httpx

from app.config import get_settings
from app.connectors.base import Connector, ConnectorScope, RawRecord
from app.services.normalization import normalize_domain, normalize_email


class EmailVerificationConnector(Connector):
    source_id = "email_verifier"

    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        if not scope.commercial_enabled or scope.budget_cents <= 0:
            raise RuntimeError("Email verification requires explicit commercial opt-in and a positive budget")
        settings = get_settings()
        key = settings.email_verification_api_key or settings.hunter_api_key
        if not key:
            raise RuntimeError("EMAIL_VERIFICATION_API_KEY or HUNTER_API_KEY is not configured")
        emails = [normalize_email(value) for value in scope.parameters.get("emails", [])]
        emails = [value for value in emails if value]
        if not emails:
            raise ValueError("Email verification requires one or more professional/business emails")
        configured_unit_cost = scope.parameters.get("cost_per_email_cents")
        if len(emails) > 1 and not configured_unit_cost:
            raise ValueError("Batch verification requires cost_per_email_cents for an enforceable ceiling")
        unit_cost = int(configured_unit_cost or scope.budget_cents)
        if unit_cost <= 0:
            raise ValueError("cost_per_email_cents must be positive")

        async with httpx.AsyncClient(timeout=30) as client:
            for index, email in enumerate(emails):
                if self.spent_cents + unit_cost > scope.budget_cents:
                    break
                response = await client.get(
                    "https://api.hunter.io/v2/email-verifier",
                    params={"email": email, "api_key": key},
                )
                response.raise_for_status()
                self.spent_cents += unit_cost
                data = response.json().get("data", {})
                score = float(data.get("score") or 0) / 100
                yield RawRecord(
                    source_record_id=f"verification:{email}",
                    source_url="https://hunter.io/email-verifier",
                    domain=normalize_domain(email),
                    email=email,
                    email_verification_status=data.get("status") or "unknown",
                    email_verification_score=score,
                    confidence=score,
                    extra={"account_id": scope.parameters.get("account_id")},
                )
                if index < len(emails) - 1:
                    await asyncio.sleep(1.0)
