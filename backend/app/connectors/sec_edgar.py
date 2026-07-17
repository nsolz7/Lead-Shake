from __future__ import annotations

from typing import AsyncIterator
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.connectors.base import Connector, ConnectorScope, RawRecord


class SecEdgarConnector(Connector):
    source_id = "sec_edgar"

    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        user_agent = get_settings().sec_user_agent
        if not user_agent:
            raise ValueError("SEC_USER_AGENT is not configured (use a descriptive name and email)")
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": user_agent}) as client:
            for query in scope.queries[: scope.limit]:
                response = await client.get(
                    f"https://efts.sec.gov/LATEST/search-index?q={quote(query)}&forms=10-K,10-Q,8-K&from=0&size=10"
                )
                response.raise_for_status()
                for hit in ((response.json().get("hits") or {}).get("hits") or [])[:10]:
                    source = hit.get("_source") or {}
                    names = source.get("display_names") or source.get("entity_name") or [query]
                    name = names[0] if isinstance(names, list) else names
                    cik = str(source.get("ciks", [""])[0] if isinstance(source.get("ciks"), list) else source.get("cik") or "")
                    yield RawRecord(
                        source_record_id=f"cik:{cik or hit.get('_id')}",
                        source_url=f"https://www.sec.gov/edgar/browse/?CIK={cik}" if cik else "https://www.sec.gov/edgar/search/",
                        legal_name=name,
                        entity_external_id=cik or None,
                        public_company_signal=True,
                        corporate_control_signal=True,
                        confidence=0.9,
                    )
