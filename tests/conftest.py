from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from lens.storage.db import Database, normalize_url
from lens.storage.models import Base


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--no-db",
        action="store_true",
        default=False,
        help="Skip PostgreSQL integration tests and list what was not run.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    db_items = [item for item in items if item.get_closest_marker("db")]
    network_items = [item for item in items if item.get_closest_marker("network")]
    if not os.environ.get("LENS_RUN_NETWORK_TESTS"):
        for item in network_items:
            item.add_marker(pytest.mark.skip(reason="live provider check; provider-drift only"))
    if config.getoption("--no-db"):
        config._lens_skipped_db = [item.nodeid for item in db_items]  # type: ignore[attr-defined]
        for item in db_items:
            item.add_marker(pytest.mark.skip(reason="--no-db"))
        return
    if db_items and not os.environ.get("TEST_DATABASE_URL"):
        reason = (
            "TEST_DATABASE_URL is not set. Start PostgreSQL with `uv run poe db-up` and set "
            "TEST_DATABASE_URL, or pass --no-db to list the integration tests that will not run."
        )
        for item in db_items:
            item.add_marker(pytest.mark.usefixtures("_require_database"))
        config._lens_db_error = reason  # type: ignore[attr-defined]


@pytest.fixture
def _require_database(request: pytest.FixtureRequest) -> None:
    reason = getattr(request.config, "_lens_db_error", None)
    if reason:
        pytest.fail(reason, pytrace=False)


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    skipped = getattr(config, "_lens_skipped_db", None)
    if skipped:
        terminalreporter.section("PostgreSQL tests NOT run (--no-db)")
        for nodeid in skipped:
            terminalreporter.write_line(nodeid)


def _test_url() -> str:
    return normalize_url(os.environ["TEST_DATABASE_URL"])


async def _ensure_database(url: str) -> None:
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    if not name.startswith("lens_test"):
        raise RuntimeError(
            f"refusing to run tests against database {name!r}; use a lens_test* database"
        )
    admin = create_async_engine(
        urlunsplit(parts._replace(path="/postgres")), isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as connection:
        exists = await connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        )
        if not exists:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()


@pytest.fixture(scope="session")
def migrated_url() -> str:
    url = _test_url()
    asyncio.run(_ensure_database(url))
    config = Config("alembic.ini")
    config.cmd_opts = None
    os.environ["DATABASE_URL_DIRECT"] = url
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return url


@pytest.fixture
async def db(migrated_url: str) -> AsyncIterator[Database]:
    database = Database(migrated_url)
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with database.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield database
    await database.dispose()
