from __future__ import annotations

import asyncio
from typing import AsyncIterator

import httpx

from app.config import get_settings
from app.connectors.base import Connector, ConnectorScope, RawRecord


class HunterConnector(Connector):
    source_id = "hunter"

    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        if not scope.commercial_enabled or scope.budget_cents <= 0:
            raise RuntimeError("Hunter requires commercial_enabled=true and a positive per-run budget")
        key = get_settings().hunter_api_key
        if not key:
            raise RuntimeError("HUNTER_API_KEY is not configured")
        domains = scope.parameters.get("domains", [])
        if not domains:
            raise ValueError("Hunter requires at least one explicit domain")
        configured_unit_cost = scope.parameters.get("cost_per_domain_cents")
        if len(domains) > 1 and not configured_unit_cost:
            raise ValueError("Batch Hunter runs require cost_per_domain_cents for an enforceable credit cap")
        unit_cost = int(configured_unit_cost or scope.budget_cents)
        if unit_cost <= 0:
            raise ValueError("cost_per_domain_cents must be positive")
        async with httpx.AsyncClient(timeout=30) as client:
            for index, domain in enumerate(domains):
                if self.spent_cents + unit_cost > scope.budget_cents:
                    break
                response = await client.get(
                    "https://api.hunter.io/v2/domain-search",
                    params={"domain": domain, "api_key": key, "limit": 20},
                )
                response.raise_for_status()
                self.spent_cents += unit_cost
                data = response.json().get("data", {})
                for item in data.get("emails", []):
                    email = item.get("value")
                    if not email:
                        continue
                    person_name = " ".join(p for p in [item.get("first_name"), item.get("last_name")] if p) or None
                    sources = [source.get("uri") for source in item.get("sources", []) if source.get("uri")]
                    yield RawRecord(
                        source_record_id=f"{domain}:{email}",
                        source_url=sources[0] if sources else None,
                        domain=domain,
                        website=f"https://{domain}",
                        email=email,
                        person_name=person_name,
                        person_role=item.get("position"),
                        confidence=float(item.get("confidence", 50)) / 100,
                        extra={"source_urls": sources, "verification": item.get("verification", {})},
                    )
                if index < len(domains) - 1:
                    await asyncio.sleep(1.0)
