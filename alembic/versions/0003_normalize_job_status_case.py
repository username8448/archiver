"""normalize job status case

Revision ID: 0003_normalize_job_status_case
Revises: 0002_jobs_download_pipeline
Create Date: 2026-04-30
"""

from alembic import op

revision = "0003_normalize_job_status_case"
down_revision = "0002_jobs_download_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE jobs
        SET status = CASE status
            WHEN 'queued' THEN 'PENDING'
            WHEN 'running' THEN 'RUNNING'
            WHEN 'completed' THEN 'DONE'
            WHEN 'failed' THEN 'FAILED'
            WHEN 'cancelled' THEN 'CANCELLED'
            WHEN 'waiting' THEN 'WAITING'
            ELSE status
        END
        """
    )
    op.execute(
        """
        UPDATE job_items
        SET status = CASE status
            WHEN 'queued' THEN 'PENDING'
            WHEN 'running' THEN 'RUNNING'
            WHEN 'completed' THEN 'DONE'
            WHEN 'failed' THEN 'FAILED'
            WHEN 'cancelled' THEN 'CANCELLED'
            ELSE status
        END
        """
    )
    op.execute(
        """
        UPDATE job_items
        SET target = jobs.username
        FROM jobs
        WHERE job_items.job_id = jobs.id AND job_items.target IS NULL
        """
    )
    op.execute(
        """
        UPDATE jobs
        SET completed_items = counters.done_count,
            items_done = counters.done_count
        FROM (
            SELECT job_id, COUNT(*)::integer AS done_count
            FROM job_items
            WHERE status = 'DONE'
            GROUP BY job_id
        ) AS counters
        WHERE jobs.id = counters.job_id
        """
    )
    op.execute(
        """
        UPDATE jobs
        SET completed_items = 0,
            items_done = 0
        WHERE id NOT IN (
            SELECT DISTINCT job_id
            FROM job_items
            WHERE status = 'DONE'
        )
        """
    )
    op.execute(
        """
        UPDATE jobs
        SET failed_items = counters.failed_count
        FROM (
            SELECT job_id, COUNT(*)::integer AS failed_count
            FROM job_items
            WHERE status = 'FAILED'
            GROUP BY job_id
        ) AS counters
        WHERE jobs.id = counters.job_id
        """
    )
    op.execute(
        """
        UPDATE jobs
        SET failed_items = 0
        WHERE id NOT IN (
            SELECT DISTINCT job_id
            FROM job_items
            WHERE status = 'FAILED'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE jobs
        SET status = CASE status
            WHEN 'PENDING' THEN 'queued'
            WHEN 'RUNNING' THEN 'running'
            WHEN 'DONE' THEN 'completed'
            WHEN 'FAILED' THEN 'failed'
            WHEN 'CANCELLED' THEN 'cancelled'
            WHEN 'WAITING' THEN 'waiting'
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
