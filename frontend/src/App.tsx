import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDownToLine, BarChart3, CalendarDays, Check, ChevronRight, CircleAlert, Database,
  FileArchive, FileSearch, FlaskConical, GitMerge, LayoutDashboard, LogOut, Menu, Play, RefreshCw,
  Search, ShieldCheck, SlidersHorizontal, Upload, UserRoundSearch, X,
} from "lucide-react";
import { api, ApiError, downloadExport, login, logout, safeHref } from "./api";
import { FishBadge, FishLogo, FishToggle } from "./fish";
import { CalendarIntegrationPage } from "./CalendarIntegrationPage";
import { ResearchQueuePage } from "./ResearchQueuePage";
import type { Dashboard, ExportBatch, Lead, Meeting, Page, ResearchRun, Run, Source } from "./types";

const NAV: Array<{ page: Page; label: string; icon: typeof LayoutDashboard }> = [
  { page: "dashboard", label: "Overview", icon: LayoutDashboard },
  { page: "research", label: "Research queue", icon: FlaskConical },
  { page: "leads", label: "Lead queue", icon: UserRoundSearch },
  { page: "matches", label: "Match review", icon: GitMerge },
  { page: "runs", label: "Runs & imports", icon: Play },
  { page: "sources", label: "Source health", icon: Activity },
  { page: "integrations", label: "Calendar", icon: CalendarDays },
  { page: "exports", label: "Evidence packs", icon: FileArchive },
  { page: "suppressions", label: "Suppressions", icon: ShieldCheck },
];

function fmtDate(value: unknown) {
  if (!value || typeof value !== "string") return "—";
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const date = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleDateString();
}

function fmtMicroUsd(value: number | undefined) {
  return `$${((value || 0) / 1_000_000).toFixed(4)}`;
}

function titleCase(value: unknown) {
  if (!value || typeof value !== "string") return "Unknown";
  return value.replaceAll("_", " ").replace(/\b\w/g, (x) => x.toUpperCase());
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

function Score({ value, tier }: { value: number; tier: string }) {
  const tone = tier === "A" ? "a" : tier === "B" ? "b" : tier === "C" ? "c" : "neutral";
  const alive = tier === "A" || tier === "B";
  return <div className="score-cell">
    <FishBadge alive={alive} />
    <div className={`score score-${tone}`}><strong>{value}</strong><span>{tier}</span></div>
  </div>;
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="empty"><FileSearch size={30} /><strong>{title}</strong><p>{detail}</p></div>;
}

function Loading() {
  return <div className="loading"><RefreshCw className="spin" size={18} /> Loading current records…</div>;
}

function Login({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { await login(username, password); onDone(); }
    catch (err) { setError(err instanceof Error ? err.message : "Login failed"); }
    finally { setBusy(false); }
  }
  return <div className="login-shell">
    <div className="login-brand"><span className="brand-mark"><FishLogo size={34} /></span><span>Lead Shake</span></div>
    <form className="login-card" onSubmit={submit}>
      <div><p className="eyebrow">Local workbench</p><h1>Commercial lead research, with receipts.</h1>
        <p>Sign in to the private NC–SC–VA research workspace.</p></div>
      <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
      <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus /></label>
      {error && <div className="alert"><CircleAlert size={16} />{error}</div>}
      <button className="button primary" disabled={busy}>{busy ? "Signing in…" : "Open workbench"}<ChevronRight size={17} /></button>
      <small>Credentials are read from your local environment file.</small>
    </form>
  </div>;
}

function DashboardPage({ openLeads }: { openLeads: () => void }) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  useEffect(() => { Promise.all([
    api<Dashboard>("/dashboard"), api<{ items: Lead[] }>("/leads?eligible=true&limit=6"),
  ]).then(([d, l]) => { setData(d); setLeads(l.items); }); }, []);
  if (!data) return <Loading />;
  const cards = [
    ["Research due", data.research_new_or_stale, "New or stale active accounts"],
    ["Contact ready", data.contact_ready, "All critical research gates passed"],
    ["Today's meetings", data.meetings_today, "Application-managed calendar events"],
    ["Overdue follow-ups", data.followups_due, "Open actions that need attention"],
  ];
  return <>
    <div className="easter-egg" title="Shake the bag. Just don't shake it too much."><FishToggle /></div>
    <div className="page-head"><div><p className="eyebrow">Portfolio pulse</p><h1>Research overview</h1><p>Explainable priority, current evidence, and the work that needs judgment.</p></div>
      <button className="button primary" onClick={openLeads}>Review lead queue<ChevronRight size={17} /></button></div>
    <section className="metric-grid">{cards.map(([label, value, detail]) => <article className="metric" key={String(label)}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>)}</section>
    <section className="split-grid">
      <article className="panel"><div className="panel-head"><div><p className="eyebrow">Next best work</p><h2>Highest-priority qualified accounts</h2></div><BarChart3 size={20} /></div>
        {leads.length ? <div className="compact-list">{leads.map((lead) => <div className="compact-lead" key={lead.id}><Score value={lead.score} tier={lead.tier}/><div><strong>{lead.name}</strong><span>{titleCase(lead.vertical)} · {lead.states.join(", ")} · {lead.location_count_verified ?? "?"} locations</span></div><Badge tone={lead.review_status === "approved" ? "green" : "neutral"}>{titleCase(lead.review_status)}</Badge></div>)}</div> : <Empty title="No qualified accounts yet" detail="Run Overture discovery or import an official source file." />}
      </article>
      <article className="panel health-card"><div className="panel-head"><div><p className="eyebrow">Data quality</p><h2>Attention needed</h2></div><Database size={20} /></div>
        <div className="attention-row"><span>All discovered records</span><strong>{data.total_leads}</strong></div>
        <div className="attention-row"><span>Unresolved entity matches</span><strong>{data.proposed_matches}</strong></div>
        <div className="attention-row"><span>Findings awaiting review</span><strong className={data.pending_findings ? "danger-text" : "good-text"}>{data.pending_findings}</strong></div>
        <div className="attention-row"><span>Blocked research runs</span><strong className={data.blocked_research ? "danger-text" : "good-text"}>{data.blocked_research}</strong></div>
        <div className="attention-row"><span>Sources reporting errors</span><strong className={data.failed_sources ? "danger-text" : "good-text"}>{data.failed_sources}</strong></div>
        <div className="attention-row"><span>Research runs needing attention</span><strong className={data.research_failures ? "danger-text" : "good-text"}>{data.research_failures}</strong></div>
        <div className="attention-row"><span>Follow-ups due</span><strong className={data.followups_due ? "danger-text" : "good-text"}>{data.followups_due}</strong></div>
        <p className="callout"><ShieldCheck size={18} /> Only approved leads and professional contact paths enter the default export.</p>
      </article>
    </section>
  </>;
}

interface LeadFilters { q: string; state: string; vertical: string; tier: string; review: string; eligible: string; sales: string }

export function LeadDetail({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const [lead, setLead] = useState<Lead | null>(null);
  const [tab, setTab] = useState("profile");
  const [busy, setBusy] = useState(false);
  const [googleView, setGoogleView] = useState<Record<string, unknown> | null>(null);
  const [showCoverageForm, setShowCoverageForm] = useState(false);
  const [researchRuns, setResearchRuns] = useState<ResearchRun[]>([]);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [researchBudget, setResearchBudget] = useState(5);
  const [message, setMessage] = useState("");
  const load = useCallback(() => Promise.all([
    api<Lead>(`/leads/${id}`), api<ResearchRun[]>(`/leads/${id}/research-runs`), api<Meeting[]>(`/leads/${id}/meetings`),
  ]).then(([currentLead, runs, currentMeetings]) => { setLead(currentLead); setResearchRuns(runs); setMeetings(currentMeetings); }), [id]);
  useEffect(() => { load(); }, [load]);
  const researchActive = researchRuns.some((run) => ["queued", "running"].includes(run.status));
  useEffect(() => {
    if (!researchActive) return;
    const timer = window.setInterval(() => { load().then(onChanged); }, 3000);
    return () => window.clearInterval(timer);
  }, [load, onChanged, researchActive]);
  async function decide(decision: string) {
    setBusy(true);
    try { await api(`/leads/${id}/review`, { method: "POST", body: JSON.stringify({ decision }) }); await load(); onChanged(); }
    finally { setBusy(false); }
  }
  async function validateGoogle() {
    setBusy(true);
    try {
      setGoogleView(await api<Record<string, unknown>>(`/leads/${id}/google-validation`, {
        method: "POST", body: JSON.stringify({ confirm_live_request: true }),
      }));
    } finally { setBusy(false); }
  }
  async function startResearch() {
    setBusy(true); setMessage("");
    try {
      await api(`/leads/${id}/research-runs`, { method: "POST", body: JSON.stringify({ mode: "free_public" }) });
      setTab("research"); setMessage("Free public research queued. No paid API will run."); await load(); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Research could not start"); }
    finally { setBusy(false); }
  }
  async function startAiAnalysis() {
    setBusy(true); setMessage("");
    try {
      await api(`/leads/${id}/ai-analysis-runs`, { method: "POST", body: JSON.stringify({ budget_cents: researchBudget }) });
      setTab("research"); setMessage("AI analysis queued with the approved ceiling."); await load(); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "AI analysis could not start"); }
    finally { setBusy(false); }
  }
  async function approvePaid(runId: string) {
    setBusy(true); setMessage("");
    try {
      await api(`/research-runs/${runId}/approve-paid`, { method: "POST", body: JSON.stringify({ budget_cents: researchBudget }) });
      setMessage("Paid research approved and queued."); await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Paid research could not start"); }
    finally { setBusy(false); }
  }
  async function retryStep(runId: string, kind: string) {
    setBusy(true);
    try { await api(`/research-runs/${runId}/steps/${kind}/retry`, { method: "POST" }); await load(); }
    finally { setBusy(false); }
  }
  async function decideFinding(findingId: string, decision: "accept" | "reject") {
    setBusy(true); setMessage("");
    try {
      const result = await api<{ followup_run_id?: string }>(`/research-findings/${findingId}/decision`, {
        method: "POST", body: JSON.stringify({ decision }),
      });
      setMessage(result.followup_run_id ? "Website accepted. A second first-party crawl was queued." : `Finding ${decision}ed.`);
      await load(); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Finding decision failed"); }
    finally { setBusy(false); }
  }
  async function addWebsiteCandidate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); setBusy(true); setMessage("");
    try {
      await api(`/leads/${id}/website-candidates`, {
        method: "POST", body: JSON.stringify({ url: values.get("url"), notes: values.get("notes") || null }),
      });
      form.reset(); setMessage("Website candidate added for review."); await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Website candidate could not be added"); }
    finally { setBusy(false); }
  }
  async function updateStage(stage: string) {
    setBusy(true);
    try { await api(`/leads/${id}/sales-stage`, { method: "PATCH", body: JSON.stringify({ stage }) }); await load(); onChanged(); }
    finally { setBusy(false); }
  }
  async function updateRelationship(relationship_status: string) {
    setBusy(true);
    try { await api(`/leads/${id}/profile`, { method: "PATCH", body: JSON.stringify({ relationship_status }) }); await load(); onChanged(); }
    finally { setBusy(false); }
  }
  async function addPerson(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); setBusy(true); setMessage("");
    try {
      await api(`/leads/${id}/people`, { method: "POST", body: JSON.stringify({
        name: values.get("name"), role: values.get("role") || null,
        preferred_name: values.get("preferred_name") || null,
        communication_preference: values.get("communication_preference") || null,
        timezone: values.get("timezone") || null,
        is_primary_contact: values.get("is_primary_contact") === "on",
        tags: String(values.get("tags") || "").split(",").map((value) => value.trim()).filter(Boolean),
        relationship_notes: values.get("relationship_notes") || null,
      }) });
      form.reset(); setMessage("Contact profile added without changing researched evidence."); await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Contact profile could not be added"); }
    finally { setBusy(false); }
  }
  async function addActivity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); setBusy(true);
    try {
      await api(`/leads/${id}/activities`, { method: "POST", body: JSON.stringify({
        kind: values.get("kind"), disposition: values.get("disposition") || null,
        subject: values.get("subject") || null, direction: values.get("direction") || "outbound",
        duration_minutes: values.get("duration_minutes") ? Number(values.get("duration_minutes")) : null,
        person_role_id: values.get("person_role_id") || null, outcome: values.get("outcome") || null,
        notes: values.get("notes") || null, details: {},
        follow_up: values.get("follow_up_at") ? {
          title: values.get("follow_up_title") || "Follow up",
          kind: values.get("follow_up_kind") || "call",
          due_at: new Date(String(values.get("follow_up_at"))).toISOString(),
          priority: values.get("follow_up_priority") || "normal",
        } : null,
      }) });
      form.reset(); await load(); onChanged();
    } finally { setBusy(false); }
  }
  async function addTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); setBusy(true);
    try {
      await api(`/leads/${id}/tasks`, { method: "POST", body: JSON.stringify({
        kind: values.get("kind"), due_at: new Date(String(values.get("due_at"))).toISOString(),
        title: values.get("title") || null, priority: values.get("priority") || "normal",
        person_role_id: values.get("person_role_id") || null, notes: values.get("notes") || null,
      }) });
      form.reset(); await load(); onChanged();
    } finally { setBusy(false); }
  }
  async function completeTask(taskId: string) {
    setBusy(true);
    try { await api(`/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify({ status: "completed" }) }); await load(); onChanged(); }
    finally { setBusy(false); }
  }
  async function addCoverage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const optional = (name: string) => String(values.get(name) || "") || null;
    setBusy(true);
    try {
      await api(`/leads/${id}/coverage`, {
        method: "POST",
        body: JSON.stringify({
          source_id: values.get("source_id"), coverage_type: "workers_comp",
          carrier: optional("carrier"), policy_identifier: optional("policy_identifier"),
          effective_on: optional("effective_on"), expires_on: optional("expires_on"),
          coverage_as_of: optional("coverage_as_of"), confidence: values.get("confidence"),
          source_record_id: values.get("source_record_id"), source_url: optional("source_url"),
          evidence_excerpt: optional("evidence_excerpt"),
        }),
      });
      setShowCoverageForm(false); await load(); onChanged();
    } finally { setBusy(false); }
  }
  async function addPolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); setBusy(true); setMessage("");
    const optional = (name: string) => String(values.get(name) || "") || null;
    try {
      await api(`/leads/${id}/policies`, { method: "POST", body: JSON.stringify({
        coverage_type: values.get("coverage_type"), carrier: optional("carrier"),
        policy_identifier: optional("policy_identifier"), effective_on: optional("effective_on"),
        expires_on: optional("expires_on"), policy_status: values.get("policy_status"),
        renewal_status: values.get("renewal_status"), source_kind: values.get("source_kind"),
        observed_on: values.get("observed_on"),
        annual_premium: values.get("annual_premium") ? Number(values.get("annual_premium")) : null,
        notes: optional("notes"), confidence: values.get("confidence"),
      }) });
      form.reset(); setMessage("New append-only policy snapshot saved."); await load(); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Policy snapshot could not be saved"); }
    finally { setBusy(false); }
  }
  async function addMeeting(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); setBusy(true); setMessage("");
    const attendee = String(values.get("attendee_email") || "").trim();
    try {
      await api(`/leads/${id}/meetings`, { method: "POST", body: JSON.stringify({
        title: values.get("title"), person_role_id: values.get("person_role_id") || null,
        start_at: new Date(String(values.get("start_at"))).toISOString(),
        end_at: new Date(String(values.get("end_at"))).toISOString(),
        timezone: values.get("timezone"), location: values.get("location") || null,
        attendees: attendee ? [{ email: attendee }] : [],
        reminder_minutes: Number(values.get("reminder_minutes") || 30),
        create_meet: values.get("create_meet") === "on", send_updates: values.get("send_updates") === "on",
        private_prep_notes: values.get("private_prep_notes") || null,
        readiness_override_reason: values.get("readiness_override_reason") || null,
      }) });
      form.reset(); setMessage("Meeting saved and queued for idempotent calendar synchronization."); await load(); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Meeting could not be scheduled"); }
    finally { setBusy(false); }
  }
  async function syncMeeting(meetingId: string) {
    setBusy(true); setMessage("");
    try { await api(`/meetings/${meetingId}/sync`, { method: "POST" }); setMessage("Meeting synchronized."); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Meeting synchronization failed"); }
    finally { setBusy(false); }
  }
  async function cancelMeeting(meetingId: string) {
    setBusy(true); setMessage("");
    try { await api(`/meetings/${meetingId}/cancel`, { method: "POST" }); setMessage("Meeting cancelled locally and in Google when connected."); await load(); onChanged(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Meeting cancellation failed"); }
    finally { setBusy(false); }
  }
  if (!lead) return <aside className="drawer"><Loading /></aside>;
  const locations = (lead.locations ?? []) as Array<Record<string, unknown>>;
  const contacts = (lead.contacts ?? []) as Array<Record<string, unknown>>;
  const people = (lead.people ?? []) as Array<Record<string, unknown>>;
  const permits = (lead.permits ?? []) as Array<Record<string, unknown>>;
  const coverages = (lead.coverages ?? []) as Array<Record<string, unknown>>;
  const triggers = (lead.triggers ?? []) as Array<Record<string, unknown>>;
  const evidence = (lead.evidence ?? []) as Array<Record<string, unknown>>;
  const contributions = (lead.score_contributions ?? []) as Array<Record<string, unknown>>;
  const activities = (lead.activities ?? []) as Array<Record<string, unknown>>;
  const tasks = (lead.tasks ?? []) as Array<Record<string, unknown>>;
  const services = (lead.services ?? []) as Array<Record<string, unknown>>;
  const exposures = (lead.exposures ?? []) as Array<Record<string, unknown>>;
  const ownershipRelationships = (lead.ownership_relationships ?? []) as Array<Record<string, unknown>>;
  const businessEvents = (lead.business_events ?? []) as Array<Record<string, unknown>>;
  const latestResearch = researchRuns[0];
  return <aside className="drawer">
    <div className="drawer-head"><div><p className="eyebrow">Account group</p><h2>{lead.name}</h2><div className="inline-badges"><Badge tone={lead.eligible ? "green" : "amber"}>{lead.eligible ? "Qualified" : "Not qualified"}</Badge><Badge>{titleCase(lead.ownership_status)} control</Badge><Badge tone="blue">{lead.research_completeness}% researched</Badge></div></div><button className="icon-button" onClick={onClose} aria-label="Close"><X /></button></div>
    <div className="drawer-score"><Score value={lead.score} tier={lead.tier}/><div><strong>{lead.best_pitch_angle || "Needs more evidence"}</strong><span>{lead.location_count_verified ?? "Unverified"} total operating locations · {lead.states.join(", ") || "No state"}</span></div></div>
    <div className="tabs">{["profile", "research", "interactions", "policies", "meetings", "score", "evidence"].map((x) => <button className={tab === x ? "active" : ""} onClick={() => setTab(x)} key={x}>{titleCase(x)}</button>)}</div>
    <div className="drawer-body">
      {message && <div className="alert amber">{message}</div>}
      {tab === "profile" && <>
        {!lead.eligible && lead.exclusion_reason && <div className="alert amber"><CircleAlert size={17}/>{titleCase(lead.exclusion_reason)}</div>}
        <div className="classification-line"><Badge tone={lead.classification_status === "target" ? "green" : lead.classification_status === "excluded" ? "red" : "amber"}>{titleCase(lead.classification_status)}</Badge><span>{titleCase(lead.classification_reason)} · {Math.round(lead.classification_confidence * 100)}% · {lead.classification_policy_version}</span></div>
        <div className="profile-controls"><label>Sales stage<select value={lead.sales_stage} disabled={busy} onChange={(event) => updateStage(event.target.value)}>{["uncontacted", "attempting", "connected", "meeting_scheduled", "quote_in_progress", "won", "lost", "nurture"].map((stage) => <option value={stage} key={stage}>{titleCase(stage)}</option>)}</select></label><label>Relationship<select value={lead.relationship_status} disabled={busy} onChange={(event) => updateRelationship(event.target.value)}>{["prospect", "active_client", "former_client"].map((status) => <option value={status} key={status}>{titleCase(status)}</option>)}</select></label></div>
        {lead.sales_brief && <section className="sales-brief"><p className="eyebrow">Call preparation</p><pre>{lead.sales_brief}</pre></section>}
        <DetailSection title="Locations" count={locations.length}>{locations.map((x) => <RecordRow key={String(x.id)} title={String(x.name || lead.name)} meta={`${x.address1 ?? ""}, ${x.city ?? ""}, ${x.state ?? ""} ${x.postal_code ?? ""}`} side={x.authoritative ? "Authoritative" : `${Math.round(Number(x.confidence) * 100)}%`} />)}</DetailSection>
        <DetailSection title="Decision-makers & relationship profiles" count={people.length}>{people.map((x) => <RecordRow key={String(x.id)} title={String(x.preferred_name || x.name)} meta={`${titleCase(x.role)}${x.communication_preference ? ` · prefers ${titleCase(x.communication_preference)}` : ""}${x.relationship_notes ? ` · ${String(x.relationship_notes)}` : ""}`} side={x.is_primary_contact ? "Primary" : `${Math.round(Number(x.confidence) * 100)}%`} />)}</DetailSection>
        <form className="activity-form" onSubmit={addPerson}><div className="detail-title"><h3>Add relationship profile</h3></div><p className="section-note">Relationship fields are manual CRM data. Never add home addresses, sensitive identifiers, or unverified personal contact methods.</p><div className="coverage-grid"><label>Full professional name<input name="name" required/></label><label>Role<input name="role"/></label><label>Preferred name<input name="preferred_name"/></label><label>Communication preference<select name="communication_preference" defaultValue=""><option value="">Unknown</option>{["email", "phone", "meeting", "contact_form"].map((value) => <option value={value} key={value}>{titleCase(value)}</option>)}</select></label><label>Timezone<input name="timezone" defaultValue="America/New_York"/></label><label>Tags, comma-separated<input name="tags"/></label><label className="wide">Relationship notes<textarea name="relationship_notes" rows={2}/></label><label className="checkbox-label wide"><input name="is_primary_contact" type="checkbox"/>Primary contact</label></div><button className="button" disabled={busy}>Add contact profile</button></form>
        <DetailSection title="Ownership evidence" count={ownershipRelationships.length}>{ownershipRelationships.map((x) => <RecordRow key={String(x.id)} title={`${String(x.subject_name)} ${titleCase(x.relationship_type)} ${String(x.object_name)}`} meta={titleCase(x.verification_status)} side={`${Math.round(Number(x.confidence) * 100)}%`} />)}</DetailSection>
        <DetailSection title="Services and exposures" count={services.length + exposures.length}>{services.map((x) => <RecordRow key={String(x.id)} title={String(x.name)} meta={titleCase(x.category)} side={titleCase(x.verification_status)} />)}{exposures.map((x) => <RecordRow key={String(x.id)} title={titleCase(x.kind)} meta={String(x.basis)} side={titleCase(x.verification_status)} />)}</DetailSection>
        <DetailSection title="Business contact paths" count={contacts.length}>{contacts.map((x) => <RecordRow key={String(x.id)} title={String(x.value)} meta={`${titleCase(x.kind)} · ${titleCase(x.scope)}`} side={titleCase(x.verification_status)} />)}</DetailSection>
        <DetailSection title="Licenses and coverage" count={permits.length + coverages.length}>
          {permits.map((x) => <RecordRow key={String(x.id)} title={titleCase(x.kind)} meta={`Expires ${fmtDate(x.expires_on)}`} side={titleCase(x.status)} />)}
          {coverages.map((x) => <RecordRow key={String(x.id)} title={`${titleCase(x.type)} · ${x.carrier || "carrier unknown"}`} meta={`${fmtDate(x.effective_on)} – ${fmtDate(x.expires_on)}`} side={titleCase(x.confidence)} />)}
        </DetailSection>
        {!showCoverageForm ? <button className="button coverage-toggle" onClick={() => setShowCoverageForm(true)}>Add manual workers’ comp evidence</button> : <form className="coverage-form" onSubmit={addCoverage}>
          <div className="detail-title"><h3>Manual coverage lookup</h3><button type="button" className="icon-button" onClick={() => setShowCoverageForm(false)}><X size={15}/></button></div>
          <p className="section-note">Enter only fields explicitly returned by the state portal. License dates are not insurance X-dates.</p>
          <div className="coverage-grid">
            <label>State portal<select name="source_id" defaultValue={`${(lead.states[0] || "NC").toLowerCase()}_workers_comp`}><option value="nc_workers_comp">North Carolina IC</option><option value="sc_workers_comp">South Carolina WCC</option><option value="va_workers_comp">Virginia WCC</option></select></label>
            <label>Confidence<select name="confidence" defaultValue="exact"><option value="exact">Exact portal result</option><option value="strong">Strong</option><option value="weak">Weak</option><option value="unknown">Unknown</option></select></label>
            <label>Carrier<input name="carrier" /></label><label>Policy identifier<input name="policy_identifier" autoComplete="off" /></label>
            <label>Effective date<input name="effective_on" type="date" /></label><label>Expiration date<input name="expires_on" type="date" /></label>
            <label>Coverage as of<input name="coverage_as_of" type="date" /></label><label>Portal record ID<input name="source_record_id" required /></label>
            <label className="wide">Source URL<input name="source_url" type="url" /></label><label className="wide">Short evidence excerpt<textarea name="evidence_excerpt" rows={2}/></label>
          </div><div className="coverage-actions"><button type="button" className="button" onClick={() => setShowCoverageForm(false)}>Cancel</button><button className="button primary" disabled={busy}>Save coverage evidence</button></div>
        </form>}
        <DetailSection title="Business triggers & risk flags" count={triggers.length}>{triggers.map((x) => <RecordRow key={String(x.id)} title={String(x.label)} meta={`${titleCase(x.kind)} · ${fmtDate(x.date)}`} side={x.risk_review_only ? "Risk review" : "Timing"} />)}</DetailSection>
        <DetailSection title="Structured business events" count={businessEvents.length}>{businessEvents.map((x) => <RecordRow key={String(x.id)} title={String(x.label)} meta={`${titleCase(x.kind)} · ${fmtDate(x.date)}`} side={titleCase(x.verification_status)} />)}</DetailSection>
      </>}
      {tab === "research" && <>
        <div className="research-summary"><div><span>Research completeness</span><strong>{lead.research_completeness}%</strong></div><progress max={100} value={lead.research_completeness}/></div>
        {lead.research_assessment && <section className="assessment-grid">{Object.entries(lead.research_assessment.dimensions).map(([dimension, result]) => <article key={dimension}><span className={`status-dot status-${result.status === "found" ? "completed" : result.status === "conflict" ? "failed" : result.status === "in_progress" ? "running" : "partial"}`}/><div><strong>{titleCase(dimension)}</strong><small>{titleCase(result.status)} · {result.reason}</small></div></article>)}</section>}
        {lead.readiness_blockers.length > 0 && <div className="gap-list">{lead.readiness_blockers.map((blocker) => <Badge tone="amber" key={blocker}>{titleCase(blocker)}</Badge>)}</div>}
        {lead.review_status !== "needs_research" ? <div className="alert amber">Mark this lead Needs research to unlock automation.</div> : researchActive ? <div className="callout wide"><RefreshCw className="spin" size={16}/>Research is running. This view refreshes automatically.</div> : <div className="research-actions"><button className="button primary" disabled={busy} onClick={startResearch}><Search size={16}/>Run free research</button><div className="ai-action"><label>AI ceiling (cents)<input type="number" min={1} value={researchBudget} onChange={(event) => setResearchBudget(Number(event.target.value))}/></label><button className="button" disabled={busy || researchBudget <= 0} onClick={startAiAnalysis}>Run AI analysis</button></div></div>}
        <p className="section-note">Free research uses approved public data and first-party pages only. AI is a separate paid API feature; ChatGPT subscriptions do not include API usage.</p>
        <form className="website-candidate-form" onSubmit={addWebsiteCandidate}><label>Candidate website<input name="url" type="url" placeholder="https://example.com" required/></label><label>Why it may match<input name="notes" placeholder="Same business name and NC address"/></label><button className="button small" disabled={busy}>Add candidate</button></form>
        {!latestResearch ? <Empty title="No research runs" detail="Launch research after identifying this account as needing more evidence."/> : <>
          <section className="research-run-head"><div><strong>{titleCase(latestResearch.mode)}</strong><span>{fmtDate(latestResearch.created_at)} · authorized {latestResearch.budget_cents}¢ · calculated {fmtMicroUsd(latestResearch.calculated_cost_microusd)}</span></div><Badge tone={latestResearch.status === "completed" ? "green" : latestResearch.status === "partial" ? "amber" : "blue"}>{titleCase(latestResearch.status)}</Badge></section>
          {latestResearch.summary?.gaps?.length ? <div className="gap-list">{latestResearch.summary.gaps.map((gap) => <Badge key={gap}>{titleCase(gap)}</Badge>)}</div> : null}
          <div className="research-steps">{latestResearch.steps.map((step) => <article key={step.id}><StatusDot status={step.status}/><div><strong>{titleCase(step.kind)}</strong><span>{step.error || JSON.stringify(step.summary)}</span></div>{["failed", "partial"].includes(step.status) && <button className="button small" disabled={busy} onClick={() => retryStep(latestResearch.id, step.kind)}>Retry</button>}</article>)}</div>
          {latestResearch.status === "awaiting_paid_approval" && <div className="paid-approval"><p>Free research is complete. Approve an explicit ceiling to run cited AI research.</p><label>Maximum cents<input type="number" min={1} value={researchBudget} onChange={(event) => setResearchBudget(Number(event.target.value))}/></label><button className="button" disabled={busy || researchBudget <= 0} onClick={() => approvePaid(latestResearch.id)}>Approve paid steps</button></div>}
          <DetailSection title="Research findings" count={latestResearch.findings.length}>{latestResearch.findings.map((finding) => <article className="evidence-card" key={finding.id}><div><Badge tone={finding.status === "accepted" ? "green" : finding.status === "rejected" ? "red" : "amber"}>{titleCase(finding.status)}</Badge><span>{Math.round(finding.confidence * 100)}%</span></div><strong>{titleCase(finding.field)}</strong><code>{JSON.stringify(finding.value)}</code>{finding.excerpt && <p>{finding.excerpt}</p>}{safeHref(finding.source_url) && <a href={safeHref(finding.source_url)} target="_blank" rel="noreferrer">Open cited source</a>}{finding.status === "proposed" && <div className="finding-actions"><button className="button small danger" disabled={busy} onClick={() => decideFinding(finding.id, "reject")}>Reject</button><button className="button small primary" disabled={busy} onClick={() => decideFinding(finding.id, "accept")}>Accept</button></div>}</article>)}</DetailSection>
        </>}
      </>}
      {tab === "score" && <>
        <p className="section-note">The rules score ranks sales priority. It is not a predicted likelihood to buy.</p>
        {contributions.length ? <div className="score-list">{contributions.map((x, index) => <div className="score-factor" key={`${x.category}-${x.factor}-${index}`}><div><Badge>{titleCase(x.category)}</Badge><strong>{titleCase(x.factor)}</strong><span>{String(x.explanation)}</span></div><b>+{String(x.points)}<small> / {String(x.max_points)}</small></b></div>)}</div> : <Empty title="No score contribution snapshot" detail="Rescore the account after adding evidence." />}
      </>}
      {tab === "evidence" && <>
        <p className="section-note">Assertions remain source-specific. Conflicts are visible and never silently overwritten.</p>
        {Boolean(lead.google_place_id) && <div className="live-validation"><div><strong>Transient Google validation</strong><span>Requested live, shown with attribution, and never written to the lead record.</span></div><button className="button small" disabled={busy} onClick={validateGoogle}>Validate live</button></div>}
        {googleView && <article className="google-card"><Badge tone="blue">Google Maps</Badge><strong>{String(googleView.display_name || "No live display name")}</strong><span>{String(googleView.formatted_address || "Address unavailable")} · {titleCase(googleView.business_status)}</span>{safeHref(googleView.google_maps_uri) && <a href={safeHref(googleView.google_maps_uri)} target="_blank" rel="noreferrer">Open in Google Maps</a>}<small>Transient response · validated {fmtDate(googleView.validated_at)}</small></article>}
        {evidence.length ? evidence.map((x) => <article className="evidence-card" key={String(x.id)}><div><Badge tone={x.conflict ? "amber" : "neutral"}>{String(x.source_id)}</Badge><span>{fmtDate(x.retrieved_at)}</span></div><strong>{titleCase(x.field)}</strong><code>{JSON.stringify(x.value)}</code>{Boolean(x.excerpt) && <p>{String(x.excerpt)}</p>}<small>{Math.round(Number(x.confidence) * 100)}% confidence · {String(x.authority)} authority · hash {String(x.content_hash).slice(0, 10)}</small></article>) : <Empty title="No assertions" detail="Enrich this account from a permitted source." />}
      </>}
      {tab === "interactions" && <>
        <label>Sales stage<select value={lead.sales_stage} disabled={busy} onChange={(event) => updateStage(event.target.value)}>{["uncontacted", "attempting", "connected", "meeting_scheduled", "quote_in_progress", "won", "lost", "nurture"].map((stage) => <option value={stage} key={stage}>{titleCase(stage)}</option>)}</select></label>
        <form className="activity-form" onSubmit={addActivity}><div className="detail-title"><h3>Log activity</h3></div><div className="coverage-grid"><label>Type<select name="kind" defaultValue="call"><option value="call">Call</option><option value="email">Email</option><option value="meeting">Meeting</option><option value="note">Note</option></select></label><label>Disposition<select name="disposition" defaultValue=""><option value="">None</option>{["no_answer", "voicemail", "gatekeeper", "wrong_number", "connected", "follow_up", "do_not_contact"].map((item) => <option value={item} key={item}>{titleCase(item)}</option>)}</select></label><label className="wide">Notes<textarea name="notes" rows={2}/></label></div><button className="button primary" disabled={busy}>Save activity</button></form>
        <DetailSection title="Activity history" count={activities.length}>{activities.map((item) => <RecordRow key={String(item.id)} title={titleCase(item.kind)} meta={`${fmtDate(item.occurred_at)} · ${item.notes || "No notes"}`} side={titleCase(item.disposition)} />)}</DetailSection>
        <form className="activity-form" onSubmit={addTask}><div className="detail-title"><h3>Schedule next action</h3></div><div className="coverage-grid"><label>Type<select name="kind" defaultValue="call"><option value="call">Call</option><option value="email">Email</option><option value="meeting">Meeting</option><option value="research">Research</option><option value="other">Other</option></select></label><label>Due<input name="due_at" type="datetime-local" required/></label><label className="wide">Notes<input name="notes"/></label></div><button className="button primary" disabled={busy}>Schedule</button></form>
        <DetailSection title="Tasks" count={tasks.length}>{tasks.map((item) => <div className="record-row" key={String(item.id)}><div><strong>{titleCase(item.kind)}</strong><span>{fmtDate(item.due_at)} · {String(item.notes || "No notes")}</span></div>{item.status === "open" ? <button className="button small" disabled={busy} onClick={() => completeTask(String(item.id))}>Complete</button> : <Badge>{titleCase(item.status)}</Badge>}</div>)}</DetailSection>
      </>}
      {tab === "policies" && <>
        <p className="section-note">Policy information is append-only. Corrections and customer updates create new snapshots; identifiers are HMAC-hashed and displayed only in masked form.</p>
        <form className="activity-form" onSubmit={addPolicy}>
          <div className="detail-title"><h3>Add policy snapshot</h3></div>
          <div className="coverage-grid">
            <label>Line of business<input name="coverage_type" placeholder="general_liability" required/></label>
            <label>Carrier<input name="carrier"/></label>
            <label>Policy status<select name="policy_status" defaultValue="unknown">{["unknown", "active", "expiring", "expired", "cancelled", "quoted"].map((value) => <option value={value} key={value}>{titleCase(value)}</option>)}</select></label>
            <label>Renewal status<select name="renewal_status" defaultValue="unknown">{["unknown", "not_contacted", "reviewing", "quoted", "bound", "lost"].map((value) => <option value={value} key={value}>{titleCase(value)}</option>)}</select></label>
            <label>Source<select name="source_kind" defaultValue="producer_entered"><option value="producer_entered">Producer entered</option><option value="customer_reported">Customer reported</option></select></label>
            <label>Confidence<select name="confidence" defaultValue="unknown">{["unknown", "exact", "strong", "weak"].map((value) => <option value={value} key={value}>{titleCase(value)}</option>)}</select></label>
            <label>Effective date<input name="effective_on" type="date"/></label>
            <label>Expiration date<input name="expires_on" type="date"/></label>
            <label>Observed date<input name="observed_on" type="date" defaultValue={new Date().toISOString().slice(0, 10)} required/></label>
            <label>Annual premium<input name="annual_premium" type="number" min={0} step="0.01"/></label>
            <label className="wide">Policy identifier<input name="policy_identifier" autoComplete="off"/></label>
            <label className="wide">Notes<textarea name="notes" rows={2}/></label>
          </div>
          <button className="button primary" disabled={busy}>Save snapshot</button>
        </form>
        <div className="policy-list">{coverages.length ? coverages.map((policy) => <article className={`policy-card ${policy.current ? "current" : "historical"}`} key={String(policy.id)}><div><Badge tone={policy.current ? "green" : "neutral"}>{policy.current ? "Current" : "Historical"}</Badge><span>{titleCase(policy.source_kind)}</span></div><h3>{titleCase(policy.type)} · {String(policy.carrier || "Carrier unknown")}</h3><p>{String(policy.policy_masked || "No policy identifier")} · {fmtDate(policy.effective_on)} – {fmtDate(policy.expires_on)}</p><div className="queue-badges"><Badge>{titleCase(policy.policy_status)}</Badge><Badge>{titleCase(policy.renewal_status)}</Badge></div>{Boolean(policy.notes) && <small>{String(policy.notes)}</small>}</article>) : <Empty title="No policy snapshots" detail="Add customer-reported or producer-entered insurance status without overwriting research evidence."/>}</div>
      </>}
      {tab === "meetings" && <>
        {!lead.contact_ready && <div className="alert amber"><CircleAlert size={16}/><div><strong>Scheduling is gated by research readiness.</strong><span>{lead.readiness_blockers.length ? ` Blockers: ${lead.readiness_blockers.map(titleCase).join(", ")}.` : " Run a current research assessment first."} An audited override requires a reason.</span></div></div>}
        <form className="activity-form" onSubmit={addMeeting}>
          <div className="detail-title"><h3>Schedule meeting</h3></div>
          <div className="coverage-grid">
            <label className="wide">Title<input name="title" defaultValue={`Introduction · ${lead.name}`} required/></label>
            <label>Start<input name="start_at" type="datetime-local" required/></label><label>End<input name="end_at" type="datetime-local" required/></label>
            <label>Timezone<input name="timezone" defaultValue="America/New_York" required/></label><label>Location<input name="location"/></label>
            <label>Person<select name="person_role_id" defaultValue=""><option value="">No linked person</option>{people.map((person) => <option value={String(person.id)} key={String(person.id)}>{String(person.preferred_name || person.name)}</option>)}</select></label>
            <label>Attendee email<input name="attendee_email" type="email"/></label>
            <label>Reminder minutes<input name="reminder_minutes" type="number" min={0} defaultValue={30}/></label>
            <label className="checkbox-label"><input name="create_meet" type="checkbox"/>Create unique Meet link</label>
            <label className="checkbox-label"><input name="send_updates" type="checkbox"/>Send attendee invitations</label>
            <label className="wide">Private preparation notes<textarea name="private_prep_notes" rows={3}/></label>
            {!lead.contact_ready && <label className="wide">Required override reason<textarea name="readiness_override_reason" minLength={5} required rows={2}/></label>}
          </div>
          <button className="button primary" disabled={busy}><CalendarDays size={16}/>Save and sync meeting</button>
        </form>
        <div className="meeting-list">{meetings.length ? meetings.map((meeting) => <article className="meeting-card" key={meeting.id}><div><Badge tone={meeting.status === "cancelled" ? "red" : meeting.sync_status === "synced" ? "green" : "amber"}>{titleCase(meeting.sync_status)}</Badge><span>{titleCase(meeting.status)}</span></div><h3>{meeting.title}</h3><p>{new Date(meeting.start_at).toLocaleString()} – {new Date(meeting.end_at).toLocaleTimeString()} · {meeting.timezone}</p>{meeting.location && <small>{meeting.location}</small>}{meeting.private_prep_notes && <section><strong>Private preparation</strong><p>{meeting.private_prep_notes}</p></section>}{meeting.sync_error && <div className="alert">{meeting.sync_error}</div>}<div className="meeting-actions">{meeting.google_html_link && <a className="button small" href={meeting.google_html_link} target="_blank" rel="noreferrer">Open Google event</a>}{meeting.google_meet_link && <a className="button small" href={meeting.google_meet_link} target="_blank" rel="noreferrer">Join Meet</a>}{meeting.status !== "cancelled" && <><button className="button small" disabled={busy} onClick={() => syncMeeting(meeting.id)}>Sync</button><button className="button small danger" disabled={busy} onClick={() => cancelMeeting(meeting.id)}>Cancel</button></>}</div></article>) : <Empty title="No scheduled meetings" detail="A contact-ready lead can create one idempotent Google event from here."/>}</div>
      </>}
    </div>
    <div className="drawer-actions">{lead.review_status === "needs_research" ? <button className="button" disabled={busy} onClick={() => researchActive ? setTab("research") : startResearch()}><Search size={16}/>{researchActive ? "View research" : "Free research"}</button> : <button className="button" disabled={busy} onClick={() => decide("needs_research")}>Needs research</button>}<button className="button danger" disabled={busy} onClick={() => decide("rejected")}>Reject</button><button className="button primary" disabled={busy} onClick={() => decide("approved")}><Check size={16}/>Approve</button></div>
  </aside>;
}

function DetailSection({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return <section className="detail-section"><div className="detail-title"><h3>{title}</h3><Badge>{count}</Badge></div>{count ? children : <p className="muted">No current evidence.</p>}</section>;
}

function RecordRow({ title, meta, side }: { title: string; meta: string; side: string }) {
  return <div className="record-row"><div><strong>{title}</strong><span>{meta}</span></div><small>{side}</small></div>;
}

function LeadsPage() {
  const [items, setItems] = useState<Lead[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<LeadFilters>({ q: "", state: "", vertical: "", tier: "", review: "", eligible: "", sales: "" });
  const query = useMemo(() => {
    const p = new URLSearchParams({ limit: "200" });
    if (filters.q) p.set("q", filters.q);
    if (filters.state) p.set("state", filters.state);
    if (filters.vertical) p.set("vertical", filters.vertical);
    if (filters.tier) p.set("tier", filters.tier);
    if (filters.review) p.set("review_status", filters.review);
    if (filters.eligible) p.set("eligible", filters.eligible);
    if (filters.sales) p.set("sales_stage", filters.sales);
    return p.toString();
  }, [filters]);
  const load = useCallback(() => { setLoading(true); api<{ items: Lead[] }>(`/leads?${query}`).then((x) => setItems(x.items)).finally(() => setLoading(false)); }, [query]);
  useEffect(() => { const timer = setTimeout(load, 180); return () => clearTimeout(timer); }, [load]);
  return <>
    <div className="page-head"><div><p className="eyebrow">Human review queue</p><h1>Commercial lead accounts</h1><p>Eligibility is applied before ranking. Open an account to audit every material claim.</p></div><Badge tone="blue">{items.length} shown</Badge></div>
    <section className="filter-bar">
      <label className="search-input"><Search size={16}/><input placeholder="Business, domain…" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })}/></label>
      <Select value={filters.state} onChange={(x) => setFilters({ ...filters, state: x })} options={["NC", "SC", "VA"]} placeholder="All states" />
      <Select value={filters.vertical} onChange={(x) => setFilters({ ...filters, vertical: x })} options={["hospitality_alcohol_events", "fitness_recreation", "contractors_trades", "auto_services"]} placeholder="All verticals" />
      <Select value={filters.tier} onChange={(x) => setFilters({ ...filters, tier: x })} options={["A", "B", "C", "HOLD"]} placeholder="All tiers" />
      <Select value={filters.review} onChange={(x) => setFilters({ ...filters, review: x })} options={["new", "needs_research", "approved", "rejected", "suppressed"]} placeholder="All reviews" />
      <Select value={filters.sales} onChange={(x) => setFilters({ ...filters, sales: x })} options={["uncontacted", "attempting", "connected", "meeting_scheduled", "quote_in_progress", "won", "lost", "nurture"]} placeholder="All sales stages" />
      <Select value={filters.eligible} onChange={(x) => setFilters({ ...filters, eligible: x })} options={["true", "false"]} labels={["Qualified only", "Excluded only"]} placeholder="Any eligibility" />
    </section>
    <section className="table-panel">{loading ? <Loading /> : !items.length ? <Empty title="No leads match these filters" detail="Clear a filter or ingest another source snapshot."/> : <div className="data-table">
      <div className="table-row table-head-row"><span>Priority</span><span>Account</span><span>Footprint</span><span>Control</span><span>Sales</span><span>Research</span></div>
      {items.map((lead) => <button className="table-row" key={lead.id} onClick={() => setSelected(lead.id)}><Score value={lead.score} tier={lead.tier}/><span className="account-cell"><strong>{lead.name}</strong><small>{titleCase(lead.vertical)}{lead.website ? ` · ${lead.domain}` : ""}</small></span><span><strong>{lead.location_count_verified ?? "?"} locations</strong><small>{lead.states.join(", ") || "State unknown"}</small></span><span><Badge tone={lead.classification_status === "target" ? "green" : lead.classification_status === "excluded" ? "red" : "amber"}>{titleCase(lead.classification_status)}</Badge><small>{lead.eligible ? "Qualified" : titleCase(lead.classification_reason || lead.exclusion_reason || "Evidence gap")}</small></span><span><strong>{titleCase(lead.sales_stage)}</strong><small>{lead.next_action_at ? `Next ${fmtDate(lead.next_action_at)}` : "No follow-up"}</small></span><span><Badge tone={lead.review_status === "approved" ? "green" : "neutral"}>{titleCase(lead.review_status)}</Badge><small>{lead.research_completeness}% · {titleCase(lead.research_status || "not_started")}</small></span></button>)}
    </div>}</section>
    {selected && <><div className="drawer-backdrop" onClick={() => setSelected(null)}/><LeadDetail id={selected} onClose={() => setSelected(null)} onChanged={load}/></>}
  </>;
}

function Select({ value, onChange, options, labels, placeholder }: { value: string; onChange: (x: string) => void; options: string[]; labels?: string[]; placeholder: string }) {
  return <label className="select-wrap"><select value={value} onChange={(e) => onChange(e.target.value)}><option value="">{placeholder}</option>{options.map((x, i) => <option value={x} key={x}>{labels?.[i] || titleCase(x)}</option>)}</select></label>;
}

interface MatchRecord { id: string; score: number; reasons: string[]; left: Lead; right: Lead }

function MatchesPage() {
  const [items, setItems] = useState<MatchRecord[] | null>(null);
  const load = useCallback(() => api<MatchRecord[]>("/matches").then(setItems), []);
  useEffect(() => { load(); }, [load]);
  async function decide(id: string, decision: string) { await api(`/matches/${id}/decision`, { method: "POST", body: JSON.stringify({ decision }) }); await load(); }
  return <><div className="page-head"><div><p className="eyebrow">Identity resolution</p><h1>Match review</h1><p>Fuzzy matches only propose links. Common ownership and location totals need your judgment.</p></div></div>
    {!items ? <Loading /> : !items.length ? <Empty title="No proposed entity links" detail="New fuzzy candidates will appear after discovery and resolution jobs."/> : <div className="match-list">{items.map((x) => <article className="match-card" key={x.id}><div className="match-score"><strong>{Math.round(x.score)}%</strong><span>match score</span></div><div className="match-sides"><div><strong>{x.left.name}</strong><span>{x.left.domain || "No domain"} · {x.left.location_count_verified ?? "?"} locations</span></div><GitMerge/><div><strong>{x.right.name}</strong><span>{x.right.domain || "No domain"} · {x.right.location_count_verified ?? "?"} locations</span></div></div><div className="reason-list">{x.reasons.map((r) => <Badge key={r}>{titleCase(r)}</Badge>)}</div><div className="match-actions"><button className="button" onClick={() => decide(x.id, "split")}>Keep separate</button><button className="button danger" onClick={() => decide(x.id, "reject")}>Reject link</button><button className="button primary" onClick={() => decide(x.id, "accept")}><GitMerge size={16}/>Merge accounts</button></div></article>)}</div>}
  </>;
}

function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState("overture_places");
  const [limit, setLimit] = useState(500);
  const [states, setStates] = useState(["NC"]);
  const [targets, setTargets] = useState("");
  const [commercialEnabled, setCommercialEnabled] = useState(false);
  const [budgetCents, setBudgetCents] = useState(0);
  const [message, setMessage] = useState("");
  const load = useCallback(() => Promise.all([api<Run[]>("/runs"), api<Source[]>("/sources/health")]).then(([r, s]) => { setRuns(r); setSources(s); }), []);
  useEffect(() => { load(); }, [load]);
  async function start(event: FormEvent) {
    event.preventDefault(); setMessage("");
    const lines = targets.split("\n").map((x) => x.trim()).filter(Boolean);
    const parameters: Record<string, unknown> = {};
    let queries: string[] = [];
    if (sourceId === "google_places_ids") queries = lines;
    if (sourceId === "first_party_web") parameters.websites = lines;
    if (sourceId === "hunter") {
      parameters.domains = lines;
      if (lines.length) parameters.cost_per_domain_cents = Math.max(1, Math.floor(budgetCents / lines.length));
    }
    if (sourceId === "email_verifier") {
      parameters.emails = lines;
      if (lines.length) parameters.cost_per_email_cents = Math.max(1, Math.floor(budgetCents / lines.length));
    }
    try { await api("/runs", { method: "POST", body: JSON.stringify({ source_id: sourceId, states, limit, verticals: [], queries, parameters, commercial_enabled: commercialEnabled, budget_cents: budgetCents }) }); setMessage("Run queued."); await load(); }
    catch (err) { setMessage(err instanceof Error ? err.message : "Run could not start"); }
  }
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); setMessage("");
    try { await api("/imports/tabular", { method: "POST", body: data }); setMessage("Official file imported."); event.currentTarget.reset(); await load(); }
    catch (err) { setMessage(err instanceof Error ? err.message : "Import failed"); }
  }
  const runnable = sources.filter((x) => x.enabled && x.standalone_runnable);
  const importable = sources.filter((x) => x.enabled && x.accepts_upload);
  const selectedSource = sources.find((x) => x.id === sourceId);
  return <><div className="page-head"><div><p className="eyebrow">Durable acquisition jobs</p><h1>Runs & official imports</h1><p>Every run records scope, source version, cost ceiling, counts, and errors.</p></div><button className="icon-button" onClick={load}><RefreshCw/></button></div>
    {message && <div className="alert amber">{message}</div>}
    <section className="two-form-grid"><form className="panel form-panel" onSubmit={start}><div className="panel-head"><div><p className="eyebrow">Automated connector</p><h2>Start a scoped run</h2></div><Play size={20}/></div>
      <label>Source<select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>{runnable.map((x) => <option value={x.id} key={x.id}>{x.name}</option>)}</select></label>
      <fieldset><legend>States</legend><div className="checkbox-row">{["NC", "SC", "VA"].map((state) => <label key={state}><input type="checkbox" checked={states.includes(state)} onChange={() => setStates(states.includes(state) ? states.filter((x) => x !== state) : [...states, state])}/>{state}</label>)}</div></fieldset>
      <label>Record ceiling<input type="number" min={1} max={100000} value={limit} onChange={(e) => setLimit(Number(e.target.value))}/></label>
      {sourceId !== "overture_places" && <label>Targets, one per line<textarea rows={3} placeholder={sourceId === "hunter" ? "example.com" : sourceId === "email_verifier" ? "owner@example.com" : sourceId === "first_party_web" ? "https://example.com" : "Source-specific identifiers or URLs"} value={targets} onChange={(e) => setTargets(e.target.value)}/></label>}
      {selectedSource?.commercial && <fieldset><legend>Commercial request controls</legend><div className="commercial-controls"><label><input type="checkbox" checked={commercialEnabled} onChange={(e) => setCommercialEnabled(e.target.checked)}/>Explicitly enable this paid run</label><label>Hard ceiling (cents)<input type="number" min={1} value={budgetCents} onChange={(e) => setBudgetCents(Number(e.target.value))}/></label></div></fieldset>}
      {selectedSource && <p className="section-note">{titleCase(selectedSource.cost_class)} · {titleCase(selectedSource.policy_status)} policy{selectedSource.credential_required ? " · credential required" : ""}{selectedSource.overage_possible ? " · overage possible" : ""}</p>}<button className="button primary"><Play size={16}/>Queue source run</button>
    </form><form className="panel form-panel" onSubmit={upload}><div className="panel-head"><div><p className="eyebrow">Official snapshot</p><h2>Import CSV or XLSX</h2></div><Upload size={20}/></div>
      <label>Source<select name="source_id" required>{importable.map((x) => <option value={x.id} key={x.id}>{x.name}</option>)}</select></label>
      <label>Official file<input name="file" type="file" accept=".csv,.xlsx,.xls" required/></label>
      <p className="section-note">Files are hashed and retained under the source policy. Mapping aliases cover common official field names.</p>
      <button className="button"><Upload size={16}/>Import snapshot</button>
    </form></section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">Latest activity</p><h2>Run history</h2></div></div>{!runs.length ? <Empty title="No acquisition runs" detail="Start discovery or import an approved official file."/> : <div className="run-list">{runs.map((x) => <div className="run-row" key={x.id}><StatusDot status={x.status}/><div><strong>{x.source_name}</strong><span>{fmtDate(x.created_at)} · {x.records_seen.toLocaleString()} accepted · {x.records_created.toLocaleString()} created · {x.records_updated.toLocaleString()} updated · {(x.records_rejected || 0).toLocaleString()} rejected</span>{x.records_rejected > 0 && <small>{Object.entries(x.rejection_reasons || {}).map(([reason, count]) => `${titleCase(reason)} ${count.toLocaleString()}`).join(" · ")}</small>}</div><Badge tone={x.status === "failed" ? "red" : x.status === "completed" ? "green" : "blue"}>{titleCase(x.status)}</Badge>{x.error && <small className="danger-text">{x.error}</small>}</div>)}</div>}</section>
  </>;
}

function StatusDot({ status }: { status: string }) { return <span className={`status-dot status-${status}`}/>; }

function SourcesPage() {
  const [items, setItems] = useState<Source[] | null>(null);
  const load = useCallback(() => api<Source[]>("/sources/health").then(setItems), []);
  useEffect(() => { load(); }, [load]);
  async function toggle(item: Source) { await api(`/sources/${item.id}?enabled=${!item.enabled}`, { method: "PATCH" }); await load(); }
  const groups = useMemo(() => Object.entries((items || []).reduce<Record<string, Source[]>>((a, x) => { (a[x.jurisdiction] ||= []).push(x); return a; }, {})), [items]);
  return <><div className="page-head"><div><p className="eyebrow">Policy-aware acquisition</p><h1>Source health & controls</h1><p>Unknown terms disable automation. Manual and metered connectors never run implicitly.</p></div></div>{!items ? <Loading/> : <div className="source-groups">{groups.map(([group, sources]) => <section className="panel" key={group}><div className="panel-head"><h2>{group === "ALL" ? "Cross-jurisdiction" : group}</h2><Badge>{sources.length} sources</Badge></div><div className="source-list">{sources.map((x) => <div className="source-row" key={x.id}><div className={`source-icon ${x.last_error ? "bad" : x.policy_status !== "approved" || x.stale ? "warn" : "good"}`}>{x.last_error ? <CircleAlert/> : <Database/>}</div><div><strong>{x.name}</strong><span>{titleCase(x.acquisition_mode)} · {titleCase(x.authority)} · {titleCase(x.cost_class)}</span><small>{titleCase(x.policy_status)} policy · {x.last_error || x.notes || `Last success ${fmtDate(x.last_success_at)}`}</small></div><div className="source-state"><Badge tone={!x.enabled ? "neutral" : x.policy_status !== "approved" ? "amber" : x.last_error ? "red" : x.stale ? "amber" : "green"}>{!x.enabled ? "Disabled" : x.policy_status !== "approved" ? titleCase(x.policy_status) : x.last_error ? "Error" : x.stale ? "Stale" : "Healthy"}</Badge><button role="switch" aria-checked={x.enabled} className={`switch ${x.enabled ? "on" : ""}`} onClick={() => toggle(x)}><span/></button></div></div>)}</div></section>)}</div>}</>;
}

function ExportsPage() {
  const [items, setItems] = useState<ExportBatch[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(() => api<ExportBatch[]>("/exports").then(setItems), []);
  useEffect(() => { load(); }, [load]);
  async function create() { setBusy(true); setError(""); try { await api("/exports", { method: "POST", body: JSON.stringify({ tiers: ["A", "B", "C"], states: [], review_statuses: ["approved"], include_hold: false }) }); await load(); } catch (e) { setError(e instanceof Error ? e.message : "Export failed"); } finally { setBusy(false); } }
  return <><div className="page-head"><div><p className="eyebrow">Versioned deliverables</p><h1>Evidence-pack exports</h1><p>XLSX and equivalent UTF-8 CSVs, plus a reproducibility manifest.</p></div><button className="button primary" onClick={create} disabled={busy}><FileArchive size={17}/>{busy ? "Generating…" : "Export approved A–C leads"}</button></div>
    {error && <div className="alert"><CircleAlert size={16}/>{error}</div>}
    <div className="callout wide"><ShieldCheck size={19}/><div><strong>Professional contact boundary</strong><span>Home addresses and personal phones are suppressed. Only human-approved leads enter the default pack.</span></div></div>
    <section className="panel">{!items.length ? <Empty title="No evidence packs yet" detail="Approve reviewed leads, then generate the first versioned export."/> : <div className="export-list">{items.map((x) => <div className="export-row" key={x.id}><div className="file-icon"><FileArchive/></div><div><strong>Evidence pack · {x.lead_count} leads</strong><span>{fmtDate(x.created_at)} · {x.manifest_hash ? `manifest ${x.manifest_hash.slice(0, 12)}` : "manifest pending"}</span></div><Badge tone={x.status === "completed" ? "green" : x.status === "failed" ? "red" : "blue"}>{titleCase(x.status)}</Badge>{x.status === "completed" && <button className="button small" onClick={() => downloadExport(x.id)}><ArrowDownToLine size={15}/>Download</button>}</div>)}</div>}</section>
  </>;
}

interface Suppression { id: string; kind: string; value: string; reason: string; source: string | null; created_at: string }

function SuppressionsPage() {
  const [items, setItems] = useState<Suppression[]>([]);
  const [kind, setKind] = useState("email");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("opt_out");
  const load = useCallback(() => api<Suppression[]>("/suppressions").then(setItems), []);
  useEffect(() => { load(); }, [load]);
  async function submit(e: FormEvent) { e.preventDefault(); await api("/suppressions", { method: "POST", body: JSON.stringify({ kind, value, reason, source: "manual" }) }); setValue(""); await load(); }
  return <><div className="page-head"><div><p className="eyebrow">Durable outreach boundaries</p><h1>Suppression & do-not-contact</h1><p>Normalized opt-outs apply to every future evidence pack.</p></div></div>
    <form className="inline-form panel" onSubmit={submit}><Select value={kind} onChange={setKind} options={["email", "phone", "domain", "account"]} placeholder="Kind"/><input required placeholder="Email, phone, domain, or account ID" value={value} onChange={(e) => setValue(e.target.value)}/><input required placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)}/><button className="button primary"><ShieldCheck size={16}/>Add suppression</button></form>
    <section className="panel">{!items.length ? <Empty title="No suppression records" detail="Opt-outs and manual do-not-contact decisions will appear here."/> : <div className="simple-table">{items.map((x) => <div key={x.id}><Badge>{titleCase(x.kind)}</Badge><strong>{x.value}</strong><span>{titleCase(x.reason)}</span><small>{fmtDate(x.created_at)}</small></div>)}</div>}</section>
  </>;
}

function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [page, setPage] = useState<Page>("dashboard");
  const [sidebar, setSidebar] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    // Session lives in an HttpOnly cookie; probe the server to find out if it is valid.
    api("/auth/me")
      .then(() => setAuthenticated(true))
      .catch((e) => { setAuthenticated(false); if (!(e instanceof ApiError && e.status === 401)) setError(String(e)); });
  }, []);
  useEffect(() => {
    const handler = (event: PromiseRejectionEvent) => setError(event.reason instanceof Error ? event.reason.message : String(event.reason));
    window.addEventListener("unhandledrejection", handler); return () => window.removeEventListener("unhandledrejection", handler);
  }, []);
  if (authenticated === null) return null;
  if (!authenticated) return <Login onDone={() => setAuthenticated(true)}/>;
  const active = NAV.find((x) => x.page === page)!;
  return <div className="app-shell">
    <aside className={`sidebar ${sidebar ? "open" : ""}`}><div className="brand"><span className="brand-mark"><FishLogo /></span><div><strong>Lead Shake</strong><small>NC · SC · VA</small></div></div><nav>{NAV.map(({ page: p, label, icon: Icon }) => <button key={p} className={page === p ? "active" : ""} onClick={() => { setPage(p); setSidebar(false); }}><Icon size={18}/><span>{label}</span>{page === p && <ChevronRight size={15}/>}</button>)}</nav><div className="sidebar-foot"><div><span className="status-dot status-completed"/><small>Local private instance</small></div><button onClick={() => { void logout().finally(() => setAuthenticated(false)); }}><LogOut size={16}/>Sign out</button></div></aside>
    {sidebar && <div className="mobile-backdrop" onClick={() => setSidebar(false)}/>}<main><header className="topbar"><button className="mobile-menu" onClick={() => setSidebar(true)}><Menu/></button><div><active.icon size={17}/><span>{active.label}</span></div><div className="top-actions"><span className="environment"><span/>Local</span></div></header>{error && <div className="global-error"><CircleAlert size={16}/><span>{error}</span><button onClick={() => setError("")}><X size={15}/></button></div>}<div className="page-content">
      {page === "dashboard" && <DashboardPage openLeads={() => setPage("leads")}/>} {page === "research" && <ResearchQueuePage/>} {page === "leads" && <LeadsPage/>} {page === "matches" && <MatchesPage/>} {page === "runs" && <RunsPage/>} {page === "sources" && <SourcesPage/>} {page === "integrations" && <CalendarIntegrationPage/>} {page === "exports" && <ExportsPage/>} {page === "suppressions" && <SuppressionsPage/>}
    </div></main>
  </div>;
}

export default App;
