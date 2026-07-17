import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LeadDetail } from "./App";
import { api } from "./api";
import type { Lead } from "./types";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, api: vi.fn() };
});

const detail = {
  id: "lead-1", name: "Ready Roofing", vertical: "contractors_trades", states: ["NC"],
  location_count_verified: 3, ownership_status: "likely_independent", eligible: true,
  score: 82, tier: "A", review_status: "needs_research", research_completeness: 75,
  sales_stage: "uncontacted", relationship_status: "prospect", research_state: "not_ready",
  contact_ready: false, contact_ready_at: null, readiness_blockers: ["named_decision_maker"],
  classification_status: "target", classification_reason: "matched_vertical",
  classification_confidence: .9, classification_policy_version: "v1", evidence_count: 0,
  locations: [], contacts: [], people: [], permits: [], triggers: [], evidence: [],
  score_contributions: [], activities: [{ id: "a1", kind: "call", occurred_at: "2026-07-15T10:00:00Z", notes: "Spoke with office", disposition: "connected" }],
  tasks: [], services: [], exposures: [], ownership_relationships: [], business_events: [],
  coverages: [{ id: "p1", type: "general_liability", carrier: "Example Mutual", current: true, policy_status: "active", renewal_status: "reviewing", source_kind: "customer_reported", policy_masked: "••••1234" }],
} as unknown as Lead;

describe("LeadDetail CRM workspace", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset().mockImplementation(async (path) => {
      if (path === "/leads/lead-1") return detail as never;
      if (path === "/leads/lead-1/research-runs" || path === "/leads/lead-1/meetings") return [] as never;
      return {} as never;
    });
  });

  it("keeps interaction and policy history on the same account", async () => {
    render(<LeadDetail id="lead-1" onClose={() => undefined} onChanged={() => undefined}/>);
    fireEvent.click(await screen.findByRole("button", { name: "Interactions" }));
    expect(screen.getByText(/Spoke with office/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Policies" }));
    expect(screen.getByText(/Example Mutual/)).toBeInTheDocument();
    expect(screen.getByText("Current")).toBeInTheDocument();
  });

  it("shows readiness blockers and requires a scheduling override reason", async () => {
    render(<LeadDetail id="lead-1" onClose={() => undefined} onChanged={() => undefined}/>);
    fireEvent.click(await screen.findByRole("button", { name: "Meetings" }));
    expect(screen.getByText(/Scheduling is gated by research readiness/)).toBeInTheDocument();
    expect(screen.getByText(/Named Decision Maker/)).toBeInTheDocument();
    expect(screen.getByLabelText("Required override reason")).toBeRequired();
  });
});
