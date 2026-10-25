"""The dashboard's access boundary and views, against a migrated PostgreSQL with seeded rows."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from lens.dashboard.app import DashboardConfig, create_app
from lens.dashboard.auth import COOKIE, issue_session
from lens.storage.db import Database
from lens.storage.models import (
    BacktestReportRow,
    BriefingRow,
    DeliveryRow,
    InstrumentRow,
    OperationalEvent,
    Owner,
    PipelineRun,
    SignalEventRow,
    SignalRow,
    StageRun,
)
from tests.dashboard.test_auth import NOW, OWNER, SECRET, TOKEN, login

pytestmark = pytest.mark.db

REPORT = json.loads(
    (
        Path(__file__).resolve().parents[2] / "reports" / "pullback_in_uptrend-52df5d457a0c.json"
    ).read_text(encoding="utf-8")
)
DAY = date(2026, 10, 16)


async def seed(db: Database) -> None:
    async with db.session() as s:
        s.add(Owner(id=OWNER, base_currency="MYR", timezone="Asia/Kuala_Lumpur"))
        s.add(Owner(id=7, base_currency="MYR", timezone="Asia/Kuala_Lumpur"))
        await s.flush()
        s.add(
            InstrumentRow(
                id=1,
                symbol="KSTL",
                name="Kestrel Systems",
                asset_class="stock",
                market="XNYS",
                currency="USD",
            )
        )
        run = PipelineRun(
            cycle_id=uuid.uuid4(),
            owner_id=OWNER,
            briefing_date=DAY,
            trigger="schedule_1",
            code_version="abc1234",
            status="SENT",
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=9),
        )
        s.add(run)
        await s.flush()
        s.add(
            StageRun(
                run_id=run.id,
                stage="gather",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=4),
                outcome="ok",
            )
        )
        for owner, total, words in (
            (OWNER, "214820.75", "Kestrel withdrawn"),
            (7, "999.00", "stranger only"),
        ):
            briefing = BriefingRow(
                owner_id=owner,
                briefing_date=DAY,
                run_id=run.id if owner == OWNER else None,
                mode="deterministic",
                document={
                    "portfolio": {
                        "total_base": total,
                        "base_currency": "MYR",
                        "exposure_by_asset_class": {"stock": "100.0"},
                    }
                },
                chunks=[f"<b>Goldirham Lens</b> · {words} &amp; <script>x</script>"],
                inputs={},
                code_version="abc1234",
            )
            s.add(briefing)
            await s.flush()
            s.add(
                DeliveryRow(
                    briefing_id=briefing.id,
                    owner_id=owner,
                    briefing_date=DAY,
                    state="SENT",
                    sent_at=NOW,
                )
            )
        signal = SignalRow(
            owner_id=OWNER,
            instrument_id=1,
            strategy="pullback_in_uptrend",
            strategy_version="52df5d457a0c",
            signal_day=date(2026, 10, 14),
            entry=Decimal("93.90"),
            stop=Decimal("90.40"),
            t1=Decimal("99.15"),
            t2=Decimal("104.40"),
            size_pct=Decimal("20.00"),
            expiry_days=120,
        )
        s.add(signal)
        await s.flush()
        s.add(
            SignalEventRow(
                signal_id=signal.id,
                kind="T1_TOUCHED",
                day=date(2026, 10, 20),
                price=Decimal("99.15"),
                r=Decimal("1.50"),
            )
        )
        s.add(
            BacktestReportRow(
                strategy_version=REPORT["version"],
                name=REPORT["strategy"],
                params=REPORT["params"],
                from_day=date.fromisoformat(REPORT["period"][0]),
                to_day=date.fromisoformat(REPORT["period"][1]),
                report=REPORT,
                report_hash="e6f2b5105c67810b" + "0" * 48,
            )
        )
        s.add(
            OperationalEvent(
                kind="backup_ok",
                severity="info",
                source="backup.yml",
                dedupe_key="backup-2026-10-16",
            )
        )


@pytest.fixture
async def client(db: Database, migrated_url: str) -> AsyncIterator[httpx.AsyncClient]:
    await seed(db)
    reader = Database(migrated_url, read_only=True)
    config = DashboardConfig(
        reader, OWNER, TOKEN, "goldirham_lens_bot", SECRET, secure_cookies=False, clock=lambda: NOW
    )
    app = create_app(lambda: config)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://dash.test") as http:
        http.app = app  # type: ignore[attr-defined]
        yield http
    await reader.dispose()


def signed_in(http: httpx.AsyncClient) -> httpx.AsyncClient:
    http.cookies.set(COOKIE, issue_session(OWNER, secret=SECRET, now=NOW), domain="dash.test")
    return http


SAMPLE = {"day": DAY.isoformat(), "signal_id": "1", "report_id": "1"}
PUBLIC = {"/login", "/auth/telegram", "/dashboard.css"}


def page_paths(app: object) -> list[str]:
    paths = []
    for route in app.routes:  # type: ignore[attr-defined]
        if isinstance(route, APIRoute) and "GET" in route.methods and route.path not in PUBLIC:
            paths.append(route.path.format(**SAMPLE))
    return paths


async def test_every_page_needs_the_owner_session(client: httpx.AsyncClient) -> None:
    paths = page_paths(client.app)  # type: ignore[attr-defined]
    assert len(paths) == 9
    for cookie in (
        None,
        "garbage",
        issue_session(7, secret=SECRET, now=NOW),
        issue_session(OWNER, secret="x" * 40, now=NOW),
    ):
        client.cookies.clear()
        if cookie:
            client.cookies.set(COOKIE, cookie, domain="dash.test")
        for path in paths:
            response = await client.get(path)
            assert response.status_code == 303, (path, cookie)
            assert response.headers["location"] == "/login"
            assert "Kestrel" not in response.text


async def test_only_logout_accepts_post(client: httpx.AsyncClient) -> None:
    for route in client.app.routes:  # type: ignore[attr-defined]
        if isinstance(route, APIRoute):
            assert route.methods <= {"GET", "HEAD"} or route.path == "/logout", route.path
    response = await signed_in(client).post("/briefings")
    assert response.status_code == 405


async def test_a_stranger_signed_by_telegram_is_refused(client: httpx.AsyncClient) -> None:
    response = await client.get("/auth/telegram", params=login(user=7))
    assert response.status_code == 403
    assert COOKIE not in response.cookies


async def test_the_owner_signs_in_and_reads_only_their_rows(client: httpx.AsyncClient) -> None:
    response = await client.get("/auth/telegram", params=login())
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie

    pages = {path: await client.get(path) for path in page_paths(client.app)}  # type: ignore[attr-defined]
    assert all(r.status_code == 200 for r in pages.values()), {
        p: r.status_code for p, r in pages.items()
    }
    briefing = pages[f"/briefings/{DAY.isoformat()}"].text
    assert "<strong>Goldirham Lens</strong>" in briefing
    assert "Kestrel withdrawn &amp;" in briefing
    assert "<script>" not in briefing
    assert "stranger only" not in briefing
    assert "MYR 214,820.75" in pages["/portfolio"].text
    assert "MYR 999.00" not in pages["/portfolio"].text
    assert "USD 93.90" in pages["/signals"].text
    assert "T1_TOUCHED" in pages["/signals/1"].text
    assert "pullback_in_uptrend" in pages["/backtests"].text
    assert "Backtest: pullback_in_uptrend" in pages["/backtests/1"].text
    assert "backup_ok" in pages["/health"].text
    assert "9.0s" in pages["/health"].text


async def test_headers_keep_pages_private(client: httpx.AsyncClient) -> None:
    response = await signed_in(client).get("/")
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


async def test_unknown_rows_are_404_not_errors(client: httpx.AsyncClient) -> None:
    http = signed_in(client)
    assert (await http.get("/briefings/2020-01-01")).status_code == 404
    assert (await http.get("/signals/999")).status_code == 404
    assert (await http.get("/backtests/999")).status_code == 404


async def test_unconfigured_deployment_answers_503() -> None:
    app = create_app(lambda: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://dash.test"
    ) as http:
        for path in ("/", "/login", "/auth/telegram"):
            assert (await http.get(path)).status_code == 503


async def test_the_dashboard_connection_cannot_write(db: Database, migrated_url: str) -> None:
    await seed(db)
    reader = Database(migrated_url, read_only=True)
    try:
        with pytest.raises(DBAPIError, match="read-only transaction"):
            async with reader.session() as s:
                await s.execute(text("UPDATE owners SET timezone = 'UTC'"))
    finally:
        await reader.dispose()
    async with db.session() as s:
        assert (
            await s.scalar(text("SELECT timezone FROM owners WHERE id = 42")) == "Asia/Kuala_Lumpur"
        )
    _ = datetime.now(UTC)
