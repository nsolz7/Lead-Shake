import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { CircleAlert, FlaskConical, RefreshCw, Search } from "lucide-react";
import { api } from "./api";
import type { Lead, ResearchBatch } from "./types";

function titleCase(value: string | null | undefined) {
  return value ? value.replaceAll("_", " ").replace(/\b\w/g, (x) => x.toUpperCase()) : "Unknown";
}

function localDate(value: string | null | undefined) {
  if (!value) return "Never assessed";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

export function ResearchQueuePage() {
  const [items, setItems] = useState<Lead[]>([]);
  const [batches, setBatches] = useState<ResearchBatch[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [researchState, setResearchState] = useState("");
  const [readiness, setReadiness] = useState("");
  const [mode, setMode] = useState<"free_public" | "ai_analysis">("free_public");
  const [perLeadBudget, setPerLeadBudget] = useState(10);
  const [totalBudget, setTotalBudget] = useState(100);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (researchState) params.set("research_state", researchState);
    if (readiness) params.set("ready", readiness);
    return params.toString();
  }, [readiness, researchState]);
  const load = useCallback(() => Promise.all([
    api<{ items: Lead[] }>(`/research/queue?${query}`),
    api<ResearchBatch[]>("/research/batches"),
  ]).then(([queue, history]) => { setItems(queue.items); setBatches(history); }), [query]);
  useEffect(() => { void load(); }, [load]);

  function toggle(id: string) {
    setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  async function createBatch(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setMessage("");
    try {
      await api("/research/batches", {
        method: "POST",
        body: JSON.stringify({
          mode,
          account_ids: selected,
          filters: selected.length ? {} : { research_state: researchState || undefined },
          approved_sources: mode === "ai_analysis" ? ["openai_web_research"] : [],
          max_leads: selected.length || 25,
          per_lead_budget_cents: mode === "ai_analysis" ? perLeadBudget : 0,
          total_budget_cents: mode === "ai_analysis" ? totalBudget : 0,
        }),
      });
      setSelected([]);
      setMessage(mode === "free_public" ? "Free research batch queued." : "Paid AI batch queued within both hard ceilings.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Research batch could not be created");
    } finally { setBusy(false); }
  }

  return <>
    <div className="page-head"><div><p className="eyebrow">Research-first workflow</p><h1>Research queue</h1><p>Complete bounded source attempts, resolve identity gaps, and only then prepare contact.</p></div><button className="icon-button" onClick={() => void load()} aria-label="Refresh research queue"><RefreshCw/></button></div>
    {message && <div className="alert amber">{message}</div>}
    <section className="research-workbench">
      <form className="panel research-batch-panel" onSubmit={createBatch}>
        <div className="panel-head"><div><p className="eyebrow">Bounded execution</p><h2>Create a research batch</h2></div><FlaskConical size={20}/></div>
        <label>Mode<select value={mode} onChange={(event) => setMode(event.target.value as "free_public" | "ai_analysis")}><option value="free_public">Approved free/open sources</option><option value="ai_analysis">Paid cited AI passes</option></select></label>
        {mode === "ai_analysis" && <div className="budget-grid"><label>Per-lead ceiling (cents)<input type="number" min={1} value={perLeadBudget} onChange={(event) => setPerLeadBudget(Number(event.target.value))}/></label><label>Total ceiling (cents)<input type="number" min={1} value={totalBudget} onChange={(event) => setTotalBudget(Number(event.target.value))}/></label></div>}
        <p className="section-note">{selected.length ? `${selected.length} explicitly selected account(s).` : "No explicit selection: the current state filter is used, capped at 25 leads."}</p>
        <button className="button primary wide-button" disabled={busy || (mode === "ai_analysis" && totalBudget < perLeadBudget * Math.max(selected.length, 1))}><Search size={16}/>{busy ? "Queueing…" : "Queue research batch"}</button>
        <div className="batch-history"><h3>Recent batches</h3>{batches.slice(0, 8).map((batch) => <article key={batch.id}><span className={`status-dot status-${batch.status}`}/><div><strong>{titleCase(batch.mode)}</strong><small>{batch.account_ids.length} accounts · {batch.spent_cents}/{batch.total_budget_cents}¢ spent</small></div><span>{titleCase(batch.status)}</span></article>)}</div>
      </form>
      <div className="queue-column">
        <section className="filter-bar research-filters"><select value={researchState} onChange={(event) => setResearchState(event.target.value)}><option value="">All research states</option>{["new", "stale", "in_progress", "blocked", "ready", "ready_override", "not_ready"].map((value) => <option value={value} key={value}>{titleCase(value)}</option>)}</select><select value={readiness} onChange={(event) => setReadiness(event.target.value)}><option value="">Any readiness</option><option value="true">Contact ready</option><option value="false">Not ready</option></select><button className="button small" onClick={() => setSelected(selected.length === items.length ? [] : items.map((lead) => lead.id))}>{selected.length === items.length && items.length ? "Clear all" : "Select all"}</button></section>
        <section className="research-queue-list">{!items.length ? <div className="empty"><FlaskConical size={30}/><strong>No leads match this queue</strong><p>Change a freshness/readiness filter or discover another lead.</p></div> : items.map((lead) => <label className={`research-queue-card ${selected.includes(lead.id) ? "selected" : ""}`} key={lead.id}><input type="checkbox" checked={selected.includes(lead.id)} onChange={() => toggle(lead.id)}/><div className="research-queue-main"><div><strong>{lead.name}</strong><span>{titleCase(lead.vertical)} · {lead.states.join(", ") || "Unknown state"}</span></div><div className="queue-badges"><span className={`badge ${lead.contact_ready ? "badge-green" : "badge-amber"}`}>{lead.contact_ready ? "Contact ready" : titleCase(lead.research_state)}</span><span className="badge badge-neutral">{lead.research_completeness}% attempted</span></div><progress max={100} value={lead.research_completeness}/><small>Assessed {localDate(lead.research_assessed_at)}</small>{lead.readiness_blockers.length > 0 && <div className="blocker-line"><CircleAlert size={14}/>{lead.readiness_blockers.map(titleCase).join(" · ")}</div>}</div></label>)}</section>
      </div>
    </section>
  </>;
}
