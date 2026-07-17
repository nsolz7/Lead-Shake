export type Page = "dashboard" | "research" | "leads" | "matches" | "runs" | "sources" | "integrations" | "exports" | "suppressions";

export interface Dashboard {
  total_leads: number;
  eligible_leads: number;
  approved_leads: number;
  tier_a: number;
  proposed_matches: number;
  failed_sources: number;
  research_failures: number;
  followups_due: number;
  research_new_or_stale: number;
  contact_ready: number;
  pending_findings: number;
  blocked_research: number;
  meetings_today: number;
}

export interface Lead {
  id: string;
  name: string;
  vertical: string | null;
  classification_status: string;
  classification_reason: string | null;
  classification_policy_version: string;
  classification_confidence: number;
  naics: string | null;
  states: string[];
  location_count_verified: number | null;
  ownership_status: string;
  eligible: boolean;
  exclusion_reason: string | null;
  score: number;
  tier: string;
  review_status: string;
  website: string | null;
  domain: string | null;
  primary_phone: string | null;
  primary_email: string | null;
  timing_confidence: string;
  x_date: string | null;
  best_pitch_angle: string | null;
  next_action_date: string | null;
  evidence_count: number;
  last_verified_at: string | null;
  data_status: string;
  research_completeness: number;
  research_status: string | null;
  sales_stage: string;
  sales_brief: string | null;
  last_contact_at: string | null;
  next_action_at: string | null;
  relationship_status: string;
  research_state: string;
  research_assessed_at: string | null;
  contact_ready_at: string | null;
  contact_ready: boolean;
  readiness_blockers: string[];
  research_assessment?: ResearchAssessment | null;
  [key: string]: unknown;
}

export interface Source {
  id: string;
  name: string;
  jurisdiction: string;
  acquisition_mode: string;
  authority: string;
  enabled: boolean;
  automation_allowed: boolean;
  commercial: boolean;
  cost_class: string;
  credential_required: boolean;
  overage_possible: boolean;
  license_name: string | null;
  terms_url: string | null;
  policy_status: string;
  accepts_upload: boolean;
  standalone_runnable: boolean;
  stale: boolean;
  last_success_at: string | null;
  last_error: string | null;
  notes: string | null;
}

export interface Run {
  id: string;
  source_id: string;
  source_name: string;
  status: string;
  scope: Record<string, unknown>;
  budget_cents: number;
  spent_cents: number;
  records_seen: number;
  records_created: number;
  records_updated: number;
  records_rejected: number;
  rejection_reasons: Record<string, number>;
  created_at: string;
  error: string | null;
}

export interface ResearchStep {
  id: string;
  kind: string;
  status: string;
  spent_cents: number;
  calculated_cost_microusd: number;
  provider_usage: Record<string, unknown>;
  summary: Record<string, unknown>;
  error: string | null;
}

export interface ResearchFinding {
  id: string;
  field: string;
  value: unknown;
  source_url: string | null;
  excerpt: string | null;
  confidence: number;
  status: string;
  decided_at: string | null;
  materialized_type: string | null;
}

export interface ResearchRun {
  id: string;
  mode: string;
  status: string;
  budget_cents: number;
  spent_cents: number;
  calculated_cost_microusd: number;
  calculated_cost_usd: number;
  provider_usage: Record<string, unknown>;
  rate_card_id: string | null;
  summary: { completeness?: number; gaps?: string[] };
  steps: ResearchStep[];
  findings: ResearchFinding[];
  created_at: string;
}

export interface ResearchDimension {
  status: "not_started" | "in_progress" | "found" | "attempted_no_evidence" | "stale" | "conflict";
  reason: string;
  evidence_ids: string[];
}

export interface ResearchAssessment {
  id: string;
  rubric_version: string;
  completeness: number;
  ready: boolean;
  dimensions: Record<string, ResearchDimension>;
  blockers: string[];
  assessed_at: string;
}

export interface ResearchBatch {
  id: string;
  mode: string;
  status: string;
  account_ids: string[];
  approved_sources: string[];
  max_leads: number;
  total_budget_cents: number;
  per_lead_budget_cents: number;
  spent_cents: number;
  runs: string[];
  created_at: string;
  error: string | null;
}

export interface Meeting {
  id: string;
  title: string;
  start_at: string;
  end_at: string;
  timezone: string;
  location: string | null;
  attendees: Array<{ email?: string; name?: string; response_status?: string }>;
  status: string;
  sync_status: string;
  google_html_link: string | null;
  google_meet_link: string | null;
  private_prep_notes: string | null;
  sync_error: string | null;
}

export interface CalendarStatus {
  configured: boolean;
  connected: boolean;
  status: string;
  calendar_id: string;
  scopes?: string[];
  connected_at?: string;
  last_synced_at?: string;
  last_error?: string | null;
}

export interface ExportBatch {
  id: string;
  status: string;
  lead_count: number;
  manifest_hash: string | null;
  created_at?: string;
  download_url?: string;
  error?: string | null;
}
