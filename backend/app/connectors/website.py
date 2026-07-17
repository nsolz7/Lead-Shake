from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import deque
from typing import AsyncIterator
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser

from app.config import get_settings
from app.connectors.base import Connector, ConnectorScope, RawRecord


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
RELEVANT_PATHS = (
    "location", "about", "team", "contact", "service", "event", "cater", "career",
    "franchise", "owner", "founder", "news", "blog", "press", "sitemap",
)

BUSINESS_TYPES = {"LocalBusiness", "Restaurant", "Organization", "AutoRepair", "SportsActivityLocation", "GeneralContractor"}
EXPOSURE_TERMS = {
    "liquor_liability": ("beer", "wine", "cocktail", "spirits", "full bar"),
    "event_liability": ("catering", "private events", "banquet", "event venue"),
    "commercial_auto": ("fleet", "service trucks", "delivery vehicles", "towing"),
    "equipment": ("heavy equipment", "excavator", "crane", "equipment rental"),
    "garagekeepers": ("collision repair", "body shop", "vehicle storage"),
    "professional_liability": ("personal training", "fitness coaching", "instruction"),
    "abuse_molestation": ("childcare", "youth program", "kids camp"),
}


def _excerpt(text: str, needle: str, radius: int = 120) -> str | None:
    index = text.lower().find(needle.lower())
    if index < 0:
        return None
    return re.sub(r"\s+", " ", text[max(0, index - radius): index + len(needle) + radius]).strip()[:500]


def _flatten_json_ld(value):
    items = value if isinstance(value, list) else [value]
    flattened = []
    for item in items:
        if not isinstance(item, dict):
            continue
        flattened.append(item)
        graph = item.get("@graph")
        if isinstance(graph, list):
            flattened.extend(node for node in graph if isinstance(node, dict))
    return flattened


def _types(item: dict) -> set[str]:
    value = item.get("@type", [])
    return set(value if isinstance(value, list) else [value])


def _service_items(nodes: list[dict]) -> list[dict]:
    services: dict[str, dict] = {}
    for node in nodes:
        if "Service" in _types(node):
            name = node.get("name") or node.get("serviceType")
            if name:
                services[str(name).lower()] = {"name": str(name), "category": node.get("serviceType"), "confidence": 0.9}
        offers = node.get("makesOffer") or node.get("offers") or []
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            provided = offer.get("itemOffered") if isinstance(offer.get("itemOffered"), dict) else offer
            name = provided.get("name") or provided.get("serviceType")
            if name:
                services[str(name).lower()] = {"name": str(name), "category": provided.get("serviceType"), "confidence": 0.85}
    return list(services.values())[:50]


class WebsiteConnector(Connector):
    source_id = "first_party_web"

    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        websites = scope.parameters.get("websites", [])
        page_cache = scope.parameters.get("page_cache", {})
        settings = get_settings()
        headers = {"User-Agent": "LeadIntelligenceResearchBot/1.0 (+local analyst; respects robots.txt)"}
        async with httpx.AsyncClient(timeout=settings.website_timeout_seconds, headers=headers, follow_redirects=True) as client:
            for website in websites:
                root = website if "://" in website else f"https://{website}"
                parsed_root = urlparse(root)
                robots_url = f"{parsed_root.scheme}://{parsed_root.netloc}/robots.txt"
                robot = RobotFileParser(robots_url)
                try:
                    response = await client.get(robots_url)
                    robot.parse(response.text.splitlines() if response.status_code < 400 else [])
                except httpx.HTTPError:
                    robot.parse([])

                queue = deque([root, urljoin(root.rstrip("/") + "/", "sitemap.xml")])
                visited: set[str] = set()
                canonical_visited: set[str] = set()
                while queue and len(visited) < settings.max_website_pages:
                    url = queue.popleft()
                    if url in visited:
                        continue
                    visited.add(url)
                    if not robot.can_fetch(headers["User-Agent"], url):
                        yield RawRecord(
                            source_record_id=f"{parsed_root.netloc}:{urlparse(url).path or '/'}:robots",
                            source_url=url, website=root,
                            extra={"crawl_page": {
                                "url": url, "canonical_url": url, "robots_status": "disallowed",
                                "error": "Blocked by robots.txt",
                            }},
                        )
                        continue
                    request_headers = {}
                    cached = page_cache.get(url) or {}
                    if cached.get("etag"):
                        request_headers["If-None-Match"] = cached["etag"]
                    if cached.get("last_modified"):
                        request_headers["If-Modified-Since"] = cached["last_modified"]
                    try:
                        response = await client.get(url, headers=request_headers)
                        if response.status_code == 304:
                            yield RawRecord(
                                source_record_id=f"{parsed_root.netloc}:{urlparse(url).path or '/'}:cached",
                                source_url=url,
                                website=root,
                                extra={"crawl_page": {
                                    "url": url, "canonical_url": url, "status_code": 304,
                                    "content_type": response.headers.get("content-type"),
                                    "content_hash": cached.get("content_hash"), "etag": cached.get("etag"),
                                    "last_modified": cached.get("last_modified"), "robots_status": "allowed",
                                }},
                            )
                            continue
                        response.raise_for_status()
                    except httpx.HTTPError as exc:
                        status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                        yield RawRecord(
                            source_record_id=f"{parsed_root.netloc}:{urlparse(url).path or '/'}:error",
                            source_url=url, website=root,
                            extra={"crawl_page": {
                                "url": url, "canonical_url": url, "status_code": status_code,
                                "robots_status": "allowed", "error": str(exc)[:1000],
                            }},
                        )
                        continue
                    content_type = response.headers.get("content-type", "")
                    if "xml" in content_type or urlparse(url).path.endswith(".xml"):
                        for found in re.findall(r"<loc>\s*(https?://[^<]+)\s*</loc>", response.text, re.I):
                            parsed = urlparse(found)
                            if parsed.netloc == parsed_root.netloc and any(term in parsed.path.lower() for term in RELEVANT_PATHS):
                                queue.append(found)
                        continue
                    if "text/html" not in content_type:
                        continue
                    tree = HTMLParser(response.text)
                    text = tree.body.text(separator=" ") if tree.body else ""
                    title = tree.css_first("title").text(strip=True) if tree.css_first("title") else parsed_root.netloc
                    emails = sorted(set(EMAIL_RE.findall(text)))
                    phones = sorted(set(PHONE_RE.findall(text)))
                    franchise = "franchise" in text.lower() and any(term in text.lower() for term in ("franchise with", "franchise opportunities", "become a franchise"))
                    owner_excerpt = next((_excerpt(text, phrase) for phrase in ("family-owned", "family owned", "founded by", "our founder", "owner") if phrase in text.lower()), None)

                    json_ld_nodes: list[dict] = []
                    for node in tree.css('script[type="application/ld+json"]'):
                        try:
                            value = json.loads(node.text())
                            json_ld_nodes.extend(_flatten_json_ld(value))
                        except (json.JSONDecodeError, TypeError):
                            continue
                    businesses = [item for item in json_ld_nodes if _types(item) & BUSINESS_TYPES] or [{}]
                    people = [item for item in json_ld_nodes if isinstance(item, dict) and "Person" in _types(item) and item.get("name")]
                    services = _service_items(json_ld_nodes)
                    exposures = []
                    lowered = text.lower()
                    for kind, terms in EXPOSURE_TERMS.items():
                        matched = next((term for term in terms if term in lowered), None)
                        if matched:
                            exposures.append({"kind": kind, "basis": _excerpt(text, matched) or matched, "confidence": 0.75})
                    ownership_relationships = []
                    founder = next((item.get("founder") for item in businesses if item.get("founder")), None)
                    if isinstance(founder, dict) and founder.get("name"):
                        ownership_relationships.append({
                            "subject_name": businesses[0].get("name") or title.split("|")[0].strip(),
                            "relationship_type": "founded_by", "object_name": founder["name"], "confidence": 0.9,
                        })
                    events = []
                    for item in json_ld_nodes:
                        if _types(item) & {"Event", "NewsArticle"} and item.get("name"):
                            events.append({
                                "kind": "event" if "Event" in _types(item) else "news",
                                "label": item["name"], "date": item.get("startDate") or item.get("datePublished"),
                                "details": {"url": item.get("url")}, "confidence": 0.85,
                            })
                    source_id = f"{parsed_root.netloc}:{urlparse(url).path or '/'}"
                    final_url = str(response.url) if response.url else url
                    canonical_node = tree.css_first('link[rel="canonical"]')
                    canonical = urljoin(final_url, canonical_node.attributes.get("href", "")) if canonical_node else final_url
                    canonical_parts = urlparse(canonical)
                    canonical = canonical_parts._replace(fragment="", query="").geturl()
                    if canonical in canonical_visited:
                        continue
                    canonical_visited.add(canonical)
                    contact_form = next((
                        urljoin(url, anchor.attributes.get("href", "")) for anchor in tree.css("a[href]")
                        if "contact" in (anchor.attributes.get("href", "").lower())
                    ), None)
                    page_meta = {
                        "url": url, "canonical_url": canonical, "status_code": response.status_code,
                        "content_type": content_type, "content_hash": hashlib.sha256(response.content).hexdigest(),
                        "etag": response.headers.get("etag"), "last_modified": response.headers.get("last-modified"),
                        "robots_status": "allowed",
                    }
                    for index, business in enumerate(businesses):
                        address = business.get("address") if isinstance(business.get("address"), dict) else {}
                        yield RawRecord(
                            source_record_id=f"{source_id}:{index}",
                            source_url=url,
                            brand_name=business.get("name") or title.split("|")[0].strip(),
                            category=next(iter(_types(business)), None),
                            website=root,
                            phone=business.get("telephone") or (phones[0] if phones else None),
                            email=business.get("email") or (emails[0] if emails else None),
                            address1=address.get("streetAddress"),
                            city=address.get("addressLocality"),
                            state=address.get("addressRegion"),
                            postal_code=address.get("postalCode"),
                            person_name=people[0].get("name") if people else None,
                            person_role=people[0].get("jobTitle") if people else None,
                            contact_form_url=contact_form,
                            ownership_signal=bool(owner_excerpt),
                            ownership_status="likely" if owner_excerpt else None,
                            franchise_signal=franchise,
                            services=services,
                            exposures=exposures,
                            ownership_relationships=ownership_relationships,
                            business_events=events,
                            confidence=0.85,
                            evidence_excerpt=owner_excerpt,
                            extra={"people": [{"name": x.get("name"), "role": x.get("jobTitle"), "profile": x.get("url")} for x in people[:25]], "crawl_page": page_meta},
                        )
                    await asyncio.sleep(4.0)
                    for anchor in tree.css("a[href]"):
                        href = urljoin(url, anchor.attributes.get("href", ""))
                        parsed = urlparse(href)
                        clean = parsed._replace(fragment="", query="").geturl()
                        if parsed.netloc == parsed_root.netloc and any(term in parsed.path.lower() for term in RELEVANT_PATHS):
                            if clean not in visited:
                                queue.append(clean)
