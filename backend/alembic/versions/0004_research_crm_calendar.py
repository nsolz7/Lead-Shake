"""Add research readiness, CRM profiles, policy snapshots, and calendar meetings.

Revision ID: 0004_research_crm_calendar
Revises: 0003_free_first
"""
import json
import uuid
from datetime import datetime, timezone

from alembic import context, op
import sqlalchemy as sa


revision = "0004_research_crm_calendar"
down_revision = "0003_free_first"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    if not context.is_offline_mode() and "research_assessments" in sa.inspect(op.get_bind()).get_table_names():
        return
    for column in (
        sa.Column("research_state", sa.String(24), nullable=False, server_default="not_started"),
        sa.Column("research_assessed_at", sa.DateTime(timezone=True)),
        sa.Column("contact_ready_at", sa.DateTime(timezone=True)),
        sa.Column("relationship_status", sa.String(24), nullable=False, server_default="prospect"),
    ):
        op.add_column("account_groups", column)
    for name, columns in (
        ("ix_account_groups_research_state", ["research_state"]),
        ("ix_account_groups_research_assessed_at", ["research_assessed_at"]),
        ("ix_account_groups_contact_ready_at", ["contact_ready_at"]),
        ("ix_account_groups_relationship_status", ["relationship_status"]),
    ):
        op.create_index(name, "account_groups", columns)

    op.create_table(
        "contact_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("person_role_id", sa.String(36), sa.ForeignKey("person_roles.id"), nullable=False, unique=True),
        sa.Column("preferred_name", sa.String(120)),
        sa.Column("is_primary_contact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("communication_preference", sa.String(32)),
        sa.Column("timezone", sa.String(80)),
        sa.Column("interests", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("relationship_notes", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_contact_profiles_person_role_id", "contact_profiles", ["person_role_id"], unique=True)

    for column in (
        sa.Column("policy_status", sa.String(24), nullable=False, server_default="unknown"),
        sa.Column("renewal_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("source_kind", sa.String(32), nullable=False, server_default="research_evidence"),
        sa.Column("observed_on", sa.Date()),
        sa.Column("annual_premium", sa.Float()),
        sa.Column("notes", sa.Text()),
        sa.Column("supersedes_id", sa.String(36), sa.ForeignKey("coverage_evidence.id")),
    ):
        op.add_column("coverage_evidence", column)
    op.create_index("ix_coverage_evidence_policy_status", "coverage_evidence", ["policy_status"])
    op.create_index("ix_coverage_evidence_supersedes_id", "coverage_evidence", ["supersedes_id"])
    op.execute("UPDATE coverage_evidence SET observed_on = COALESCE(coverage_as_of, effective_on, CAST(created_at AS DATE))")

    op.create_table(
        "research_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mode", sa.String(24), nullable=False, server_default="free_public"),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("filters", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("account_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("approved_sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("max_leads", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("total_budget_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("per_lead_budget_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spent_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(120), nullable=False, server_default="automation"),
        sa.Column("error", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_research_batches_status", "research_batches", ["status"])
    op.add_column("research_runs", sa.Column("batch_id", sa.String(36), sa.ForeignKey("research_batches.id")))
    op.create_index("ix_research_runs_batch_id", "research_runs", ["batch_id"])

    op.create_table(
        "research_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("account_groups.id"), nullable=False),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("research_runs.id"), unique=True),
        sa.Column("rubric_version", sa.String(32), nullable=False, server_default="readiness-v1"),
        sa.Column("completeness", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dimensions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("blockers", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_timestamps(),
    )
    op.create_index("ix_research_assessments_account_id", "research_assessments", ["account_id"])
    op.create_index("ix_research_assessments_research_run_id", "research_assessments", ["research_run_id"], unique=True)
    op.create_index("ix_research_assessments_ready", "research_assessments", ["ready"])
    op.create_index("ix_research_assessments_assessed_at", "research_assessments", ["assessed_at"])

    # Preserve existing evidence by generating one initial immutable assessment per
    # account. Unknown optional facts remain not_started; they are not treated as
    # negative evidence or silently invented during migration.
    connection = op.get_bind()
    account_result = connection.execute(sa.text("""
        SELECT a.id, a.eligible, a.operating_status, a.classification_status,
               a.website, a.domain, a.location_count_verified, a.ownership_status,
               a.franchise_signal, a.corporate_control_signal, a.pe_signal, a.public_company_signal,
               (SELECT COUNT(*) FROM person_roles p WHERE p.account_id = a.id AND p.confidence >= 0.6) AS person_count,
               (SELECT COUNT(*) FROM contact_points c WHERE c.account_id = a.id AND c.suppressed = false AND c.scope IN ('business', 'professional')) AS contact_count,
               (SELECT COUNT(*) FROM field_assertions f WHERE f.account_id = a.id) AS assertion_count,
               (SELECT COUNT(*) FROM field_assertions f WHERE f.account_id = a.id AND f.conflict = true) AS conflict_count,
               (SELECT COUNT(*) FROM legal_entities l WHERE l.account_id = a.id) +
                 (SELECT COUNT(*) FROM permit_licenses p WHERE p.account_id = a.id) AS legal_count,
               (SELECT COUNT(*) FROM service_offerings s WHERE s.account_id = a.id) +
                 (SELECT COUNT(*) FROM exposure_evidence e WHERE e.account_id = a.id) AS operation_count,
               (SELECT COUNT(*) FROM coverage_evidence c WHERE c.account_id = a.id) +
                 (SELECT COUNT(*) FROM business_events b WHERE b.account_id = a.id) AS timing_count,
               (SELECT COUNT(*) FROM business_events b WHERE b.account_id = a.id) +
                 (SELECT COUNT(*) FROM triggers t WHERE t.account_id = a.id AND t.occurred_on IS NOT NULL) AS event_count
        FROM account_groups a
    """))
    # Alembic's offline SQL renderer returns None because it cannot inspect data.
    # Online upgrades execute the evidence-preserving backfill below.
    existing_accounts = account_result.mappings().all() if account_result is not None else []
    assessed_at = datetime.now(timezone.utc)
    for account in existing_accounts:
        dimensions = {
            "identity": {"status": "found" if account.operating_status == "active" and account.classification_status == "target" else "not_started", "reason": "Backfilled from existing active target classification.", "evidence_ids": []},
            "website": {"status": "found" if account.website and account.domain else "not_started", "reason": "Backfilled from accepted account website/domain.", "evidence_ids": []},
            "footprint": {"status": "found" if account.location_count_verified is not None and 2 <= account.location_count_verified <= 5 else "not_started", "reason": "Backfilled from the existing verified location count.", "evidence_ids": []},
            "ownership": {"status": "conflict" if any((account.franchise_signal, account.corporate_control_signal, account.pe_signal, account.public_company_signal)) else ("found" if account.ownership_status in {"confirmed", "likely"} else "not_started"), "reason": "Backfilled from existing ownership/control signals.", "evidence_ids": []},
            "decision_maker": {"status": "found" if account.person_count else "not_started", "reason": "Backfilled from existing sourced people.", "evidence_ids": []},
            "contacts": {"status": "found" if account.contact_count else "not_started", "reason": "Backfilled from existing usable business/professional contacts.", "evidence_ids": []},
            "legal_licenses": {"status": "found" if account.legal_count else "not_started", "reason": "Backfilled from existing legal and permit records.", "evidence_ids": []},
            "operations_exposures": {"status": "found" if account.operation_count else "not_started", "reason": "Backfilled from existing operations/exposure records.", "evidence_ids": []},
            "insurance_timing": {"status": "found" if account.timing_count else "not_started", "reason": "Backfilled from existing coverage/timing records.", "evidence_ids": []},
            "recent_events": {"status": "found" if account.event_count else "not_started", "reason": "Backfilled from existing dated business events.", "evidence_ids": []},
            "freshness_conflicts": {"status": "conflict" if account.conflict_count else ("found" if account.assertion_count else "not_started"), "reason": "Backfilled from existing assertion conflict state.", "evidence_ids": []},
        }
        completed = sum(value["status"] == "found" for value in dimensions.values())
        completeness = round(100 * completed / len(dimensions))
        critical = ("identity", "website", "footprint", "ownership", "decision_maker", "contacts", "freshness_conflicts")
        blockers = [name for name in critical if dimensions[name]["status"] != "found"]
        if not account.eligible:
            blockers.insert(0, "qualification")
        ready = not blockers
        assessment_id = str(uuid.uuid4())
        connection.execute(sa.text("""
            INSERT INTO research_assessments
                (id, account_id, rubric_version, completeness, ready, dimensions, blockers, assessed_at, created_at, updated_at)
            VALUES
                (:id, :account_id, 'readiness-v1', :completeness, :ready, :dimensions, :blockers, :assessed_at, :assessed_at, :assessed_at)
        """), {
            "id": assessment_id, "account_id": account.id, "completeness": completeness,
            "ready": ready, "dimensions": json.dumps(dimensions), "blockers": json.dumps(blockers),
            "assessed_at": assessed_at,
        })
        connection.execute(sa.text("""
            UPDATE account_groups
            SET research_state = :state, research_assessed_at = :assessed_at,
                contact_ready_at = :contact_ready_at, research_completeness = :completeness
            WHERE id = :account_id
        """), {
            "state": "ready" if ready else ("blocked" if any(dimensions[name]["status"] == "conflict" for name in critical) else "needs_review"),
            "assessed_at": assessed_at, "contact_ready_at": assessed_at if ready else None,
            "completeness": completeness, "account_id": account.id,
        })

    op.create_table(
        "readiness_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("account_groups.id"), nullable=False),
        sa.Column("assessment_id", sa.String(36), sa.ForeignKey("research_assessments.id")),
        sa.Column("decision", sa.String(24), nullable=False, server_default="override"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(120), nullable=False, server_default="admin"),
        *_timestamps(),
    )
    op.create_index("ix_readiness_decisions_account_id", "readiness_decisions", ["account_id"])

    op.create_table(
        "crawl_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("account_groups.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("status_code", sa.Integer()),
        sa.Column("content_type", sa.String(120)),
        sa.Column("content_hash", sa.String(128)),
        sa.Column("etag", sa.String(240)),
        sa.Column("last_modified", sa.String(240)),
        sa.Column("robots_status", sa.String(24), nullable=False, server_default="unknown"),
        sa.Column("parser_version", sa.String(40), nullable=False, server_default="website-v2"),
        sa.Column("error", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("account_id", "canonical_url", name="uq_crawl_page_account_url"),
    )
    op.create_index("ix_crawl_pages_account_id", "crawl_pages", ["account_id"])
    op.create_index("ix_crawl_pages_content_hash", "crawl_pages", ["content_hash"])

    op.create_table(
        "calendar_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(120), nullable=False, unique=True),
        sa.Column("provider", sa.String(24), nullable=False, server_default="google"),
        sa.Column("google_account_email", sa.String(320)),
        sa.Column("calendar_id", sa.String(320), nullable=False, server_default="primary"),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("sync_token", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False, server_default="connected"),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_calendar_connections_username", "calendar_connections", ["username"], unique=True)
    op.create_index("ix_calendar_connections_status", "calendar_connections", ["status"])

    op.create_table(
        "meetings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("account_groups.id"), nullable=False),
        sa.Column("person_role_id", sa.String(36), sa.ForeignKey("person_roles.id")),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="America/New_York"),
        sa.Column("location", sa.Text()),
        sa.Column("attendees", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("reminder_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("create_meet", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("send_updates", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("sync_status", sa.String(24), nullable=False, server_default="not_synced"),
        sa.Column("google_event_id", sa.String(200), unique=True),
        sa.Column("google_etag", sa.String(240)),
        sa.Column("google_html_link", sa.Text()),
        sa.Column("google_meet_link", sa.Text()),
        sa.Column("private_prep_notes", sa.Text()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("sync_error", sa.Text()),
        sa.Column("created_by", sa.String(120), nullable=False, server_default="admin"),
        *_timestamps(),
    )
    for name, cols, unique in (
        ("ix_meetings_account_id", ["account_id"], False),
        ("ix_meetings_person_role_id", ["person_role_id"], False),
        ("ix_meetings_start_at", ["start_at"], False),
        ("ix_meetings_end_at", ["end_at"], False),
        ("ix_meetings_status", ["status"], False),
        ("ix_meetings_sync_status", ["sync_status"], False),
        ("ix_meetings_google_event_id", ["google_event_id"], True),
    ):
        op.create_index(name, "meetings", cols, unique=unique)

    for column in (
        sa.Column("subject", sa.String(240)),
        sa.Column("direction", sa.String(24), nullable=False, server_default="outbound"),
        sa.Column("duration_minutes", sa.Integer()),
        sa.Column("person_role_id", sa.String(36), sa.ForeignKey("person_roles.id")),
        sa.Column("coverage_evidence_id", sa.String(36), sa.ForeignKey("coverage_evidence.id")),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id")),
        sa.Column("outcome", sa.String(80)),
    ):
        op.add_column("sales_activities", column)
    for name, cols in (
        ("ix_sales_activities_person_role_id", ["person_role_id"]),
        ("ix_sales_activities_coverage_evidence_id", ["coverage_evidence_id"]),
        ("ix_sales_activities_meeting_id", ["meeting_id"]),
    ):
        op.create_index(name, "sales_activities", cols)

    for column in (
        sa.Column("title", sa.String(240)),
        sa.Column("priority", sa.String(24), nullable=False, server_default="normal"),
        sa.Column("person_role_id", sa.String(36), sa.ForeignKey("person_roles.id")),
        sa.Column("activity_id", sa.String(36), sa.ForeignKey("sales_activities.id")),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id")),
    ):
        op.add_column("sales_tasks", column)
    for name, cols in (
        ("ix_sales_tasks_person_role_id", ["person_role_id"]),
        ("ix_sales_tasks_activity_id", ["activity_id"]),
        ("ix_sales_tasks_meeting_id", ["meeting_id"]),
    ):
        op.create_index(name, "sales_tasks", cols)


def downgrade() -> None:
    for column in ("meeting_id", "activity_id", "person_role_id", "priority", "title"):
        op.drop_column("sales_tasks", column)
    for column in ("outcome", "meeting_id", "coverage_evidence_id", "person_role_id", "duration_minutes", "direction", "subject"):
        op.drop_column("sales_activities", column)
    op.drop_table("meetings")
    op.drop_table("calendar_connections")
    op.drop_table("crawl_pages")
    op.drop_table("readiness_decisions")
    op.drop_table("research_assessments")
    op.drop_column("research_runs", "batch_id")
    op.drop_table("research_batches")
    for column in ("supersedes_id", "notes", "annual_premium", "observed_on", "source_kind", "renewal_status", "policy_status"):
        op.drop_column("coverage_evidence", column)
    op.drop_table("contact_profiles")
    for column in ("relationship_status", "contact_ready_at", "research_assessed_at", "research_state"):
        op.drop_column("account_groups", column)
