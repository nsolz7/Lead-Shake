import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { ResearchQueuePage } from "./ResearchQueuePage";
import type { Lead } from "./types";

vi.mock("./api", () => ({ api: vi.fn() }));

const lead = {
  id: "lead-1", name: "Ready Roofing", vertical: "contractors_trades", states: ["NC"],
  score: 82, tier: "A", contact_ready: false, research_state: "stale",
  research_completeness: 75, research_assessed_at: "2026-07-15T10:00:00Z",
  readiness_blockers: ["named_decision_maker"],
} as Lead;

describe("ResearchQueuePage", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset().mockImplementation(async (path) => {
      if (String(path).startsWith("/research/queue")) return { items: [lead] } as never;
      if (path === "/research/batches") return [] as never;
      if (path === "/research/batches") return {} as never;
      return {} as never;
    });
  });

  it("shows freshness, completion attempts, and readiness blockers", async () => {
    render(<ResearchQueuePage/>);
    expect(await screen.findByText("Ready Roofing")).toBeInTheDocument();
    expect(screen.getByText("75% attempted")).toBeInTheDocument();
    expect(screen.getByText("Named Decision Maker")).toBeInTheDocument();
  });

  it("creates a selected free batch with zero paid budget", async () => {
    render(<ResearchQueuePage/>);
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /queue research batch/i }));
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/research/batches", expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"account_ids":["lead-1"]'),
    })));
  });
});
