"""instagram session state

Revision ID: 0004_instagram_session_state
Revises: 0003_normalize_job_status_case
Create Date: 2026-04-30
"""

from alembic import op

revision = "0004_instagram_session_state"
down_revision = "0003_normalize_job_status_case"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS provider VARCHAR(40) NOT NULL DEFAULT 'instagram'")
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS session_kind VARCHAR(40) NOT NULL DEFAULT 'legacy'")
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS settings_secret_id VARCHAR(80)")
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS user_agent TEXT")
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_ok_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_error_reason VARCHAR(80)")

    op.execute(
        """
        UPDATE accounts
        SET provider = COALESCE(NULLIF(provider, ''), 'instagram'),
            session_kind = CASE
                WHEN session_kind IS NOT NULL AND session_kind != 'legacy' THEN session_kind
                WHEN secret_kind IN ('session', 'sessionid') THEN 'unsupported_legacy'
                WHEN secret_kind = 'cookies' THEN 'browser_cookies'
                ELSE 'unsupported_legacy'
            END
        """
    )
    op.execute("UPDATE accounts SET last_ok_at = last_validated_at WHERE status = 'OK' AND last_ok_at IS NULL")
    op.execute(
        """
        UPDATE accounts
        SET last_error_at = last_validated_at,
            last_error_reason = failure_reason
        WHERE failure_reason IS NOT NULL
          AND last_error_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE accounts
        SET status = 'INVALID_SESSION',
            failure_reason = 'UNSUPPORTED_LEGACY_SESSION',
            last_error_reason = 'UNSUPPORTED_LEGACY_SESSION',
            last_error_at = COALESCE(last_validated_at, NOW())
        WHERE session_kind = 'unsupported_legacy'
        """
    )

    op.create_index("ix_accounts_provider", "accounts", ["provider"], if_not_exists=True)
    op.create_index("ix_accounts_session_kind", "accounts", ["session_kind"], if_not_exists=True)
    op.create_index(
        "ix_accounts_settings_secret_id",
        "accounts",
        ["settings_secret_id"],
        unique=True,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_accounts_settings_secret_id", table_name="accounts", if_exists=True)
    op.drop_index("ix_accounts_session_kind", table_name="accounts", if_exists=True)
    op.drop_index("ix_accounts_provider", table_name="accounts", if_exists=True)
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS last_error_reason")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS last_error_at")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS last_ok_at")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS user_agent")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS settings_secret_id")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS session_kind")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS provider")
