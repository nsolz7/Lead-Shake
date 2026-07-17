# Qualification, scoring, and review

Qualification runs before ranking. An account is export-eligible only when it is active, in a V1 vertical, has 2–5 verified physical premises in total, and independent control is `confirmed` or `likely`. Franchise, public, PE, subsidiary/corporate-chain, virtual-office, closed, one-location, and 6+-location groups fail the gate. LLC or corporate legal form does not fail the gate.

Location count is verified when all active locations come from an authoritative/first-party list or high-confidence locations are corroborated across at least two sources. Ambiguous entity links remain proposed until a reviewer accepts, rejects, or splits them.

## Rules score v1

| Category | Maximum | Factors |
|---|---:|---|
| Fit | 30 | V1 vertical, 2–5-location complexity, independent control, Raleigh serviceability |
| Timing | 25 | Exact/inferred renewal timing and dated non-risk business events |
| Coverage opportunity | 25 | Premises, WC, alcohol, auto/fleet, equipment, events, garage, professional/cyber exposures |
| Contactability | 10 | Named decision-maker and usable professional/business paths |
| Evidence quality | 10 | Authority, source diversity, and unresolved conflicts |

Tiers are A ≥80, B 65–79, C 50–64, and Hold <50 or ineligible. Every awarded point is stored as a `ScoreContribution`; displayed totals are the sum of those rows. Violations, inspection grades, or negative operational flags are `risk_review_only` and never add timing or propensity points.

Timing vocabulary is strict:

- `exact`: a policy date explicitly returned by coverage evidence;
- `inferred_anniversary`: an insurance anniversary with documented inference;
- `business_trigger`: a dated opening, ownership change, permit event, or similar sales-review event;
- `unknown`: no responsible timing basis.

The workbench does not present a purchase probability. Outcomes (`contacted`, `reply`, `meeting`, `quote`, `won`, `lost`, renewal date, reason) are captured for future evaluation. A separate calibrated model should be considered only after at least 500 contacted accounts and 50 positive outcomes, using a time-split holdout. Its probability must remain separate from the rules score.

## Reviewer checklist

1. Confirm every operating location, including out-of-territory locations and multiple brands.
2. Resolve legal entity and ownership; registered-agent data alone is never proof.
3. Confirm no franchise, public, PE, subsidiary, or national-chain control signal.
4. Inspect evidence conflicts and stale claims.
5. Check that owner/contact paths are professional or business scoped.
6. Verify timing labels and policy masking.
7. Add a useful pitch angle and approve, reject, suppress, or mark for research.
