# Source acquisition runbook

The database catalog is the automation allowlist. A connector runs only when it is enabled, automation is allowed, and `policy_status=approved`. Manual sources never become automated merely because a URL is known. Bootstrap updates catalog metadata but never fabricates a terms-review date.

| Source class | Acquisition | Default storage boundary |
|---|---|---|
| Overture Places | DuckDB query over monthly GeoParquet | Open licensed fields, provenance, release |
| First-party sites | Robots-compliant, low-rate crawl | Assertions, hashes, short excerpts, public work contacts |
| Google Places | IDs-only search; user-confirmed live validation | Place ID and internal validation timestamp only; live fields are transient |
| Hunter | Commercial API, explicit opt-in and budget | Professional contacts and provider source URLs only |
| Official bulk files | Human-acquired CSV/XLSX upload | Content-addressed raw snapshot plus parsed assertions |
| Manual government portals | Human lookup | Short assertion, record ID/URL, retrieval time; policy ID HMAC only |
| OSM regional extracts | Downloaded PBF/converted tabular snapshot | Source-segregated ODbL records and attribution |
| Common Crawl | Downloaded/local URL index | Candidate-domain and crawl metadata only |
| SAM.gov | Free-key API/export | Official entity identity and public business fields |
| USAspending, SEC, GLEIF | Free APIs or bulk snapshots | Identity, awards, and corporate-control evidence |
| NC WARN | Official report/import | Risk-review business events |

## Overture

Set either `OVERTURE_RELEASE` or `OVERTURE_PARQUET_URI`. A local Parquet URI is best for repeatable audits. The connector filters with NC/SC/VA bounding boxes, retains the Overture record ID/release, and never treats Overture alone as authoritative location-count verification. A first-party authoritative list or a second source is required.

## Official files

Acquire the file through the agency's documented download, subscription, list-request, API, or FOIA process. Choose its catalog entry in **Runs & imports** and upload CSV or XLSX. Common headings map automatically; an API caller may pass `mapping_json` for source-specific headings.

The importer records the original filename and SHA-256 digest and stores the exact bytes at `DATA_DIR/raw/{source_id}/{hash}.{ext}`. Reimporting the same snapshot is assertion-idempotent.

North Carolina SOS data must come from its subscription service. Never point a browser automation tool at the interactive entity search. SC SOS/SCDOR/food-grade and state workers' compensation interfaces remain manual until bulk permission is documented. Virginia ABC/DPOR and acquired VDH files use the tabular path.

## Manual coverage lookup

From a lead, research the exact legal employer name in the appropriate state portal. Enter only what the portal actually returns:

- carrier;
- coverage-as-of, effective, or expiration date;
- masked/HMAC policy identifier;
- source record identifier and URL;
- short evidence excerpt and confidence.

An absent result is not evidence of no coverage. A license expiration, entity formation date, or website anniversary is never entered as an insurance X-date.

## Commercial cost control

Commercial connectors require `commercial_enabled=true` and `budget_cents > 0` on every run. Hunter batch runs additionally require an estimated `cost_per_domain_cents`; the connector stops before the ceiling. Reconcile estimated spend against the provider dashboard.

OpenAI analysis is not part of a free research run. The AI endpoint preflights a versioned model/tool rate card, caps output and built-in tool calls, stores returned usage, and calculates token plus web-search cost in micro-USD. The authorized ceiling and calculated usage are displayed separately. ChatGPT subscriptions and API billing are separate.

Google result pages are not scraped. OSM production acquisition uses downloaded extracts rather than the public Nominatim or Overpass services. NC SOS, protected workers' compensation portals, and contractor-board search pages remain manual unless documented bulk access and automation permission are recorded.

## Source review checklist

Before enabling a new or materially changed connector, document:

- official owner and base URL;
- acquisition mode and automation permission;
- allowed fields and contact scope;
- retention/deletion requirements and attribution;
- request limit, paid-unit estimate, and hard run ceiling;
- terms review date and reviewer;
- stored parser fixture and expected schema;
- failure behavior, including how a CAPTCHA or login prompt disables the run.
