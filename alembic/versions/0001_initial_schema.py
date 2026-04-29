"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index("ix_admin_users_username", "admin_users", ["username"], unique=True, if_not_exists=True)

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index("ix_admin_sessions_token_hash", "admin_sessions", ["token_hash"], unique=True, if_not_exists=True)
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"], if_not_exists=True)

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=120), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("secret_id", sa.String(length=80), nullable=False),
        sa.Column("secret_kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(length=80), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("secret_id", name="uq_accounts_secret_id"),
        if_not_exists=True,
    )
    op.create_index("ix_accounts_username", "accounts", ["username"], unique=True, if_not_exists=True)
    op.create_index("ix_accounts_status", "accounts", ["status"], if_not_exists=True)
    op.create_index("ix_accounts_is_default", "accounts", ["is_default"], if_not_exists=True)

    op.create_table(
        "profile_cache",
        sa.Column("username", sa.String(length=120), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_profile_cache_expires_at", "profile_cache", ["expires_at"], if_not_exists=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("shortcodes", sa.JSON(), nullable=False),
        sa.Column("items_done", sa.Integer(), nullable=False),
        sa.Column("items_total", sa.Integer(), nullable=False),
        sa.Column("retry_after_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("archive_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index("ix_jobs_username", "jobs", ["username"], if_not_exists=True)
    op.create_index("ix_jobs_status", "jobs", ["status"], if_not_exists=True)

    op.create_table(
        "job_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shortcode", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("media_done", sa.Boolean(), nullable=False),
        sa.Column("metadata_done", sa.Boolean(), nullable=False),
        sa.Column("comments_done", sa.Boolean(), nullable=False),
        sa.Column("error_reason", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "shortcode", name="uq_job_shortcode"),
        if_not_exists=True,
    )
    op.create_index("ix_job_items_job_id", "job_items", ["job_id"], if_not_exists=True)
    op.create_index("ix_job_items_shortcode", "job_items", ["shortcode"], if_not_exists=True)
    op.create_index("ix_job_items_status", "job_items", ["status"], if_not_exists=True)

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("shortcode", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "shortcode", name="uq_posts_job_shortcode"),
        if_not_exists=True,
    )
    op.create_index("ix_posts_username", "posts", ["username"], if_not_exists=True)
    op.create_index("ix_posts_job_id", "posts", ["job_id"], if_not_exists=True)
    op.create_index("ix_posts_shortcode", "posts", ["shortcode"], if_not_exists=True)

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_shortcode", sa.String(length=120), nullable=False),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index("ix_comments_post_shortcode", "comments", ["post_shortcode"], if_not_exists=True)
    op.create_index("ix_comments_job_id", "comments", ["job_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_comments_job_id", table_name="comments", if_exists=True)
    op.drop_index("ix_comments_post_shortcode", table_name="comments", if_exists=True)
    op.drop_table("comments", if_exists=True)

    op.drop_index("ix_posts_shortcode", table_name="posts", if_exists=True)
    op.drop_index("ix_posts_job_id", table_name="posts", if_exists=True)
    op.drop_index("ix_posts_username", table_name="posts", if_exists=True)
    op.drop_table("posts", if_exists=True)

    op.drop_index("ix_job_items_status", table_name="job_items", if_exists=True)
    op.drop_index("ix_job_items_shortcode", table_name="job_items", if_exists=True)
    op.drop_index("ix_job_items_job_id", table_name="job_items", if_exists=True)
    op.drop_table("job_items", if_exists=True)

    op.drop_index("ix_jobs_status", table_name="jobs", if_exists=True)
    op.drop_index("ix_jobs_username", table_name="jobs", if_exists=True)
    op.drop_table("jobs", if_exists=True)

    op.drop_index("ix_profile_cache_expires_at", table_name="profile_cache", if_exists=True)
    op.drop_table("profile_cache", if_exists=True)

    op.drop_index("ix_accounts_is_default", table_name="accounts", if_exists=True)
    op.drop_index("ix_accounts_status", table_name="accounts", if_exists=True)
    op.drop_index("ix_accounts_username", table_name="accounts", if_exists=True)
    op.drop_table("accounts", if_exists=True)

    op.drop_table("settings", if_exists=True)

    op.drop_index("ix_admin_sessions_expires_at", table_name="admin_sessions", if_exists=True)
    op.drop_index("ix_admin_sessions_token_hash", table_name="admin_sessions", if_exists=True)
    op.drop_table("admin_sessions", if_exists=True)

    op.drop_index("ix_admin_users_username", table_name="admin_users", if_exists=True)
    op.drop_table("admin_users", if_exists=True)
