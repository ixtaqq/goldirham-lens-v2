from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from lens.ops.backup import (
    UnsafeTargetError,
    compare_manifests,
    ensure_drill_target,
    libpq_environment,
    manifest,
)
from lens.storage.db import Database
from tests.conftest import _ensure_database

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@db.supabase.co:5432/postgres",
        "postgresql://u:p@localhost:5432/postgres",
        "postgresql://u:p@localhost:5432/lens%5Fdrill%2F..%2Fpostgres",
        "postgresql://u:p@localhost:5432/lens_drill?dbname=postgres",
        "postgresql://u:p@localhost:5432/lens_drill?host=db.supabase.co",
        "postgresql://u:p@localhost:5432/",
        "postgresql://u:p@127.0.0.2:5432/lens_drill",
        "",
    ],
)
def test_restore_drill_refuses_anything_but_the_local_drill_database(url: str) -> None:
    """Scenario 15: by name, percent-encoding, or query-string tricks."""
    with pytest.raises(UnsafeTargetError):
        ensure_drill_target(url)


def test_local_drill_database_is_accepted() -> None:
    ensure_drill_target("postgresql://lens:x@localhost:5432/lens_drill")
    ensure_drill_target("postgresql+asyncpg://lens:x@127.0.0.1:5432/lens%5Fdrill")


def _manifest(created: datetime, rows: int = 3) -> dict[str, object]:
    return {
        "created_at": created.isoformat(),
        "revision": "0001",
        "tables": {"bars": {"rows": rows, "md5": "abc"}, "owners": {"rows": 1, "md5": "def"}},
    }


def test_matching_restore_passes() -> None:
    assert compare_manifests(_manifest(NOW - timedelta(hours=2)), _manifest(NOW), now=NOW).ok


def test_stale_backup_and_missing_rows_fail_the_drill() -> None:
    result = compare_manifests(
        _manifest(NOW - timedelta(hours=30)), _manifest(NOW, rows=2), now=NOW
    )
    assert not result.ok
    assert len(result.differences) == 2
    assert result.differences[0].startswith("backup is older than")
    assert result.differences[1].startswith("bars: expected")


def test_libpq_environment_carries_the_connection_without_a_url() -> None:
    env = libpq_environment(
        "postgresql+asyncpg://lens%40prod:p%2Fss%3Aword@db.example.co:6543/postgres?sslmode=require"
    )
    assert env == {
        "PGHOST": "db.example.co",
        "PGPORT": "6543",
        "PGUSER": "lens@prod",
        "PGPASSWORD": "p/ss:word",
        "PGDATABASE": "postgres",
        "PGSSLMODE": "require",
    }
    assert libpq_environment("postgres://u:p@localhost/lens")["PGPORT"] == "5432"


@pytest.mark.db
def test_manifest_covers_only_the_tables_that_exist(
    migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backup before the first migration, and before any migration that adds a table."""
    url = migrated_url.replace("/lens_test", "/lens_test_manifest", 1)
    asyncio.run(_ensure_database(url))
    monkeypatch.setenv("DATABASE_URL_DIRECT", url)
    config = Config("alembic.ini")
    config.cmd_opts = None
    command.downgrade(config, "base")
    try:
        empty = asyncio.run(_manifest_of(url))
        assert empty["tables"] == {}
        assert empty["revision"] is None

        command.upgrade(config, "0001")
        older = asyncio.run(_manifest_of(url))
        assert older["revision"] == "0001"
        assert "level_alerts" not in older["tables"]
        assert older["tables"]["briefings"] == {
            "rows": 0,
            "md5": "d41d8cd98f00b204e9800998ecf8427e",
        }
    finally:
        command.downgrade(config, "base")


async def _manifest_of(url: str) -> dict[str, Any]:
    db = Database(url, rollback_only=True)
    try:
        return await manifest(db)
    finally:
        await db.dispose()
