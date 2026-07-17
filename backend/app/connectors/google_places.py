from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from app.config import get_settings
from app.connectors.base import Connector, ConnectorScope, RawRecord


class GooglePlacesIdsConnector(Connector):
    source_id = "google_places_ids"

    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        key = get_settings().google_maps_api_key
        if not key:
            raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured")
        account_queries = scope.parameters.get("account_queries", [])
        query_items = account_queries or [{"query": query, "account_id": scope.parameters.get("account_id")} for query in (scope.queries or scope.parameters.get("queries", []))]
        if not query_items:
            raise ValueError("Google IDs-only discovery requires one or more explicit queries")
        async with httpx.AsyncClient(timeout=30) as client:
            for query_item in query_items:
                query = query_item["query"]
                page_token = None
                while True:
                    payload: dict = {"textQuery": query, "pageSize": 20}
                    if page_token:
                        payload["pageToken"] = page_token
                    response = await client.post(
                        "https://places.googleapis.com/v1/places:searchText",
                        json=payload,
                        headers={
                            "X-Goog-Api-Key": key,
                            "X-Goog-FieldMask": "places.id,nextPageToken",
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    for place in body.get("places", []):
                        place_id = place.get("id")
                        if place_id:
                            yield RawRecord(
                                source_record_id=place_id,
                                place_id=place_id,
                                confidence=0.5,
                                extra={"query": query, "account_id": query_item.get("account_id")},
                            )
                    page_token = body.get("nextPageToken")
                    if not page_token:
                        break
                    await asyncio.sleep(1.0)


async def live_validate_place(place_id: str) -> dict:
    """Return a transient, attributed view. Callers must never persist this payload."""
    key = get_settings().google_maps_api_key
    if not key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured")
    place_name = place_id if place_id.startswith("places/") else f"places/{place_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://places.googleapis.com/v1/{place_name}",
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "id,displayName,formattedAddress,businessStatus,googleMapsUri",
            },
        )
        response.raise_for_status()
    payload = response.json()
    return {
        "transient": True,
        "persisted": False,
        "place_id": payload.get("id"),
        "display_name": (payload.get("displayName") or {}).get("text"),
        "formatted_address": payload.get("formattedAddress"),
        "business_status": payload.get("businessStatus"),
        "google_maps_uri": payload.get("googleMapsUri"),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "attribution": {"label": "Google Maps", "required": True},
    }
