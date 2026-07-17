from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SourceSpec(Base, TimestampMixin):
    __tablename__ = "source_specs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(8), nullable=False, default="US")
    acquisition_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[str] = mapped_column(String(24), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    connector_key: Mapped[str | None] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    automation_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    commercial: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_class: Mapped[str] = mapped_column(String(24), default="open", index=True)
    credential_required: Mapped[bool] = mapped_column(Boolean, default=False)
    overage_possible: Mapped[bool] = mapped_column(Boolean, default=False)
    license_name: Mapped[str | None] = mapped_column(String(120))
    terms_url: Mapped[str | None] = mapped_column(Text)
    policy_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    policy_evidence_url: Mapped[str | None] = mapped_column(Text)
    policy_reviewed_by: Mapped[str | None] = mapped_column(String(120))
    allowed_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    retention_policy: Mapped[str] = mapped_column(String(80), default="assertions_and_source_metadata")
    attribution: Mapped[str | None] = mapped_column(Text)
    requests_per_minute: Mapped[int | None] = mapped_column(Integer)
    default_cost_cap_cents: Mapped[int] = mapped_column(Integer, default=0)
    terms_reviewed_at: Mapped[date | None] = mapped_column(Date)
    freshness_days: Mapped[int] = mapped_column(Integer, default=90)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class SourceRun(Base, TimestampMixin):
    __tablename__ = "source_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_specs.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rejection_reasons: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    source: Mapped[SourceSpec] = relationship()


class AccountGroup(Base, TimestampMixin):
    __tablename__ = "account_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    vertical: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    classification_status: Mapped[str] = mapped_column(String(24), default="review_required", index=True)
    classification_reason: Mapped[str | None] = mapped_column(String(240))
    classification_policy_version: Mapped[str] = mapped_column(String(32), default="vertical-policy-v2")
    classification_confidence: Mapped[float] = mapped_column(Float, default=0.5)
    naics: Mapped[str | None] = mapped_column(String(12))
    operating_status: Mapped[str] = mapped_column(String(24), default="active")
    ownership_status: Mapped[str] = mapped_column(String(24), default="unknown", index=True)
    corporate_control_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    franchise_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    pe_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    public_company_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    location_count_verified: Mapped[int | None] = mapped_column(Integer)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    exclusion_reason: Mapped[str | None] = mapped_column(String(240))
    website: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(240), index=True)
    primary_phone: Mapped[str | None] = mapped_column(String(40), index=True)
    primary_email: Mapped[str | None] = mapped_column(String(320))
    google_place_id: Mapped[str | None] = mapped_column(String(300))
    timing_confidence: Mapped[str] = mapped_column(String(32), default="unknown")
    x_date: Mapped[date | None] = mapped_column(Date)
    x_date_kind: Mapped[str | None] = mapped_column(String(40))
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    tier: Mapped[str] = mapped_column(String(12), default="HOLD", index=True)
    score_version: Mapped[str] = mapped_column(String(24), default="rules-v1")
    propensity_probability: Mapped[float | None] = mapped_column(Float)
    best_pitch_angle: Mapped[str | None] = mapped_column(Text)
    next_action_date: Mapped[date | None] = mapped_column(Date)
    review_status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    data_status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    research_completeness: Mapped[int] = mapped_column(Integer, default=0)
    research_state: Mapped[str] = mapped_column(String(24), default="not_started", index=True)
    research_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    contact_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    relationship_status: Mapped[str] = mapped_column(String(24), default="prospect", index=True)
    sales_stage: Mapped[str] = mapped_column(String(32), default="uncontacted", index=True)
    sales_brief: Mapped[str | None] = mapped_column(Text)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    brands: Mapped[list[Brand]] = relationship(back_populates="account", cascade="all, delete-orphan")
    locations: Mapped[list[Location]] = relationship(back_populates="account", cascade="all, delete-orphan")
    legal_entities: Mapped[list[LegalEntity]] = relationship(back_populates="account", cascade="all, delete-orphan")
    people: Mapped[list[PersonRole]] = relationship(back_populates="account", cascade="all, delete-orphan")
    contacts: Mapped[list[ContactPoint]] = relationship(back_populates="account", cascade="all, delete-orphan")
    permits: Mapped[list[PermitLicense]] = relationship(back_populates="account", cascade="all, delete-orphan")
    coverages: Mapped[list[CoverageEvidence]] = relationship(back_populates="account", cascade="all, delete-orphan")
    triggers: Mapped[list[Trigger]] = relationship(back_populates="account", cascade="all, delete-orphan")
    assertions: Mapped[list[FieldAssertion]] = relationship(back_populates="account", cascade="all, delete-orphan")
    score_contributions: Mapped[list[ScoreContribution]] = relationship(back_populates="account", cascade="all, delete-orphan")
    research_runs: Mapped[list[ResearchRun]] = relationship(back_populates="account", cascade="all, delete-orphan")
    sales_activities: Mapped[list[SalesActivity]] = relationship(back_populates="account", cascade="all, delete-orphan")
    sales_tasks: Mapped[list[SalesTask]] = relationship(back_populates="account", cascade="all, delete-orphan")
    services: Mapped[list[ServiceOffering]] = relationship(back_populates="account", cascade="all, delete-orphan")
    exposures: Mapped[list[ExposureEvidence]] = relationship(back_populates="account", cascade="all, delete-orphan")
    ownership_relationships: Mapped[list[OwnershipRelationship]] = relationship(back_populates="account", cascade="all, delete-orphan")
    business_events: Mapped[list[BusinessEvent]] = relationship(back_populates="account", cascade="all, delete-orphan")
    research_assessments: Mapped[list[ResearchAssessment]] = relationship(back_populates="account", cascade="all, delete-orphan")
    readiness_decisions: Mapped[list[ReadinessDecision]] = relationship(back_populates="account", cascade="all, delete-orphan")
    crawl_pages: Mapped[list[CrawlPage]] = relationship(back_populates="account", cascade="all, delete-orphan")
    meetings: Mapped[list[Meeting]] = relationship(back_populates="account", cascade="all, delete-orphan")


Index("ix_account_name_domain", AccountGroup.normalized_name, AccountGroup.domain)


class Brand(Base, TimestampMixin):
    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("account_id", "normalized_name", name="uq_brand_account_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(240))
    account: Mapped[AccountGroup] = relationship(back_populates="brands")


class Location(Base, TimestampMixin):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("account_id", "normalized_address", name="uq_location_account_address"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    brand_id: Mapped[str | None] = mapped_column(ForeignKey("brands.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_specs.id"))
    name: Mapped[str | None] = mapped_column(String(240))
    address1: Mapped[str | None] = mapped_column(String(240))
    address2: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(2), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(16))
    county: Mapped[str | None] = mapped_column(String(120))
    normalized_address: Mapped[str] = mapped_column(String(500), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    phone: Mapped[str | None] = mapped_column(String(40))
    operating_status: Mapped[str] = mapped_column(String(24), default="active")
    physical: Mapped[bool] = mapped_column(Boolean, default=True)
    authoritative: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    opened_on: Mapped[date | None] = mapped_column(Date)
    scope_status: Mapped[str] = mapped_column(String(24), default="in_scope", index=True)
    location_role: Mapped[str] = mapped_column(String(32), default="operating")
    verification_status: Mapped[str] = mapped_column(String(32), default="unverified", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    evidence_assertion_id: Mapped[str | None] = mapped_column(String(36))
    account: Mapped[AccountGroup] = relationship(back_populates="locations")
    brand: Mapped[Brand | None] = relationship()


class LegalEntity(Base, TimestampMixin):
    __tablename__ = "legal_entities"
    __table_args__ = (UniqueConstraint("jurisdiction", "external_id", name="uq_legal_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_specs.id"))
    legal_name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    jurisdiction: Mapped[str] = mapped_column(String(8), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str | None] = mapped_column(String(60))
    formed_on: Mapped[date | None] = mapped_column(Date)
    registered_agent_name: Mapped[str | None] = mapped_column(String(240))
    registered_agent_type: Mapped[str | None] = mapped_column(String(40))
    principal_address: Mapped[str | None] = mapped_column(Text)
    account: Mapped[AccountGroup] = relationship(back_populates="legal_entities")


class PersonRole(Base, TimestampMixin):
    __tablename__ = "person_roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_specs.id"))
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    role: Mapped[str | None] = mapped_column(String(120))
    ownership_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    professional_profile_url: Mapped[str | None] = mapped_column(Text)
    account: Mapped[AccountGroup] = relationship(back_populates="people")
    profile: Mapped[ContactProfile | None] = relationship(back_populates="person", cascade="all, delete-orphan", uselist=False)


class ContactProfile(Base, TimestampMixin):
    __tablename__ = "contact_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    person_role_id: Mapped[str] = mapped_column(ForeignKey("person_roles.id"), unique=True, index=True)
    preferred_name: Mapped[str | None] = mapped_column(String(120))
    is_primary_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    communication_preference: Mapped[str | None] = mapped_column(String(32))
    timezone: Mapped[str | None] = mapped_column(String(80))
    interests: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    relationship_notes: Mapped[str | None] = mapped_column(Text)
    person: Mapped[PersonRole] = relationship(back_populates="profile")


class ContactPoint(Base, TimestampMixin):
    __tablename__ = "contact_points"
    __table_args__ = (UniqueConstraint("account_id", "kind", "normalized_value", name="uq_contact_value"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    person_role_id: Mapped[str | None] = mapped_column(ForeignKey("person_roles.id"))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_specs.id"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(500), nullable=False)
    scope: Mapped[str] = mapped_column(String(24), default="business")
    verification_status: Mapped[str] = mapped_column(String(32), default="unverified")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    account: Mapped[AccountGroup] = relationship(back_populates="contacts")
    person: Mapped[PersonRole | None] = relationship()


class PermitLicense(Base, TimestampMixin):
    __tablename__ = "permit_licenses"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_permit_source_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("source_specs.id"))
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str | None] = mapped_column(String(60))
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    classifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    account: Mapped[AccountGroup] = relationship(back_populates="permits")


class CoverageEvidence(Base, TimestampMixin):
    __tablename__ = "coverage_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_specs.id"))
    coverage_type: Mapped[str] = mapped_column(String(80), nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(240))
    policy_hmac: Mapped[str | None] = mapped_column(String(128), index=True)
    policy_masked: Mapped[str | None] = mapped_column(String(40))
    effective_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    coverage_as_of: Mapped[date | None] = mapped_column(Date)
    confidence: Mapped[str] = mapped_column(String(32), default="unknown")
    policy_status: Mapped[str] = mapped_column(String(24), default="unknown", index=True)
    renewal_status: Mapped[str] = mapped_column(String(32), default="unknown")
    source_kind: Mapped[str] = mapped_column(String(32), default="research_evidence")
    observed_on: Mapped[date | None] = mapped_column(Date)
    annual_premium: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("coverage_evidence.id"), index=True)
    account: Mapped[AccountGroup] = relationship(back_populates="coverages")


class Trigger(Base, TimestampMixin):
    __tablename__ = "triggers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_specs.id"))
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    occurred_on: Mapped[date | None] = mapped_column(Date)
    severity: Mapped[str] = mapped_column(String(24), default="info")
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_review_only: Mapped[bool] = mapped_column(Boolean, default=False)
    account: Mapped[AccountGroup] = relationship(back_populates="triggers")


class ServiceOffering(Base, TimestampMixin):
    __tablename__ = "service_offerings"
    __table_args__ = (UniqueConstraint("account_id", "source_id", "normalized_name", name="uq_service_account_source_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_specs.id"), index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    verification_status: Mapped[str] = mapped_column(String(24), default="verified")
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    evidence_assertion_id: Mapped[str | None] = mapped_column(ForeignKey("field_assertions.id"))
    account: Mapped[AccountGroup] = relationship(back_populates="services")


class ExposureEvidence(Base, TimestampMixin):
    __tablename__ = "exposure_evidence"
    __table_args__ = (UniqueConstraint("account_id", "source_id", "kind", "basis", name="uq_exposure_account_source_basis"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_specs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    basis: Mapped[str] = mapped_column(String(500), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(24), default="verified")
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    evidence_assertion_id: Mapped[str | None] = mapped_column(ForeignKey("field_assertions.id"))
    account: Mapped[AccountGroup] = relationship(back_populates="exposures")


class OwnershipRelationship(Base, TimestampMixin):
    __tablename__ = "ownership_relationships"
    __table_args__ = (UniqueConstraint("account_id", "source_id", "subject_name", "relationship_type", "object_name", name="uq_ownership_relationship"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_specs.id"), index=True)
    subject_name: Mapped[str] = mapped_column(String(240), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(80), nullable=False)
    object_name: Mapped[str] = mapped_column(String(240), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(24), default="verified")
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    evidence_assertion_id: Mapped[str | None] = mapped_column(ForeignKey("field_assertions.id"))
    account: Mapped[AccountGroup] = relationship(back_populates="ownership_relationships")


class BusinessEvent(Base, TimestampMixin):
    __tablename__ = "business_events"
    __table_args__ = (UniqueConstraint("account_id", "source_id", "kind", "label", "occurred_on", name="uq_business_event"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_specs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    occurred_on: Mapped[date | None] = mapped_column(Date)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification_status: Mapped[str] = mapped_column(String(24), default="verified")
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    evidence_assertion_id: Mapped[str | None] = mapped_column(ForeignKey("field_assertions.id"))
    account: Mapped[AccountGroup] = relationship(back_populates="business_events")


class FieldAssertion(Base, TimestampMixin):
    __tablename__ = "field_assertions"
    __table_args__ = (
        UniqueConstraint("source_id", "source_record_id", "field_name", "content_hash", name="uq_assertion_record"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("account_groups.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_specs.id"), index=True)
    source_run_id: Mapped[str | None] = mapped_column(ForeignKey("source_runs.id"))
    source_record_id: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    authority: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    parser_version: Mapped[str] = mapped_column(String(40), default="1")
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(80), default="assertion")
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    account: Mapped[AccountGroup | None] = relationship(back_populates="assertions")


class EntityLink(Base, TimestampMixin):
    __tablename__ = "entity_links"
    __table_args__ = (UniqueConstraint("left_account_id", "right_account_id", name="uq_entity_link_pair"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    left_account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    right_account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="proposed", index=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(120))
    left: Mapped[AccountGroup] = relationship(foreign_keys=[left_account_id])
    right: Mapped[AccountGroup] = relationship(foreign_keys=[right_account_id])


class ReviewDecision(Base, TimestampMixin):
    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(120), default="admin")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ScoreContribution(Base, TimestampMixin):
    __tablename__ = "score_contributions"
    __table_args__ = (UniqueConstraint("account_id", "score_version", "category", "factor", name="uq_score_factor"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    score_version: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    factor: Mapped[str] = mapped_column(String(120), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    max_points: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    account: Mapped[AccountGroup] = relationship(back_populates="score_contributions")


class ExportBatch(Base, TimestampMixin):
    __tablename__ = "export_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    file_path: Mapped[str | None] = mapped_column(Text)
    lead_count: Mapped[int] = mapped_column(Integer, default=0)
    manifest_hash: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)


class SuppressionEntry(Base, TimestampMixin):
    __tablename__ = "suppression_entries"
    __table_args__ = (UniqueConstraint("kind", "normalized_value", name="uq_suppression_value"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str] = mapped_column(String(240), default="opt_out")
    source: Mapped[str | None] = mapped_column(String(240))


class Outcome(Base, TimestampMixin):
    __tablename__ = "outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    renewal_date: Mapped[date | None] = mapped_column(Date)
    value: Mapped[float | None] = mapped_column(Float)


class ResearchRun(Base, TimestampMixin):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("research_batches.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    mode: Mapped[str] = mapped_column(String(32), default="public_first")
    budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    calculated_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    provider_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rate_card_id: Mapped[str | None] = mapped_column(ForeignKey("provider_rate_cards.id"))
    provider_response_id: Mapped[str | None] = mapped_column(String(120))
    dedupe_key: Mapped[str | None] = mapped_column(String(400), unique=True, index=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account: Mapped[AccountGroup] = relationship(back_populates="research_runs")
    steps: Mapped[list[ResearchStep]] = relationship(back_populates="run", cascade="all, delete-orphan")
    findings: Mapped[list[ResearchFinding]] = relationship(back_populates="run", cascade="all, delete-orphan")
    assessment: Mapped[ResearchAssessment | None] = relationship(back_populates="run", uselist=False)
    batch: Mapped[ResearchBatch | None] = relationship(back_populates="runs")


class ResearchBatch(Base, TimestampMixin):
    __tablename__ = "research_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mode: Mapped[str] = mapped_column(String(24), default="free_public")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    account_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    approved_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_leads: Mapped[int] = mapped_column(Integer, default=25)
    total_budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    per_lead_budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(120), default="automation")
    error: Mapped[str | None] = mapped_column(Text)
    runs: Mapped[list[ResearchRun]] = relationship(back_populates="batch")


class ResearchAssessment(Base, TimestampMixin):
    __tablename__ = "research_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("research_runs.id"), unique=True, index=True)
    rubric_version: Mapped[str] = mapped_column(String(32), default="readiness-v1")
    completeness: Mapped[int] = mapped_column(Integer, default=0)
    ready: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    blockers: Mapped[list[str]] = mapped_column(JSON, default=list)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    account: Mapped[AccountGroup] = relationship(back_populates="research_assessments")
    run: Mapped[ResearchRun | None] = relationship(back_populates="assessment")


class ReadinessDecision(Base, TimestampMixin):
    __tablename__ = "readiness_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    assessment_id: Mapped[str | None] = mapped_column(ForeignKey("research_assessments.id"))
    decision: Mapped[str] = mapped_column(String(24), default="override")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(String(120), default="admin")
    account: Mapped[AccountGroup] = relationship(back_populates="readiness_decisions")


class CrawlPage(Base, TimestampMixin):
    __tablename__ = "crawl_pages"
    __table_args__ = (UniqueConstraint("account_id", "canonical_url", name="uq_crawl_page_account_url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(120))
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    etag: Mapped[str | None] = mapped_column(String(240))
    last_modified: Mapped[str | None] = mapped_column(String(240))
    robots_status: Mapped[str] = mapped_column(String(24), default="unknown")
    parser_version: Mapped[str] = mapped_column(String(40), default="website-v2")
    error: Mapped[str | None] = mapped_column(Text)
    account: Mapped[AccountGroup] = relationship(back_populates="crawl_pages")


class ResearchStep(Base, TimestampMixin):
    __tablename__ = "research_steps"
    __table_args__ = (UniqueConstraint("research_run_id", "kind", name="uq_research_step_kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    research_run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    calculated_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    provider_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run: Mapped[ResearchRun] = relationship(back_populates="steps")


class ResearchFinding(Base, TimestampMixin):
    __tablename__ = "research_findings"
    __table_args__ = (
        UniqueConstraint("research_run_id", "field_name", "content_hash", name="uq_research_finding_content"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    research_run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_specs.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    citation_label: Mapped[str | None] = mapped_column(String(240))
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    authority: Mapped[str] = mapped_column(String(24), default="derived")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(24), default="proposed", index=True)
    parser_version: Mapped[str] = mapped_column(String(80), default="deterministic-v1")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decision_notes: Mapped[str | None] = mapped_column(Text)
    materialized_type: Mapped[str | None] = mapped_column(String(80))
    materialized_id: Mapped[str | None] = mapped_column(String(36))
    run: Mapped[ResearchRun] = relationship(back_populates="findings")


class ProviderRateCard(Base, TimestampMixin):
    __tablename__ = "provider_rate_cards"
    __table_args__ = (UniqueConstraint("provider", "model", "effective_on", name="uq_provider_model_effective"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    effective_on: Mapped[date] = mapped_column(Date, nullable=False)
    input_usd_per_million: Mapped[float] = mapped_column(Float, nullable=False)
    cached_input_usd_per_million: Mapped[float] = mapped_column(Float, nullable=False)
    output_usd_per_million: Mapped[float] = mapped_column(Float, nullable=False)
    web_search_usd_per_thousand: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CalendarConnection(Base, TimestampMixin):
    __tablename__ = "calendar_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(24), default="google")
    google_account_email: Mapped[str | None] = mapped_column(String(320))
    calendar_id: Mapped[str] = mapped_column(String(320), default="primary")
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    sync_token: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="connected", index=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Meeting(Base, TimestampMixin):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    person_role_id: Mapped[str | None] = mapped_column(ForeignKey("person_roles.id"), index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timezone: Mapped[str] = mapped_column(String(80), default="America/New_York")
    location: Mapped[str | None] = mapped_column(Text)
    attendees: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reminder_minutes: Mapped[int] = mapped_column(Integer, default=30)
    create_meet: Mapped[bool] = mapped_column(Boolean, default=False)
    send_updates: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    sync_status: Mapped[str] = mapped_column(String(24), default="not_synced", index=True)
    google_event_id: Mapped[str | None] = mapped_column(String(200), unique=True, index=True)
    google_etag: Mapped[str | None] = mapped_column(String(240))
    google_html_link: Mapped[str | None] = mapped_column(Text)
    google_meet_link: Mapped[str | None] = mapped_column(Text)
    private_prep_notes: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(120), default="admin")
    account: Mapped[AccountGroup] = relationship(back_populates="meetings")
    person: Mapped[PersonRole | None] = relationship()


class SalesActivity(Base, TimestampMixin):
    __tablename__ = "sales_activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    disposition: Mapped[str | None] = mapped_column(String(40))
    subject: Mapped[str | None] = mapped_column(String(240))
    direction: Mapped[str] = mapped_column(String(24), default="outbound")
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    person_role_id: Mapped[str | None] = mapped_column(ForeignKey("person_roles.id"), index=True)
    coverage_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("coverage_evidence.id"), index=True)
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id"), index=True)
    outcome: Mapped[str | None] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), default="admin")
    account: Mapped[AccountGroup] = relationship(back_populates="sales_activities")


class SalesTask(Base, TimestampMixin):
    __tablename__ = "sales_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("account_groups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    title: Mapped[str | None] = mapped_column(String(240))
    priority: Mapped[str] = mapped_column(String(24), default="normal")
    person_role_id: Mapped[str | None] = mapped_column(ForeignKey("person_roles.id"), index=True)
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("sales_activities.id"), index=True)
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(120), default="admin")
    account: Mapped[AccountGroup] = relationship(back_populates="sales_tasks")
