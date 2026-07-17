from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field


class ConnectorScope(BaseModel):
    states: list[str] = Field(default_factory=lambda: ["NC", "SC", "VA"])
    verticals: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    limit: int = Field(default=500, ge=1, le=100000)
    commercial_enabled: bool = False
    budget_cents: int = Field(default=0, ge=0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class RawRecord(BaseModel):
    source_record_id: str
    source_url: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    brand_name: str | None = None
    legal_name: str | None = None
    entity_type: str | None = None
    entity_status: str | None = None
    entity_external_id: str | None = None
    registered_agent_name: str | None = None
    registered_agent_type: str | None = None
    formed_on: date | None = None
    category: str | None = None
    vertical: str | None = None
    naics: str | None = None
    website: str | None = None
    domain: str | None = None
    phone: str | None = None
    email: str | None = None
    email_verification_status: str | None = None
    email_verification_score: float | None = None
    contact_form_url: str | None = None
    professional_profile_url: str | None = None
    place_id: str | None = None
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    county: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    operating_status: str = "active"
    physical: bool = True
    person_name: str | None = None
    person_role: str | None = None
    ownership_signal: bool = False
    ownership_status: str | None = None
    franchise_signal: bool = False
    corporate_control_signal: bool = False
    pe_signal: bool = False
    public_company_signal: bool = False
    permit_kind: str | None = None
    permit_number: str | None = None
    permit_status: str | None = None
    permit_issued_on: date | None = None
    permit_expires_on: date | None = None
    permit_classifications: list[str] = Field(default_factory=list)
    coverage_type: str | None = None
    carrier: str | None = None
    policy_identifier: str | None = None
    coverage_effective_on: date | None = None
    coverage_expires_on: date | None = None
    coverage_as_of: date | None = None
    coverage_confidence: str | None = None
    trigger_kind: str | None = None
    trigger_date: date | None = None
    trigger_label: str | None = None
    trigger_risk_review_only: bool = False
    services: list[dict[str, Any]] = Field(default_factory=list)
    exposures: list[dict[str, Any]] = Field(default_factory=list)
    ownership_relationships: list[dict[str, Any]] = Field(default_factory=list)
    business_events: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0, le=1)
    evidence_excerpt: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Connector(ABC):
    source_id: str

    def __init__(self) -> None:
        self.spent_cents = 0
        self.rejection_counts: dict[str, int] = {}

    def reject(self, reason: str, count: int = 1) -> None:
        if count > 0:
            self.rejection_counts[reason] = self.rejection_counts.get(reason, 0) + count

    @abstractmethod
    async def discover(self, scope: ConnectorScope) -> AsyncIterator[RawRecord]:
        if False:
            yield RawRecord(source_record_id="unreachable")
