"""Backup manifests and restore verification. The drill target guard runs before anything else."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from sqlalchemy import text

from lens.storage.db import Database
from lens.storage.models import Base

DRILL_DATABASE = "lens_drill"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MAX_BACKUP_AGE = timedelta(hours=26)
CHECKSUM_SQL = "SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), ''))"


class UnsafeTargetError(ValueError):
    pass


def ensure_drill_target(url: str) -> None:
    """Refuse every restore target except the job-local drill database.

    The database name is decoded and every query parameter that could redirect the connection is
    refused, so neither percent-encoding nor `?dbname=`/`?host=` can point the restore at production.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    name = unquote(parts.path.lstrip("/"))
    query = {k.lower() for k in parse_qs(parts.query, keep_blank_values=True)}
    if host not in LOCAL_HOSTS:
        raise UnsafeTargetError(f"restore target host {host or '(none)'} is not local")
    if name != DRILL_DATABASE:
        raise UnsafeTargetError(
            f"restore target database must be {DRILL_DATABASE}, not {name or '(none)'}"
        )
    if query & {"dbname", "database", "host", "hostaddr", "service", "options"}:
        raise UnsafeTargetError("restore target URL may not override the host or database")


async def manifest(db: Database) -> dict[str, Any]:
    tables: dict[str, dict[str, Any]] = {}
    async with db.engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            # table names come from our own metadata, never from input
            sql = f'{CHECKSUM_SQL} FROM "{table.name}" t'
            row = (await connection.execute(text(sql))).one()
            tables[table.name] = {"rows": int(row[0]), "md5": str(row[1])}
        revision = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar()
    return {"created_at": datetime.now(UTC).isoformat(), "revision": revision, "tables": tables}


@dataclass(frozen=True, slots=True)
class DrillResult:
    ok: bool
    differences: list[str]


def compare_manifests(
    expected: dict[str, Any], actual: dict[str, Any], *, now: datetime
) -> DrillResult:
    differences = []
    created = datetime.fromisoformat(expected["created_at"])
    if now - created > MAX_BACKUP_AGE:
        differences.append(f"backup is older than {MAX_BACKUP_AGE}: {created.isoformat()}")
    if expected.get("revision") != actual.get("revision"):
        differences.append(f"revision {expected.get('revision')} != {actual.get('revision')}")
    for name, values in expected["tables"].items():
        got = actual["tables"].get(name)
        if got != values:
            differences.append(f"{name}: expected {values}, restored {got}")
    return DrillResult(not differences, differences)
