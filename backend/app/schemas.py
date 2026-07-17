from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class RunCreate(BaseModel):
    source_id: str
    states: list[str] = Field(default_factory=lambda: ["NC", "SC", "VA"])
    verticals: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=500, ge=1, le=100000)
    commercial_enabled: bool = False
    budget_cents: int = Field(default=0, ge=0)


class EnrichRequest(BaseModel):
    source_id: Literal["first_party_web", "google_places_ids", "hunter", "email_verifier"]
    commercial_enabled: bool = False
    budget_cents: int = Field(default=0, ge=0)
    query: str | None = None


class ReviewRequest(BaseModel):
    decision: Literal["approved", "rejected", "suppressed", "needs_research", "new"]
    notes: str | None = None


class MatchDecisionRequest(BaseModel):
    decision: Literal["accept", "reject", "split"]
    notes: str | None = None


class ExportRequest(BaseModel):
    tiers: list[str] = Field(default_factory=lambda: ["A", "B", "C"])
    states: list[str] = Field(default_factory=list)
    review_statuses: list[str] = Field(default_factory=lambda: ["approved"])
    include_hold: bool = False


class SuppressionCreate(BaseModel):
    kind: Literal["email", "phone", "domain", "account"]
    value: str
    reason: str = "opt_out"
    source: str | None = None


class OutcomeCreate(BaseModel):
    stage: Literal["contacted", "reply", "meeting", "quote", "won", "lost"]
    occurred_on: date
    reason: str | None = None
    renewal_date: date | None = None
    value: float | None = None


class ManualCoverageCreate(BaseModel):
    source_id: Literal["nc_workers_comp", "sc_workers_comp", "va_workers_comp"]
    coverage_type: str = "workers_comp"
    carrier: str | None = None
    policy_identifier: str | None = None
    effective_on: date | None = None
    expires_on: date | None = None
    coverage_as_of: date | None = None
    confidence: Literal["exact", "strong", "weak", "unknown"] = "unknown"
    source_record_id: str
    source_url: str | None = None
    evidence_excerpt: str | None = None


class GoogleValidationRequest(BaseModel):
    confirm_live_request: bool


class ResearchRunCreate(BaseModel):
    mode: Literal["free_public"] = "free_public"


class AiAnalysisRunCreate(BaseModel):
    budget_cents: int = Field(gt=0)


class FindingDecisionRequest(BaseModel):
    decision: Literal["accept", "reject"]
    notes: str | None = None


class WebsiteCandidateCreate(BaseModel):
    url: str = Field(min_length=4, max_length=2000)
    notes: str | None = None


class ClassificationRepairRequest(BaseModel):
    apply: bool = False


class SourcePolicyUpdate(BaseModel):
    policy_status: Literal["approved", "pending", "manual_only", "blocked"]
    policy_evidence_url: str | None = None
    notes: str | None = None


class PaidResearchApproval(BaseModel):
    budget_cents: int = Field(gt=0)


class SalesStageUpdate(BaseModel):
    stage: Literal[
        "uncontacted", "attempting", "connected", "meeting_scheduled",
        "quote_in_progress", "won", "lost", "nurture",
    ]
    notes: str | None = None


class SalesActivityCreate(BaseModel):
    kind: Literal["call", "email", "conversation", "meeting", "policy_review", "note", "stage_change"]
    disposition: Literal[
        "no_answer", "voicemail", "gatekeeper", "wrong_number", "connected",
        "follow_up", "do_not_contact",
    ] | None = None
    occurred_at: datetime | None = None
    notes: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    subject: str | None = Field(default=None, max_length=240)
    direction: Literal["inbound", "outbound", "internal"] = "outbound"
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    person_role_id: str | None = None
    coverage_evidence_id: str | None = None
    meeting_id: str | None = None
    outcome: str | None = Field(default=None, max_length=80)
    follow_up: "FollowUpCreate | None" = None


class FollowUpCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    kind: Literal["call", "email", "meeting", "research", "other"] = "call"
    due_at: datetime
    priority: Literal["low", "normal", "high"] = "normal"
    notes: str | None = None


class SalesActivityUpdate(BaseModel):
    subject: str | None = Field(default=None, max_length=240)
    direction: Literal["inbound", "outbound", "internal"] | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    disposition: str | None = None
    outcome: str | None = Field(default=None, max_length=80)
    occurred_at: datetime | None = None
    notes: str | None = None
    details: dict[str, Any] | None = None


class SalesTaskCreate(BaseModel):
    kind: Literal["call", "email", "meeting", "research", "other"]
    due_at: datetime
    notes: str | None = None
    title: str | None = Field(default=None, max_length=240)
    priority: Literal["low", "normal", "high"] = "normal"
    person_role_id: str | None = None
    activity_id: str | None = None
    meeting_id: str | None = None


class SalesTaskUpdate(BaseModel):
    status: Literal["open", "completed", "cancelled"] | None = None
    due_at: datetime | None = None
    notes: str | None = None
    title: str | None = Field(default=None, max_length=240)
    priority: Literal["low", "normal", "high"] | None = None


class ResearchBatchCreate(BaseModel):
    mode: Literal["free_public", "ai_analysis"] = "free_public"
    account_ids: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    approved_sources: list[str] = Field(default_factory=list)
    max_leads: int = Field(default=25, ge=1, le=500)
    total_budget_cents: int = Field(default=0, ge=0)
    per_lead_budget_cents: int = Field(default=0, ge=0)


class ReadinessOverrideCreate(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class LeadProfileUpdate(BaseModel):
    relationship_status: Literal["prospect", "active_client", "former_client"] | None = None
    best_pitch_angle: str | None = None


class PersonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=240)
    role: str | None = Field(default=None, max_length=120)
    professional_profile_url: str | None = Field(default=None, max_length=2000)
    preferred_name: str | None = Field(default=None, max_length=120)
    is_primary_contact: bool = False
    communication_preference: Literal["email", "phone", "meeting", "contact_form"] | None = None
    timezone: str | None = Field(default=None, max_length=80)
    interests: list[str] = Field(default_factory=list, max_length=30)
    tags: list[str] = Field(default_factory=list, max_length=30)
    relationship_notes: str | None = Field(default=None, max_length=5000)

    @field_validator("professional_profile_url")
    @classmethod
    def public_professional_url(cls, value: str | None) -> str | None:
        if value and not value.lower().startswith(("https://", "http://")):
            raise ValueError("Professional profiles must use a public http(s) URL")
        return value


class PersonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=240)
    role: str | None = Field(default=None, max_length=120)
    professional_profile_url: str | None = Field(default=None, max_length=2000)
    preferred_name: str | None = Field(default=None, max_length=120)
    is_primary_contact: bool | None = None
    communication_preference: Literal["email", "phone", "meeting", "contact_form"] | None = None
    timezone: str | None = Field(default=None, max_length=80)
    interests: list[str] | None = Field(default=None, max_length=30)
    tags: list[str] | None = Field(default=None, max_length=30)
    relationship_notes: str | None = Field(default=None, max_length=5000)

    @field_validator("professional_profile_url")
    @classmethod
    def public_professional_url(cls, value: str | None) -> str | None:
        return PersonCreate.public_professional_url(value)


class PolicyCreate(BaseModel):
    coverage_type: str = Field(min_length=1, max_length=80)
    carrier: str | None = Field(default=None, max_length=240)
    policy_identifier: str | None = Field(default=None, max_length=240)
    effective_on: date | None = None
    expires_on: date | None = None
    coverage_as_of: date | None = None
    confidence: Literal["exact", "strong", "weak", "unknown"] = "unknown"
    policy_status: Literal["unknown", "active", "expiring", "expired", "cancelled", "quoted"] = "unknown"
    renewal_status: Literal["unknown", "not_contacted", "reviewing", "quoted", "bound", "lost"] = "unknown"
    source_kind: Literal["research_evidence", "customer_reported", "producer_entered"] = "producer_entered"
    observed_on: date = Field(default_factory=date.today)
    annual_premium: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=5000)


class PolicySupersede(PolicyCreate):
    pass


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    person_role_id: str | None = None
    start_at: datetime
    end_at: datetime
    timezone: str = Field(default="America/New_York", max_length=80)
    location: str | None = Field(default=None, max_length=1000)
    attendees: list[dict[str, str]] = Field(default_factory=list, max_length=50)
    reminder_minutes: int = Field(default=30, ge=0, le=40320)
    create_meet: bool = False
    send_updates: bool = False
    private_prep_notes: str | None = Field(default=None, max_length=10000)
    readiness_override_reason: str | None = Field(default=None, max_length=2000)


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=1000)
    attendees: list[dict[str, str]] | None = Field(default=None, max_length=50)
    reminder_minutes: int | None = Field(default=None, ge=0, le=40320)
    create_meet: bool | None = None
    send_updates: bool | None = None
    private_prep_notes: str | None = Field(default=None, max_length=10000)
