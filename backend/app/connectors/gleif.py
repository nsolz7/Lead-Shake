from __future__ import annotations

from typing import AsyncIterator

import httpx

from app.connectors.base import Connector, ConnectorScope, RawRecord


class GleifConnector(Connector):
    source_id = "gleif"

    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        async with httpx.AsyncClient(timeout=30) as client:
            for query in scope.queries[: scope.limit]:
                response = await client.get(
                    "https://api.gleif.org/api/v1/lei-records",
                    params={"filter[entity.legalName]": query, "filter[entity.legalAddress.country]": "US", "page[size]": 10},
                )
                response.raise_for_status()
                for item in (response.json().get("data") or [])[:10]:
                    attrs = item.get("attributes") or {}
                    entity = attrs.get("entity") or {}
                    legal = entity.get("legalName") or {}
                    address = entity.get("legalAddress") or {}
                    yield RawRecord(
                        source_record_id=item.get("id") or attrs.get("lei") or f"lei:{query}",
                        source_url=f"https://lei.bloomberg.com/leis/view/{item.get('id')}" if item.get("id") else "https://www.gleif.org/en/lei-data/gleif-api",
                        legal_name=legal.get("name") or query,
                        entity_external_id=attrs.get("lei") or item.get("id"),
                        entity_status=(entity.get("status") or "").lower() or None,
                        address1=" ".join(address.get("addressLines") or []) or None,
                        city=address.get("city"), state=address.get("region"), postal_code=address.get("postalCode"),
                        corporate_control_signal=bool((attrs.get("relationships") or {}).get("directParent")),
                        confidence=0.9,
                    )
