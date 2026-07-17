from __future__ import annotations

from typing import AsyncIterator

import httpx

from app.config import get_settings
from app.connectors.base import Connector, ConnectorScope, RawRecord


class SamGovConnector(Connector):
    source_id = "sam_gov"

    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        key = get_settings().sam_gov_api_key
        if not key:
            raise ValueError("SAM_GOV_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=30) as client:
            for query in scope.queries[: scope.limit]:
                response = await client.get(
                    "https://api.sam.gov/entity-information/v3/entities",
                    params={"api_key": key, "legalBusinessName": query, "registrationStatus": "A"},
                )
                response.raise_for_status()
                for item in (response.json().get("entityData") or [])[:10]:
                    registration = item.get("entityRegistration") or {}
                    core = item.get("coreData") or {}
                    address = (core.get("physicalAddress") or registration.get("physicalAddress") or {})
                    state = address.get("stateOrProvinceCode") or address.get("state")
                    if scope.states and state and state.upper() not in {x.upper() for x in scope.states}:
                        continue
                    yield RawRecord(
                        source_record_id=registration.get("ueiSAM") or registration.get("cageCode") or f"sam:{query}",
                        source_url="https://sam.gov/content/entity-information",
                        legal_name=registration.get("legalBusinessName") or query,
                        entity_external_id=registration.get("ueiSAM"),
                        entity_status=registration.get("registrationStatus"),
                        address1=address.get("addressLine1"), city=address.get("city"), state=state,
                        postal_code=address.get("zipCode"),
                        naics=str(((core.get("businessTypes") or {}).get("primaryNaics") or "")) or None,
                        confidence=0.9,
                        extra={"uei": registration.get("ueiSAM"), "cage_code": registration.get("cageCode")},
                    )
