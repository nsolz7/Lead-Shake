from __future__ import annotations

import json
from typing import AsyncIterator

import duckdb

from app.config import get_settings
from app.connectors.base import Connector, ConnectorScope, RawRecord
from app.services.classification import classify_business, is_confirmed_chain
from app.services.normalization import normalize_operating_status


STATE_BBOX = {
    "NC": (-84.33, 33.75, -75.40, 36.59),
    "SC": (-83.36, 32.03, -78.50, 35.22),
    "VA": (-83.68, 36.54, -75.16, 39.47),
}


def _json(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _primary_name(names) -> str | None:
    data = _json(names) or {}
    primary = data.get("primary") if isinstance(data, dict) else None
    if isinstance(primary, str):
        return primary
    if isinstance(primary, dict):
        return primary.get("text") or primary.get("value")
    return None


def _first(values):
    data = _json(values)
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, str) else None


class OvertureConnector(Connector):
    source_id = "overture_places"

    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        uri = scope.parameters.get("parquet_uri") or get_settings().overture_parquet_uri
        release = scope.parameters.get("release") or get_settings().overture_release
        if not uri and release:
            uri = f"s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
        if not uri:
            raise RuntimeError("Set OVERTURE_PARQUET_URI or OVERTURE_RELEASE")

        conn = duckdb.connect()
        if str(uri).startswith(("s3://", "https://", "http://")):
            conn.execute("INSTALL httpfs; LOAD httpfs")
            conn.execute("SET s3_region='us-west-2'")
        yielded = 0
        columns = """
            id, to_json(names) AS names_json, to_json(categories) AS categories_json,
            to_json(websites) AS websites_json, to_json(emails) AS emails_json,
            to_json(phones) AS phones_json, to_json(addresses) AS addresses_json,
            to_json(brand) AS brand_json, operating_status, confidence,
            (bbox.xmin + bbox.xmax) / 2 AS longitude,
            (bbox.ymin + bbox.ymax) / 2 AS latitude
        """
        requested_states = list(dict.fromkeys(state.upper() for state in scope.states))
        for state in requested_states:
            if state not in STATE_BBOX:
                self.reject("unsupported_state")
                continue
            minx, miny, maxx, maxy = STATE_BBOX[state]
            # The accepted-record query below filters geography before LIMIT. Count
            # the records excluded by that filter separately so run audit totals
            # still explain why a coarse bounding box contained other states.
            missing_state, out_of_state = conn.execute(
                """
                SELECT
                    count(*) FILTER (
                        WHERE addresses[1].region IS NULL OR trim(addresses[1].region) = ''
                    ) AS missing_state,
                    count(*) FILTER (
                        WHERE addresses[1].region IS NOT NULL
                          AND trim(addresses[1].region) <> ''
                          AND (
                            coalesce(upper(addresses[1].country), '') <> 'US'
                            OR upper(addresses[1].region) <> ?
                          )
                    ) AS out_of_state
                FROM read_parquet(?, hive_partitioning=1)
                WHERE bbox.xmax >= ? AND bbox.xmin <= ? AND bbox.ymax >= ? AND bbox.ymin <= ?
                """,
                [state, uri, minx, maxx, miny, maxy],
            ).fetchone()
            self.reject("missing_state", int(missing_state or 0))
            self.reject("out_of_state", int(out_of_state or 0))
            offset = 0
            batch_size = min(max(scope.limit * 3, 1000), 10000)
            while yielded < scope.limit:
                query = f"""
                    SELECT {columns}
                    FROM read_parquet(?, hive_partitioning=1)
                    WHERE bbox.xmax >= ? AND bbox.xmin <= ? AND bbox.ymax >= ? AND bbox.ymin <= ?
                      AND upper(addresses[1].country) = 'US'
                      AND upper(addresses[1].region) = ?
                    LIMIT ? OFFSET ?
                """
                rows = conn.execute(
                    query, [uri, minx, maxx, miny, maxy, state, batch_size, offset],
                ).fetchall()
                names = [desc[0] for desc in conn.description]
                if not rows:
                    break
                offset += len(rows)
                for raw_row in rows:
                    row = dict(zip(names, raw_row))
                    addresses = _json(row.get("addresses_json")) or []
                    address = addresses[0] if isinstance(addresses, list) and addresses else {}
                    actual_state = str(address.get("region") or "").upper()
                    country = str(address.get("country") or "").upper()
                    if not actual_state:
                        self.reject("missing_state")
                        continue
                    if country != "US" or actual_state != state:
                        self.reject("out_of_state")
                        continue
                    if not (address.get("freeform") or address.get("locality")):
                        self.reject("invalid_address")
                        continue
                    categories = _json(row.get("categories_json")) or {}
                    category = categories.get("primary") if isinstance(categories, dict) else None
                    brand_data = _json(row.get("brand_json")) or {}
                    brand_name = _primary_name(brand_data.get("names")) if isinstance(brand_data, dict) else None
                    name = brand_name or _primary_name(row.get("names_json"))
                    if not name:
                        self.reject("missing_name")
                        continue
                    classification = classify_business(category, name)
                    if classification.status == "excluded":
                        self.reject("wrong_vertical")
                        continue
                    if classification.status != "target":
                        self.reject("unknown_vertical")
                        continue
                    vertical = classification.vertical
                    if scope.verticals and vertical not in scope.verticals:
                        self.reject("outside_vertical_scope")
                        continue
                    yield RawRecord(
                        source_record_id=row["id"],
                        source_url="https://explore.overturemaps.org/",
                        brand_name=name,
                        category=category,
                        vertical=vertical,
                        website=_first(row.get("websites_json")),
                        email=_first(row.get("emails_json")),
                        phone=_first(row.get("phones_json")),
                        address1=address.get("freeform") or address.get("address_line1"),
                        city=address.get("locality"),
                        state=actual_state,
                        postal_code=address.get("postcode"),
                        latitude=row.get("latitude"),
                        longitude=row.get("longitude"),
                        operating_status=normalize_operating_status(row.get("operating_status")),
                        franchise_signal=is_confirmed_chain(brand_name or name),
                        confidence=float(row.get("confidence") or 0.6),
                        extra={"overture_release": release},
                    )
                    yielded += 1
                    if yielded >= scope.limit:
                        conn.close()
                        return
                if len(rows) < batch_size:
                    break
        conn.close()
