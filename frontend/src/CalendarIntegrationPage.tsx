import { useCallback, useEffect, useState } from "react";
import { CalendarDays, CircleAlert, RefreshCw, Unplug } from "lucide-react";
import { api } from "./api";
import type { CalendarStatus } from "./types";

export function CalendarIntegrationPage() {
  const [status, setStatus] = useState<CalendarStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(() => api<CalendarStatus>("/integrations/google-calendar/status").then(setStatus), []);
  useEffect(() => { void load(); }, [load]);

  async function connect() {
    setBusy(true); setMessage("");
    try {
      const result = await api<{ authorization_url: string }>("/integrations/google-calendar/connect", { method: "POST" });
      window.location.assign(result.authorization_url);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Calendar connection could not start"); setBusy(false); }
  }

  async function sync() {
    setBusy(true); setMessage("");
    try { const result = await api<{ updated: number }>("/integrations/google-calendar/sync", { method: "POST" }); setMessage(`${result.updated} managed event(s) updated.`); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Calendar synchronization failed"); }
    finally { setBusy(false); }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect Google Calendar and remove the stored refresh token?")) return;
    setBusy(true);
    try { await api("/integrations/google-calendar", { method: "DELETE" }); setMessage("Calendar disconnected."); await load(); }
    finally { setBusy(false); }
  }

  if (!status) return <div className="loading"><RefreshCw className="spin" size={18}/>Loading calendar status…</div>;
  return <>
    <div className="page-head"><div><p className="eyebrow">Split-authority scheduling</p><h1>Google Calendar</h1><p>Google owns schedule and responses; private research, policy context, and preparation notes stay here.</p></div></div>
    {message && <div className="alert amber">{message}</div>}
    <section className="integration-card panel">
      <div className="calendar-logo"><CalendarDays size={28}/></div>
      <div><h2>Google Calendar connection</h2><p>{status.connected ? `Connected to ${status.calendar_id}` : status.configured ? "OAuth is configured and ready to connect." : "Calendar is disabled until OAuth and token-encryption settings are valid."}</p><div className="inline-badges"><span className={`badge ${status.connected ? "badge-green" : status.configured ? "badge-amber" : "badge-neutral"}`}>{status.connected ? "Connected" : status.configured ? "Not connected" : "Not configured"}</span>{status.last_synced_at && <span className="badge badge-neutral">Last sync {new Date(status.last_synced_at).toLocaleString()}</span>}</div></div>
      <div className="integration-actions">{!status.connected ? <button className="button primary" disabled={busy || !status.configured} onClick={connect}><CalendarDays size={16}/>Connect Google</button> : <><button className="button" disabled={busy} onClick={sync}><RefreshCw size={16}/>Sync now</button><button className="button danger" disabled={busy} onClick={disconnect}><Unplug size={16}/>Disconnect</button></>}</div>
      {status.last_error && <div className="alert"><CircleAlert size={16}/>{status.last_error}</div>}
    </section>
    <section className="split-grid calendar-boundaries"><article className="panel"><div className="panel-head"><h2>Copied to Google</h2></div><ul><li>Meeting title, time, timezone, and location</li><li>Explicitly selected attendees and reminders</li><li>Optional unique Google Meet conference</li></ul></article><article className="panel"><div className="panel-head"><h2>Always private here</h2></div><ul><li>Research brief and readiness blockers</li><li>Policy and renewal context</li><li>Preparation and relationship notes</li></ul></article></section>
  </>;
}
