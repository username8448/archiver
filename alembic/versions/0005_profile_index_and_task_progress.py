"""profile index and task progress

Revision ID: 0005_profile_index_progress
Revises: 0004_instagram_session_state
Create Date: 2026-05-01
"""

from alembic import op

revision = "0005_profile_index_progress"
down_revision = "0004_instagram_session_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS type VARCHAR(40) NOT NULL DEFAULT 'enrichment'")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS stage VARCHAR(80)")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_current INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_total INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS current_item VARCHAR(120)")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_payload JSON NOT NULL DEFAULT '{}'::json")
    op.create_index("ix_jobs_type", "jobs", ["type"], if_not_exists=True)

    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS full_json_status VARCHAR(40) NOT NULL DEFAULT 'queued'")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS image_status VARCHAR(40) NOT NULL DEFAULT 'skipped'")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS video_status VARCHAR(40) NOT NULL DEFAULT 'skipped'")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS comments_status VARCHAR(40) NOT NULL DEFAULT 'skipped'")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS current_stage VARCHAR(80)")

    op.execute("UPDATE jobs SET type = COALESCE(NULLIF(type, ''), 'enrichment')")
    op.execute("UPDATE jobs SET progress_total = items_total WHERE progress_total = 0 AND items_total > 0")
    op.execute("UPDATE jobs SET progress_current = items_done WHERE progress_current = 0 AND items_done > 0")
    op.execute(
        """
        UPDATE job_items
        SET full_json_status = CASE
            WHEN metadata_done THEN 'done'
            WHEN status = 'FAILED' THEN 'failed'
            ELSE full_json_status
        END,
        image_status = CASE
            WHEN media_done THEN 'done'
            WHEN status = 'FAILED' AND media_type IN ('photo', 'carousel') THEN 'failed'
            ELSE image_status
        END,
        video_status = CASE
            WHEN media_done THEN 'done'
            WHEN status = 'FAILED' AND media_type IN ('video', 'reel') THEN 'failed'
            ELSE video_status
        END,
        comments_status = CASE
            WHEN comments_done THEN 'done'
            ELSE comments_status
        END
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS current_stage")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS comments_status")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS video_status")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS image_status")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS full_json_status")

    op.drop_index("ix_jobs_type", table_name="jobs", if_exists=True)
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS progress_payload")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS current_item")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS progress_total")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS progress_current")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS stage")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS type")
