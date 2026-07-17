"""Add automation-forward research and sales workflow.

Revision ID: 0002_automation
Revises: 0001_initial
"""
from alembic import context, op
import sqlalchemy as sa


revision = "0002_automation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 historically used metadata.create_all. On a brand-new checkout that
    # metadata may already include this revision's schema; preserve upgrades for
    # genuine older databases while avoiding duplicate DDL on fresh installs.
    if not context.is_offline_mode() and "research_runs" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.add_column("source_runs", sa.Column("records_rejected", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("source_runs", sa.Column("rejection_reasons", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("account_groups", sa.Column("data_status", sa.String(24), nullable=False, server_default="active"))
    op.add_column("account_groups", sa.Column("research_completeness", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("account_groups", sa.Column("sales_stage", sa.String(32), nullable=False, server_default="uncontacted"))
    op.add_column("account_groups", sa.Column("sales_brief", sa.Text(), nullable=True))
    op.add_column("account_groups", sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("account_groups", sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("locations", sa.Column("scope_status", sa.String(24), nullable=False, server_default="in_scope"))

    op.create_index("ix_account_groups_data_status", "account_groups", ["data_status"])
    op.create_index("ix_account_groups_sales_stage", "account_groups", ["sales_stage"])
    op.create_index("ix_account_groups_next_action_at", "account_groups", ["next_action_at"])
    op.create_index("ix_locations_scope_status", "locations", ["scope_status"])

    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("account_groups.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("mode", sa.String(32), nullable=False, server_default="public_first"),
        sa.Column("budget_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spent_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_runs_account_id", "research_runs", ["account_id"])
    op.create_index("ix_research_runs_status", "research_runs", ["status"])
    op.create_table(
        "research_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("research_runs.id"), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("spent_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("research_run_id", "kind", name="uq_research_step_kind"),
    )
    op.create_index("ix_research_steps_research_run_id", "research_steps", ["research_run_id"])
    op.create_index("ix_research_steps_status", "research_steps", ["status"])
    op.create_table(
        "research_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("research_runs.id"), nullable=False),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("account_groups.id"), nullable=False),
        sa.Column("field_name", sa.String(120), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("citation_label", sa.String(240)),
        sa.Column("evidence_excerpt", sa.Text()),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("authority", sa.String(24), nullable=False, server_default="derived"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(24), nullable=False, server_default="proposed"),
        sa.Column("parser_version", sa.String(80), nullable=False, server_default="deterministic-v1"),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("research_run_id", "field_name", "content_hash", name="uq_research_finding_content"),
    )
    op.create_index("ix_research_findings_research_run_id", "research_findings", ["research_run_id"])
    op.create_index("ix_research_findings_account_id", "research_findings", ["account_id"])
    op.create_index("ix_research_findings_status", "research_findings", ["status"])
    op.create_table(
        "sales_activities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("account_groups.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("disposition", sa.String(40)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.String(120), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sales_activities_account_id", "sales_activities", ["account_id"])
    op.create_index("ix_sales_activities_kind", "sales_activities", ["kind"])
    op.create_index("ix_sales_activities_occurred_at", "sales_activities", ["occurred_at"])
    op.create_table(
        "sales_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("account_groups.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.String(120), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sales_tasks_account_id", "sales_tasks", ["account_id"])
    op.create_index("ix_sales_tasks_kind", "sales_tasks", ["kind"])
    op.create_index("ix_sales_tasks_status", "sales_tasks", ["status"])
    op.create_index("ix_sales_tasks_due_at", "sales_tasks", ["due_at"])


def downgrade() -> None:
    op.drop_table("sales_tasks")
    op.drop_table("sales_activities")
    op.drop_table("research_findings")
    op.drop_table("research_steps")
    op.drop_table("research_runs")
    op.drop_index("ix_locations_scope_status", table_name="locations")
    op.drop_index("ix_account_groups_next_action_at", table_name="account_groups")
    op.drop_index("ix_account_groups_sales_stage", table_name="account_groups")
    op.drop_index("ix_account_groups_data_status", table_name="account_groups")
    op.drop_column("locations", "scope_status")
    for column in ("next_action_at", "last_contact_at", "sales_brief", "sales_stage", "research_completeness", "data_status"):
        op.drop_column("account_groups", column)
    op.drop_column("source_runs", "rejection_reasons")
    op.drop_column("source_runs", "records_rejected")
