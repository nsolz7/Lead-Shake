"""Add free-first research, source governance, structured evidence, and metered AI usage.

Revision ID: 0003_free_first
Revises: 0002_automation
"""
from alembic import context, op
import sqlalchemy as sa


revision = "0003_free_first"
down_revision = "0002_automation"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    if not context.is_offline_mode() and "provider_rate_cards" in sa.inspect(op.get_bind()).get_table_names():
        return
    for column in (
        sa.Column("cost_class", sa.String(24), nullable=False, server_default="open"),
        sa.Column("credential_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("overage_possible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("license_name", sa.String(120)),
        sa.Column("terms_url", sa.Text()),
        sa.Column("policy_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("policy_evidence_url", sa.Text()),
        sa.Column("policy_reviewed_by", sa.String(120)),
    ):
        op.add_column("source_specs", column)
    op.create_index("ix_source_specs_cost_class", "source_specs", ["cost_class"])
    op.create_index("ix_source_specs_policy_status", "source_specs", ["policy_status"])

    for column in (
        sa.Column("classification_status", sa.String(24), nullable=False, server_default="review_required"),
        sa.Column("classification_reason", sa.String(240)),
        sa.Column("classification_policy_version", sa.String(32), nullable=False, server_default="vertical-policy-v2"),
        sa.Column("classification_confidence", sa.Float(), nullable=False, server_default="0.5"),
    ):
        op.add_column("account_groups", column)
    op.create_index("ix_account_groups_classification_status", "account_groups", ["classification_status"])

    for column in (
        sa.Column("location_role", sa.String(32), nullable=False, server_default="operating"),
        sa.Column("verification_status", sa.String(32), nullable=False, server_default="unverified"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_assertion_id", sa.String(36)),
    ):
        op.add_column("locations", column)
    op.create_index("ix_locations_verification_status", "locations", ["verification_status"])

    op.create_table(
        "provider_rate_cards",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("input_usd_per_million", sa.Float(), nullable=False),
        sa.Column("cached_input_usd_per_million", sa.Float(), nullable=False),
        sa.Column("output_usd_per_million", sa.Float(), nullable=False),
        sa.Column("web_search_usd_per_thousand", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("provider", "model", "effective_on", name="uq_provider_model_effective"),
    )
    op.create_index("ix_provider_rate_cards_provider", "provider_rate_cards", ["provider"])
    op.create_index("ix_provider_rate_cards_model", "provider_rate_cards", ["model"])

    for column in (
        sa.Column("calculated_cost_microusd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_usage", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("rate_card_id", sa.String(80), sa.ForeignKey("provider_rate_cards.id")),
        sa.Column("provider_response_id", sa.String(120)),
        sa.Column("dedupe_key", sa.String(400)),
    ):
        op.add_column("research_runs", column)
    op.create_index("ix_research_runs_dedupe_key", "research_runs", ["dedupe_key"], unique=True)
    op.add_column("research_steps", sa.Column("calculated_cost_microusd", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("research_steps", sa.Column("provider_usage", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    for column in (
        sa.Column("source_id", sa.String(80), sa.ForeignKey("source_specs.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.String(120)),
        sa.Column("decision_notes", sa.Text()),
        sa.Column("materialized_type", sa.String(80)),
        sa.Column("materialized_id", sa.String(36)),
    ):
        op.add_column("research_findings", column)
    op.create_index("ix_research_findings_source_id", "research_findings", ["source_id"])

    structured_tables = (
        ("service_offerings", [
            sa.Column("name", sa.String(240), nullable=False),
            sa.Column("normalized_name", sa.String(240), nullable=False),
            sa.Column("category", sa.String(120)),
        ]),
        ("exposure_evidence", [
            sa.Column("kind", sa.String(80), nullable=False),
            sa.Column("basis", sa.String(500), nullable=False),
        ]),
        ("ownership_relationships", [
            sa.Column("subject_name", sa.String(240), nullable=False),
            sa.Column("relationship_type", sa.String(80), nullable=False),
            sa.Column("object_name", sa.String(240), nullable=False),
        ]),
        ("business_events", [
            sa.Column("kind", sa.String(80), nullable=False),
            sa.Column("label", sa.String(240), nullable=False),
            sa.Column("occurred_on", sa.Date()),
            sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        ]),
    )
    for table, fields in structured_tables:
        op.create_table(
            table,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("account_id", sa.String(36), sa.ForeignKey("account_groups.id"), nullable=False),
            sa.Column("source_id", sa.String(80), sa.ForeignKey("source_specs.id"), nullable=False),
            *fields,
            sa.Column("verification_status", sa.String(24), nullable=False, server_default="verified"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"),
            sa.Column("evidence_assertion_id", sa.String(36), sa.ForeignKey("field_assertions.id")),
            *_timestamps(),
        )
        op.create_index(f"ix_{table}_account_id", table, ["account_id"])
        op.create_index(f"ix_{table}_source_id", table, ["source_id"])
    op.create_index("ix_exposure_evidence_kind", "exposure_evidence", ["kind"])
    op.create_index("ix_business_events_kind", "business_events", ["kind"])
    op.create_unique_constraint("uq_service_account_source_name", "service_offerings", ["account_id", "source_id", "normalized_name"])
    op.create_unique_constraint("uq_exposure_account_source_basis", "exposure_evidence", ["account_id", "source_id", "kind", "basis"])
    op.create_unique_constraint("uq_ownership_relationship", "ownership_relationships", ["account_id", "source_id", "subject_name", "relationship_type", "object_name"])
    op.create_unique_constraint("uq_business_event", "business_events", ["account_id", "source_id", "kind", "label", "occurred_on"])

    op.execute("UPDATE research_runs SET mode = 'legacy_public_first' WHERE mode = 'public_first'")


def downgrade() -> None:
    for table in ("business_events", "ownership_relationships", "exposure_evidence", "service_offerings"):
        op.drop_table(table)
    op.drop_index("ix_research_findings_source_id", table_name="research_findings")
    for column in ("materialized_id", "materialized_type", "decision_notes", "decided_by", "decided_at", "source_id"):
        op.drop_column("research_findings", column)
    op.drop_column("research_steps", "provider_usage")
    op.drop_column("research_steps", "calculated_cost_microusd")
    op.drop_index("ix_research_runs_dedupe_key", table_name="research_runs")
    for column in ("dedupe_key", "provider_response_id", "rate_card_id", "provider_usage", "calculated_cost_microusd"):
        op.drop_column("research_runs", column)
    op.drop_table("provider_rate_cards")
    op.drop_index("ix_locations_verification_status", table_name="locations")
    for column in ("evidence_assertion_id", "last_seen_at", "first_seen_at", "verification_status", "location_role"):
        op.drop_column("locations", column)
    op.drop_index("ix_account_groups_classification_status", table_name="account_groups")
    for column in ("classification_confidence", "classification_policy_version", "classification_reason", "classification_status"):
        op.drop_column("account_groups", column)
    op.drop_index("ix_source_specs_policy_status", table_name="source_specs")
    op.drop_index("ix_source_specs_cost_class", table_name="source_specs")
    for column in ("policy_reviewed_by", "policy_evidence_url", "policy_status", "terms_url", "license_name", "overage_possible", "credential_required", "cost_class"):
        op.drop_column("source_specs", column)
