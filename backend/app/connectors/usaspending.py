from __future__ import annotations

from typing import AsyncIterator

import httpx

from app.connectors.base import Connector, ConnectorScope, RawRecord


class UsaSpendingConnector(Connector):
    source_id = "usaspending"

    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        async with httpx.AsyncClient(timeout=30) as client:
            for query in scope.queries[: scope.limit]:
                response = await client.post(
                    "https://api.usaspending.gov/api/v2/autocomplete/recipient/",
                    json={"search_text": query, "limit": 10},
                )
                response.raise_for_status()
                results = response.json().get("results") or response.json().get("recipients") or []
                for item in results[:10]:
                    name = item.get("recipient_name") or item.get("name") or query
                    recipient_id = str(item.get("recipient_id") or item.get("id") or name)
                    yield RawRecord(
                        source_record_id=f"recipient:{recipient_id}",
                        source_url="https://www.usaspending.gov/recipient",
                        legal_name=name,
                        entity_external_id=item.get("uei") or item.get("duns"),
                        business_events=[{
                            "kind": "federal_award_recipient",
                            "label": "Matched USAspending federal award recipient",
                            "date": None,
                            "details": {"recipient_id": recipient_id},
                            "confidence": 0.75,
                        }],
                        confidence=0.75,
                    )
