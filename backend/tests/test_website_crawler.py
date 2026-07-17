from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from app.connectors.base import ConnectorScope
from app.connectors.website import WebsiteConnector


def response(status: int, body: str = "", *, url: str, content_type: str = "text/html", headers: dict | None = None):
    return httpx.Response(
        status,
        text=body,
        headers={"content-type": content_type, **(headers or {})},
        request=httpx.Request("GET", url),
    )


@pytest.mark.asyncio
async def test_crawler_respects_robots_recurses_sitemaps_and_extracts_structured_signals(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_website_pages", 12)
    monkeypatch.setattr(settings, "website_timeout_seconds", 1.0)
    seen: list[str] = []
    root_html = """
      <html><head><title>Example Group | Home</title></head><body>
      Family-owned service trucks support private events and catering.
      <a href="/team">Team</a><a href="/private/contact">Private contact</a><a href="/news">News</a>
      <script type="application/ld+json">{"bad": </script>
      <script type="application/ld+json">{
        "@graph": [
          {"@type":"LocalBusiness","name":"Example North","telephone":"919-555-0100","address":{"streetAddress":"1 Main St","addressLocality":"Raleigh","addressRegion":"NC","postalCode":"27601"}},
          {"@type":"LocalBusiness","name":"Example South","address":{"streetAddress":"2 Main St","addressLocality":"Durham","addressRegion":"NC","postalCode":"27701"}},
          {"@type":"Person","name":"Robin Owner","jobTitle":"Owner","url":"https://example.com/team/robin"},
          {"@type":"Person","name":"Casey Ops","jobTitle":"Operations Director"},
          {"@type":"Service","name":"Commercial Roofing","serviceType":"Roofing"},
          {"@type":"Event","name":"Expansion Open House","startDate":"2026-08-01"}
        ]
      }</script></body></html>
    """
    pages = {
        "https://example.com/robots.txt": response(200, "User-agent: *\nDisallow: /private", url="https://example.com/robots.txt", content_type="text/plain"),
        # The final request URL simulates a redirect and becomes the canonical fallback.
        "https://example.com": response(200, root_html, url="https://example.com/about"),
        "https://example.com/sitemap.xml": response(200, "<urlset><url><loc>https://example.com/sitemap-locations.xml</loc></url><url><loc>https://example.com/locations</loc></url></urlset>", url="https://example.com/sitemap.xml", content_type="application/xml"),
        "https://example.com/sitemap-locations.xml": response(200, "<urlset><url><loc>https://example.com/team</loc></url></urlset>", url="https://example.com/sitemap-locations.xml", content_type="application/xml"),
        "https://example.com/team": response(200, '<html><head><title>Example Team</title><link rel="canonical" href="/team"/></head><body><script type="application/ld+json">{"@type":"Person","name":"Taylor Manager","jobTitle":"General Manager"}</script></body></html>', url="https://example.com/team"),
        "https://example.com/locations": response(200, "<html><head><title>Locations</title></head><body>Two operating locations</body></html>", url="https://example.com/locations"),
        "https://example.com/news": response(500, "failed", url="https://example.com/news"),
    }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            seen.append(url)
            return pages[url]

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.connectors.website.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("app.connectors.website.asyncio.sleep", no_sleep)
    records = [item async for item in WebsiteConnector().discover(ConnectorScope(parameters={"websites": ["https://example.com"]}))]

    root_records = [item for item in records if item.brand_name in {"Example North", "Example South"}]
    assert len(root_records) == 2
    assert {item.address1 for item in root_records} == {"1 Main St", "2 Main St"}
    assert len(root_records[0].extra["people"]) == 2
    assert any(item["name"] == "Commercial Roofing" for item in root_records[0].services)
    assert {item["kind"] for item in root_records[0].exposures} >= {"commercial_auto", "event_liability"}
    assert root_records[0].business_events[0]["label"] == "Expansion Open House"
    assert root_records[0].extra["crawl_page"]["canonical_url"] == "https://example.com/about"
    assert "https://example.com/sitemap-locations.xml" in seen and "https://example.com/team" in seen
    robots_record = next(item for item in records if item.extra.get("crawl_page", {}).get("robots_status") == "disallowed")
    assert robots_record.extra["crawl_page"]["error"] == "Blocked by robots.txt"
    error_record = next(item for item in records if item.source_url == "https://example.com/news")
    assert error_record.extra["crawl_page"]["status_code"] == 500


@pytest.mark.asyncio
async def test_crawler_uses_conditional_requests_and_retains_unchanged_hash(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_website_pages", 2)
    request_headers: dict[str, str] = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            if url.endswith("robots.txt"):
                return response(200, "User-agent: *\nAllow: /", url=url, content_type="text/plain")
            if url == "https://example.com":
                request_headers.update(kwargs.get("headers") or {})
                return response(304, url=url, headers={"etag": '"v1"'})
            return response(200, "<urlset/>", url=url, content_type="application/xml")

    monkeypatch.setattr("app.connectors.website.httpx.AsyncClient", FakeClient)
    records = [item async for item in WebsiteConnector().discover(ConnectorScope(parameters={
        "websites": ["https://example.com"],
        "page_cache": {"https://example.com": {
            "etag": '"v1"', "last_modified": "Wed, 15 Jul 2026 12:00:00 GMT", "content_hash": "retained-hash",
        }},
    }))]
    unchanged = next(item for item in records if item.extra.get("crawl_page", {}).get("status_code") == 304)
    assert request_headers["If-None-Match"] == '"v1"'
    assert request_headers["If-Modified-Since"] == "Wed, 15 Jul 2026 12:00:00 GMT"
    assert unchanged.extra["crawl_page"]["content_hash"] == "retained-hash"
