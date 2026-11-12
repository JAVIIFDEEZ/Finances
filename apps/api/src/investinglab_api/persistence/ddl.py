"""The two guarantees every table gets from the database itself, as reusable DDL.

Migrations call these helpers so that no table is created without them, and a test checks
the live database: every table with an owner has forced row-level security, and the
append-only ones refuse changes.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "APP_ROLE",
    "FORBID_CHANGES_FUNCTION",
    "OWNER_SETTING",
    "append_only",
    "grant_to_app",
    "owner_isolation",
]

OWNER_SETTING: Final = "investinglab.owner_id"
"""Transaction setting holding the owner the application is serving."""

APP_ROLE: Final = "investinglab_app"
"""Group role of the running application: the privileges it needs and no more."""

FORBID_CHANGES_FUNCTION: Final = "investinglab_forbid_changes"

CREATE_APP_ROLE: Final = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        CREATE ROLE {APP_ROLE} NOLOGIN;
    END IF;
EXCEPTION WHEN insufficient_privilege OR duplicate_object THEN
    RAISE NOTICE 'role {APP_ROLE} not created: grant the privileges by hand';
END
$$;
"""

CREATE_FORBID_CHANGES: Final = f"""
CREATE FUNCTION {FORBID_CHANGES_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$$;
"""


def owner_isolation(table: str) -> list[str]:
    """Row-level security: a transaction only sees and writes the rows of its owner.

    It is forced, so it also binds the role that owns the table; with no owner set, no row
    is visible and none can be written.
    """
    owner = f"current_setting('{OWNER_SETTING}', true)"
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        (
            f"CREATE POLICY owner_isolation ON {table} "
            f"USING (owner_id = {owner}) WITH CHECK (owner_id = {owner})"
        ),
    ]


def append_only(table: str) -> list[str]:
    """Triggers that refuse every UPDATE, DELETE and TRUNCATE, whoever asks."""
    return [
        (
            f"CREATE TRIGGER {table}_no_row_changes BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {FORBID_CHANGES_FUNCTION}()"
        ),
        (
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION {FORBID_CHANGES_FUNCTION}()"
        ),
    ]


def grant_to_app(table: str, privileges: str) -> str:
    """Grant ``privileges`` on ``table`` to the application role, when the role exists."""
    return f"""
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        GRANT {privileges} ON {table} TO {APP_ROLE};
    END IF;
END
$$;
"""
