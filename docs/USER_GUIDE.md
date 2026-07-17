# Workbench User Guide

This guide explains how to operate the NC-SC-VA Commercial Insurance Lead Intelligence Workbench. The intended user is a commercial P&C producer or researcher who wants a smaller, defensible list of qualified accounts rather than a large unverified contact list.

The workbench does four things:

1. Discovers candidate businesses from permitted sources.
2. Groups brands, locations, and legal entities into an owner-controlled account.
3. Helps a human verify eligibility, timing, exposures, and contact paths.
4. Exports approved leads with the evidence supporting each material claim.

It does not automatically send email, place calls, bypass protected websites, or decide that a business is likely to purchase insurance.

## Before opening the workbench

Docker Desktop must be running before any `docker compose` command will work. Wait until Docker Desktop reports that its engine is running, then open PowerShell in the project directory.

For the first launch:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

Open `http://localhost:8080` and sign in with `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `.env`.

Useful operating commands:

```powershell
# Confirm that every service is running
docker compose ps

# Watch application and job output
docker compose logs -f api worker scheduler frontend

# Stop the application without deleting its database
docker compose down

# Load synthetic examples for training or testing
docker compose exec api python -m app.seed
```

The seed command creates five fictional examples. It is only a repeatable demo-data loader; it does not discover real prospects or enrich the lead database.

The Compose service that runs Celery beat is named `scheduler`, not `beat`. To rebuild the background services after an update, use:

```powershell
docker compose up -d --force-recreate api worker scheduler
```

## The basic operating sequence

Use the tabs in roughly this order:

```text
Source health -> Runs & imports -> Match review -> Research queue -> Lead queue
                                              -> Profile / Interactions / Policies / Meetings
                                              -> Suppressions / Evidence packs
```

You will return to **Overview** throughout the process to see whether the queue is improving.

## Overview

The Overview tab is the daily starting point. It summarizes:

- **Qualified accounts:** accounts currently passing the 2-5-location, vertical, operating-status, and independent-control gates.
- **Approved for export:** qualified accounts a human has approved.
- **Tier A priority:** eligible accounts scoring 80 or higher.
- **Matches to review:** possible duplicate or commonly controlled accounts awaiting a decision.
- **Highest-priority qualified accounts:** the next accounts worth researching.
- **Sources reporting errors:** connectors or imports requiring attention.
- **Research runs needing attention:** partial or failed enrichment work.
- **Follow-ups due:** open sales tasks whose due time has arrived.

How to use it:

- If qualified accounts are low, run discovery or add corroborating sources.
- If matches are waiting, resolve them before trusting location counts.
- If many accounts are qualified but few are approved, work through the Lead queue.
- If a source reports an error, open Source health before starting more work.

The Overview is a workload summary. It is not a sales forecast.

## Source health

Source health shows the acquisition rules and operational state of every source, grouped by jurisdiction.

Each source displays:

- acquisition type, such as bulk download, permitted crawl, API, manual lookup, or commercial API;
- source authority;
- whether it is paid;
- whether it is healthy, stale, disabled, or reporting an error;
- notes about important restrictions.

Use the switch to disable a source when:

- its terms or access method need review;
- its schema has changed;
- credentials are missing;
- it is returning unreliable data;
- you do not want it available for runs.

Disabling a source prevents new runs. It does not erase evidence already collected.

Important boundaries:

- Do not automate the NC Secretary of State interactive search.
- Do not bypass a login, CAPTCHA, rate limit, or robots rule.
- Google Places data is retained as Place IDs only. Any richer Google validation is shown live and is not persisted.
- Hunter and email verification require explicit paid-run approval and a hard spending ceiling.

## Runs & imports

This tab handles both automated acquisition and human-acquired official files.

### Start a scoped run

Choose a source, select the states, set a record ceiling, and enter targets when the connector needs them.

| Source | What to enter in Targets |
|---|---|
| Overture Places | Nothing. Configure `OVERTURE_RELEASE` or `OVERTURE_PARQUET_URI` in `.env`. |
| First-party business websites | One complete website URL per line. |
| Google Places IDs-only | One focused search phrase per line, such as `brewery Raleigh NC`. |
| Hunter domain search | One business domain per line, such as `example.com`. |
| Professional email verification | One professional or business email per line. |

The **record ceiling** is a safety limit, not a target you must reach. It counts accepted, in-state records across the whole run. Begin with 100-500 NC records while validating a source. Run history also shows rejected totals and reasons such as out of state, missing state, invalid address, and unknown vertical.

Overture is discovery data. Its `open` status is normalized to active, but an Overture-only footprint remains unverified. An official source or permitted first-party location list must corroborate the owner-controlled location count before qualification.

For a commercial connector:

1. Check **Explicitly enable this paid run**.
2. Enter the maximum permitted spend in cents.
3. Review the target count before submitting.
4. Reconcile estimated usage with the provider account afterward.

Examples:

- `500` means a hard ceiling of $5.00.
- `2500` means a hard ceiling of $25.00.

### Import an official snapshot

Use the right side of the tab for an agency CSV, XLS, or XLSX file obtained through a documented download, subscription, list request, API export, or FOIA response.

1. Choose the exact source that supplied the file.
2. Select the file.
3. Click **Import snapshot**.
4. Check Run history for the result.

The workbench hashes and stores the original bytes under the source's retention policy. Common column names are mapped automatically. If a file has unusual headings, use the API's `mapping_json` option or add a source-specific mapping before relying on the results.

### Understand run statuses

- **Queued:** waiting for a worker.
- **Running:** actively processing records.
- **Completed:** finished without a fatal error.
- **Failed:** stopped with an error; read the displayed message and logs.
- **Awaiting upload:** the source expects an official file rather than a live call.
- **Awaiting manual:** the source requires human research or an approved acquisition step.

`Seen`, `created`, and `updated` are ingestion counts. They are not counts of qualified leads.

## Match review

Match review prevents false merges and incorrect location totals.

A proposed match can be based on signals such as:

- shared domain;
- shared normalized phone;
- very similar business names;
- shared address;
- authoritative entity or permit identifiers.

For each proposal, compare both account names, domains, locations, legal entities, brands, and ownership evidence.

Choose:

- **Merge accounts** when the records represent the same owner-controlled operation.
- **Keep separate** when similarly named businesses are genuinely unrelated.
- **Reject link** when the matching proposal itself is unreliable.

Be conservative. A false merge can turn two unrelated businesses into a seemingly qualified multi-location account. A common address, family surname, or registered agent is supporting evidence, not proof of common ownership.

After merging, the qualification and score are recalculated using the combined locations and evidence.

## Lead queue

The Lead queue is the main research and approval workspace. Accounts are ordered by score and name.

### Filters

Use the filters to focus work by:

- business name or domain;
- NC, SC, or VA;
- V1 vertical;
- A, B, C, or Hold tier;
- review state;
- sales stage;
- qualified or excluded status.

Useful working views:

- **Qualified only + New:** accounts ready for first human review.
- **Qualified only + Needs research:** accounts with an identified evidence gap.
- **Tier A + Approved:** highest-priority accounts ready for export.
- **Excluded only:** quality-control sample for checking gate accuracy.

### Read the queue row

Each row shows:

- score and tier;
- account and vertical;
- verified location count and states;
- ownership-control assessment;
- timing type and next action date;
- review status and assertion count.

An account in Hold may still have a numeric score. Hold means it is ineligible or below 50 and should not be exported through the normal workflow.

### Lead detail: Profile

Open a row to inspect the account drawer. Profile includes:

- all known physical locations and whether each is authoritative;
- named decision-makers and confidence;
- professional and business contact paths;
- permits, licenses, carriers, and coverage dates;
- business triggers and risk-review flags;
- the current qualification result and exclusion reason;
- the suggested coverage conversation.

Location count should cover the entire owner-controlled operation, including other brands and out-of-territory locations. Do not approve an account merely because 2-5 local branches were found.

### Add manual workers' compensation evidence

Use **Add manual workers' comp evidence** after a permitted human lookup in the appropriate state portal.

Enter only what the portal actually returned:

- state portal;
- carrier;
- effective, expiration, or coverage-as-of date;
- portal record ID and source URL;
- policy identifier, if displayed;
- short evidence excerpt;
- honest confidence level.

The full policy identifier is converted to a salted HMAC and a last-four mask. A permit expiration, annual report date, or company formation date must never be entered as a policy expiration.

An unsuccessful search is not proof that the business lacks coverage.

### Lead detail: Research

Mark an account **Needs research**, then choose **Run free research**. The free run validates geography and classification, correlates imported public records, proposes website candidates, crawls an already accepted first-party website, rescores the account, prepares a deterministic call brief, and creates manual portal tasks. It never invokes OpenAI, Hunter, Google Places, email verification, or another metered source.

Use **Run AI analysis** separately when free research leaves important gaps. Enter a ceiling in cents for that AI run only. A zero application maximum, missing API key, unknown rate card, or insufficient ceiling prevents the call. The run shows the authorized maximum separately from calculated token and web-search usage. A ChatGPT Plus subscription does not include OpenAI API usage.

Website, decision-maker, ownership, location, service, exposure, event, wrong-vertical, and wrong-entity findings remain proposed. Review the citation and excerpt, then accept or reject each finding. Accepting a website queues a second robots-aware first-party crawl. Accepting another finding creates a typed record while retaining derived authority and the decision audit; rejected findings never alter the lead.

Research completeness tracks identity, geography, website, footprint, ownership, contacts, licenses, exposures, timing, and blockers. It is deliberately separate from the opportunity score.

### Lead detail: Activity

Use Activity to move the independent sales stage through `uncontacted`, `attempting`, `connected`, `meeting scheduled`, `quote in progress`, and `won`, `lost`, or `nurture`. Log calls, email, meetings, and notes; add dispositions; and schedule the next call, email, meeting, or research task. A do-not-contact disposition immediately suppresses the account.

### Lead detail: Score

The Score sub-tab reconciles every awarded point across:

- Fit: 30 maximum;
- Timing: 25 maximum;
- Coverage opportunity: 25 maximum;
- Contactability: 10 maximum;
- Evidence quality: 10 maximum.

Tiers are:

- A: 80-100;
- B: 65-79;
- C: 50-64;
- Hold: below 50 or ineligible.

The score ranks research and sales priority. It is not a probability that the prospect will buy insurance.

### Lead detail: Evidence

The Evidence sub-tab is the audit trail. Every assertion shows its source, field, value, authority, confidence, retrieval date, hash, and optional excerpt.

Use it to answer:

- Where did the owner name come from?
- Which source supports the location count?
- Is the coverage date exact or inferred?
- Are two sources contradicting one another?
- Is the evidence fresh enough to use?

Conflicting assertions remain visible. Research the conflict before approval rather than selecting the more convenient value.

If the account has a Google Place ID, **Validate live** retrieves a temporary attributed view. That response is displayed for validation and is not saved as lead data.

### Review decisions

- **Approve:** the account passes the target profile and its material claims are sufficiently supported.
- **Needs research:** the account may fit but a material question remains.
- **Reject:** the account is unsuitable or the apparent qualification is incorrect.

Approval is the human control that allows an A-C account into the default export.

## Suppressions

Suppressions are durable do-not-contact and do-not-export controls.

You can suppress:

- an email address;
- a phone number;
- an entire domain;
- an account ID.

Enter the normalized value and a clear reason such as `opt_out`, `existing_client`, `do_not_contact`, or `wrong_party`.

Use an account-level suppression when no contact associated with the account should be exported. Email, phone, and domain suppressions are useful when only one contact path is prohibited.

Suppression entries apply to future exports. Do not delete an opt-out just to make a contact reappear.

## Evidence packs

This tab creates and stores reviewed deliverables.

**Export approved A-C leads** exports only accounts that:

- are approved by a human;
- are in tiers A, B, or C;
- are not excluded by the default export filters;
- have contact paths that survive suppression checks.

The ZIP includes:

- `leads.xlsx`;
- CSVs for leads, locations, contacts, licenses and coverage, triggers and exposures, evidence, and exclusions;
- `manifest.json` with filters, score version, source versions, run parameters, generation time, and a deterministic snapshot fingerprint.

Professional and business contact paths export by default. Home addresses and personal phones do not.

The manifest hash shown in the tab identifies that export batch. Keep the ZIP intact when handing the research to another system or reviewer.

## Example: build a Raleigh-area hospitality prospect list

This example shows a practical end-to-end workflow for finding independently controlled restaurant, brewery, and event operators with 2-5 total locations.

### 1. Prepare a narrow pilot

In `.env`, configure an Overture release or local Places GeoParquet snapshot. Confirm that Docker Desktop and every Compose service are running.

Open **Source health** and verify that these sources are enabled and not reporting errors:

- Overture Places;
- First-party business websites;
- NC ABC permits;
- NC SOS subscription, if acquired;
- NC Industrial Commission coverage search for manual lookup;
- Hunter only if you plan to spend credits.

### 2. Discover candidates

Open **Runs & imports**.

Choose Overture Places, select NC, and use a conservative record ceiling such as 1,000 for the first run. Queue the run and wait for Completed status.

At this stage, expect raw candidates, single locations, uncertain ownership, and duplicates. Do not export yet.

### 3. Add official records

Acquire the permitted NC ABC file or export and upload it as **NC ABC permits**. If you have the NC SOS subscription, import that snapshot as well.

These sources can add permit identifiers, legal entities, statuses, officials, and corroborating locations. The system may create match proposals when an official record cannot be linked safely by an exact identifier.

### 4. Resolve identities

Open **Match review**.

Suppose `Oak City Table`, `Oak City Catering`, and `Oak City Events LLC` share a domain and owner but operate at three premises. Confirm the first-party site and legal records, then merge them into one account group.

If another `Oak City Table` in a different town has a different domain, owner, and address, keep it separate.

The goal is one account per owner-controlled insurance opportunity, not one account per storefront.

### 5. Enrich first-party websites

Return to **Runs & imports**, choose First-party business websites, and enter the strongest candidate websites one per line.

The crawl checks permitted pages such as locations, about, team, contact, events, catering, careers, and franchise pages. It may find:

- a complete location list;
- founder or family-ownership language;
- decision-makers;
- public business email, phone, or contact form;
- event, catering, fleet, hiring, or expansion signals;
- franchise language that should exclude the account.

### 6. Work the evidence gaps

Open **Lead queue** and filter to NC, Hospitality Alcohol Events, Qualified only, and New.

For each account:

1. Confirm all brands and all physical locations.
2. Verify independent control from more than a registered-agent name.
3. Check for franchise, public-company, private-equity, subsidiary, or national-chain signals.
4. Confirm that owner and contact paths are professional or business scoped.
5. Review ABC permits and material exposures.
6. Open Score and verify that the total makes sense.
7. Open Evidence and resolve conflicts or stale claims.

Use **Needs research** whenever location count, ownership, or identity is still uncertain.

### 7. Add responsible timing evidence

For a high-value candidate, perform a permitted manual NC Industrial Commission lookup using the exact legal employer name.

If the portal explicitly returns a carrier and policy period, add it through **Add manual workers' comp evidence**. The policy expiration can become exact timing evidence.

If you only find an ABC expiration or company formation date, keep it as a permit or business trigger. Do not label it an insurance renewal date.

### 8. Approve the account

Approve when the account has:

- 2-5 verified total operating locations;
- confirmed or likely independent control;
- no disqualifying control signal;
- a target V1 vertical;
- sufficient provenance for material claims;
- at least one responsible contact or research path.

A plausible successful result might be:

```text
Account: Oak City Hospitality Group
Locations: 3 verified
Control: Confirmed independent
Tier: A, score 86
Timing: Exact WC expiration in 108 days
Primary angle: Multi-location property, liquor liability, WC, cyber, and umbrella review
Decision-maker: Named managing member
Contact paths: Verified professional email, business phone, contact form
Review: Approved
```

### 9. Export the calling list

Open **Evidence packs** and select **Export approved A-C leads**.

Download the ZIP. Begin with the lead workbook, then use the supporting CSVs and evidence sheet when preparing personalized outreach. Preserve the manifest so you know exactly which source snapshots and scoring version produced the list.

### 10. Use the list responsibly

Prioritize A leads with exact or strong timing evidence, then B leads with clear coverage complexity. Use the suggested pitch as a research starting point, not a scripted claim.

Record contacts, conversations, meetings, policies, and follow-ups on the same account. Maintain opt-outs in **Suppressions** before generating the next export. Automated outreach remains outside the workbench's scope.

## Research queue and readiness

The **Research queue** is the daily work surface for new, stale, blocked, and contact-ready accounts. Completeness means a permitted research attempt was completed; it does not imply every fact was discoverable. `Attempted no evidence` is a legitimate result for legal/licensing, operations/exposures, insurance/timing, and recent-event dimensions.

Contact-ready requires all critical gates: active target classification, verified 2-5-location footprint, accepted first-party identity/domain, likely or confirmed independent control, a named decision-maker, a usable business/professional contact path, and no unresolved identity conflict. Select leads and create a free batch for approved sources. Paid AI batches require explicit source approval plus per-lead and batch-total ceilings.

## Profile, interactions, and policies

**Profile** keeps the account relationship (`prospect`, `active client`, or `former client`) and limited contact preferences. Researched names and roles stay evidence-backed; preferred name, communication preference, tags, interests, timezone, and relationship notes are manual CRM fields. Do not enter home addresses, sensitive identifiers, or unverified personal contacts.

**Interactions** records calls, emails, conversations, meetings, policy reviews, and internal notes. An interaction can create its linked follow-up in the same save. Notes can be corrected later without moving history to another account. Setting sales stage to **Won** promotes the account to active client.

**Policies** is append-only. Customer-reported and producer-entered changes create a new snapshot and retain the previous version. The current card is the latest non-superseded snapshot per line of business. Policy identifiers are never retained in full.

## Meetings and Google Calendar

Connect Calendar only after application OAuth is configured. A meeting cannot be scheduled until the latest assessment is contact-ready. If business context justifies proceeding, enter a specific override reason; it is stored as an audited readiness decision.

Choose attendees deliberately. **Send attendee invitations** is opt-in. Google owns the current time, timezone, location, attendee responses, Meet details, and cancellation state. The application owns the lead link, research brief, policy context, follow-ups, and private preparation notes. Those private fields are never copied into attendee-visible Calendar content. Managed events synchronize every five minutes when the feature is enabled; pending/auth/conflict badges show when intervention is needed.

## What success looks like

A successful weekly cycle is not measured by the number of raw records collected. It produces:

- fewer false merges;
- verified 2-5-location account groups;
- clear ownership-control evidence;
- fresh, source-backed timing and exposure signals;
- named professional decision-makers where publicly available;
- reviewed A-C accounts;
- a suppression-safe evidence pack;
- documented outcomes that can eventually support a separate propensity model.

For source-specific acquisition rules, read [SOURCE_ACQUISITION.md](SOURCE_ACQUISITION.md). For the point system and review standards, read [SCORING_AND_REVIEW.md](SCORING_AND_REVIEW.md).
