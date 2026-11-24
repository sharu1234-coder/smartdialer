"""Initial schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-11-24 00:00:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enums ---
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE campaign_status AS ENUM ('DRAFT','ACTIVE','PAUSED','COMPLETED','CANCELLED');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE dial_mode AS ENUM ('PROGRESSIVE','PREDICTIVE');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE agent_status AS ENUM (
                'OFFLINE','AVAILABLE','RESERVED','DIALING','CONNECTED','WRAP_UP','PAUSED'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE call_status AS ENUM (
                'QUEUED','RESERVED','INITIATED','RINGING','ANSWERED','CONNECTED',
                'COMPLETED','FAILED','CANCELLED'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE call_dial_mode AS ENUM ('PROGRESSIVE','PREDICTIVE');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE borrower_status AS ENUM ('PENDING','RESERVED','CALLED','DO_NOT_CALL','COMPLETED');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE outbox_status AS ENUM ('PENDING','PROCESSING','SENT','FAILED','CANCELLED');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE provider_event_type AS ENUM (
                'RINGING','ANSWERED','CONNECTED','COMPLETED','FAILED','BUSY','NO_ANSWER'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # --- campaigns ---
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.Enum("DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED",
                                    name="campaign_status"), nullable=False, server_default="DRAFT"),
        sa.Column("dial_mode", sa.Enum("PROGRESSIVE", "PREDICTIVE", name="dial_mode"),
                  nullable=False, server_default="PROGRESSIVE"),
        sa.Column("max_concurrent_calls", sa.Integer, nullable=False, server_default="10"),
        sa.Column("caller_id", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])

    # --- agents ---
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.Enum(
            "OFFLINE", "AVAILABLE", "RESERVED", "DIALING", "CONNECTED", "WRAP_UP", "PAUSED",
            name="agent_status"
        ), nullable=False, server_default="OFFLINE"),
        sa.Column("campaign_id", sa.String(36),
                  sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("current_call_id", sa.String(36), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reservation_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("available_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agents_status", "agents", ["status"])
    op.create_index("ix_agents_campaign_id", "agents", ["campaign_id"])
    op.create_index("ix_agents_status_campaign", "agents", ["status", "campaign_id"])

    # --- borrowers ---
    op.create_table(
        "borrowers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone_number", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", sa.Enum(
            "PENDING", "RESERVED", "CALLED", "DO_NOT_CALL", "COMPLETED",
            name="borrower_status"
        ), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reservation_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_borrowers_status", "borrowers", ["status"])
    op.create_index("ix_borrowers_campaign_id", "borrowers", ["campaign_id"])
    op.create_index("ix_borrowers_campaign_status", "borrowers", ["campaign_id", "status"])

    # --- calls ---
    op.create_table(
        "calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("borrower_id", sa.String(36),
                  sa.ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(36),
                  sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider_id", sa.String(50), nullable=False, server_default="provider_a"),
        sa.Column("provider_call_id", sa.String(255), nullable=True),
        sa.Column("status", sa.Enum(
            "QUEUED", "RESERVED", "INITIATED", "RINGING", "ANSWERED", "CONNECTED",
            "COMPLETED", "FAILED", "CANCELLED",
            name="call_status"
        ), nullable=False, server_default="QUEUED"),
        sa.Column("dial_mode", sa.Enum("PROGRESSIVE", "PREDICTIVE", name="call_dial_mode"),
                  nullable=False, server_default="PROGRESSIVE"),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("state_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.String(1024), nullable=True),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_calls_status", "calls", ["status"])
    op.create_index("ix_calls_campaign_id", "calls", ["campaign_id"])
    op.create_index("ix_calls_agent_id", "calls", ["agent_id"])
    op.create_index("ix_calls_borrower_id", "calls", ["borrower_id"])
    op.create_index("ix_calls_idempotency_key", "calls", ["idempotency_key"])
    op.create_index("ix_calls_campaign_status", "calls", ["campaign_id", "status"])

    # --- call_outbox ---
    op.create_table(
        "call_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36),
                  sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Enum(
            "PENDING", "PROCESSING", "SENT", "FAILED", "CANCELLED",
            name="outbox_status"
        ), nullable=False, server_default="PENDING"),
        sa.Column("from_number", sa.String(50), nullable=False),
        sa.Column("to_number", sa.String(50), nullable=False),
        sa.Column("provider_id", sa.String(50), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column("process_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outbox_status", "call_outbox", ["status"])
    op.create_index("ix_outbox_call_id", "call_outbox", ["call_id"])

    # --- provider_events ---
    op.create_table(
        "provider_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36),
                  sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.Enum(
            "RINGING", "ANSWERED", "CONNECTED", "COMPLETED", "FAILED", "BUSY", "NO_ANSWER",
            name="provider_event_type"
        ), nullable=False),
        sa.Column("provider_id", sa.String(50), nullable=False),
        sa.Column("is_duplicate", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_out_of_order", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("payload", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("call_id", "event_id", name="uq_provider_events_call_event"),
    )
    op.create_index("ix_provider_events_call_id", "provider_events", ["call_id"])

    # --- reservations ---
    op.create_table(
        "reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36),
                  sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(36),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("borrower_id", sa.String(36),
                  sa.ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # --- metrics ---
    op.create_table(
        "metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tick", sa.Integer, nullable=False),
        sa.Column("calls_attempted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("calls_answered", sa.Integer, nullable=False, server_default="0"),
        sa.Column("calls_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("agents_available", sa.Integer, nullable=False, server_default="0"),
        sa.Column("agents_busy", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ewma_answer_rate", sa.sa.Float, nullable=True),
        sa.Column("desired_calls", sa.Integer, nullable=True),
        sa.Column("approved_calls", sa.Integer, nullable=True),
        sa.Column("safety_decision", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_metrics_campaign_tick", "metrics", ["campaign_id", "tick"])


def downgrade() -> None:
    op.drop_table("metrics")
    op.drop_table("reservations")
    op.drop_table("provider_events")
    op.drop_table("call_outbox")
    op.drop_table("calls")
    op.drop_table("borrowers")
    op.drop_table("agents")
    op.drop_table("campaigns")

    for enum_name in [
        "provider_event_type", "outbox_status", "borrower_status",
        "call_dial_mode", "call_status", "agent_status", "dial_mode", "campaign_status"
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
