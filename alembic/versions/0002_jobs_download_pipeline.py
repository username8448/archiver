"""jobs download pipeline fields

Revision ID: 0002_jobs_download_pipeline
Revises: 0001_initial_schema
Create Date: 2026-04-30
"""

from alembic import op

revision = "0002_jobs_download_pipeline"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS completed_items INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS failed_items INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS result_dir TEXT")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS error_code VARCHAR(80)")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP WITH TIME ZONE")

    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS target VARCHAR(120)")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS media_type VARCHAR(40)")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS error_code VARCHAR(80)")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS error_message TEXT")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS result_path TEXT")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS metadata_path TEXT")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE job_items ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP WITH TIME ZONE")
    op.create_index("ix_job_items_target", "job_items", ["target"], if_not_exists=True)

    op.execute(
        """
        UPDATE jobs
        SET status = CASE status
            WHEN 'PENDING' THEN 'queued'
            WHEN 'RUNNING' THEN 'running'
            WHEN 'DONE' THEN 'completed'
            WHEN 'FAILED' THEN 'failed'
            WHEN 'CANCELLED' THEN 'cancelled'
            WHEN 'WAITING' THEN 'failed'
            ELSE status
        END
        """
    )
    op.execute(
        """
        UPDATE job_items
        SET status = CASE status
            WHEN 'PENDING' THEN 'queued'
            WHEN 'RUNNING' THEN 'running'
            WHEN 'DONE' THEN 'completed'
            WHEN 'FAILED' THEN 'failed'
            WHEN 'CANCELLED' THEN 'cancelled'
            ELSE status
        END
        """
    )
    op.execute("UPDATE jobs SET completed_items = items_done WHERE completed_items = 0 AND items_done > 0")
    op.execute("UPDATE jobs SET error_code = failure_reason WHERE error_code IS NULL AND failure_reason IS NOT NULL")
    op.execute("UPDATE job_items SET error_code = error_reason WHERE error_code IS NULL AND error_reason IS NOT NULL")
    op.execute(
        """
        UPDATE job_items
        SET target = jobs.username
        FROM jobs
        WHERE job_items.job_id = jobs.id AND job_items.target IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_job_items_target", table_name="job_items", if_exists=True)
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS finished_at")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS started_at")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS metadata_path")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS result_path")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS error_message")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS error_code")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS media_type")
    op.execute("ALTER TABLE job_items DROP COLUMN IF EXISTS target")

    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS finished_at")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS started_at")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS error_code")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS result_dir")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS failed_items")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS completed_items")
