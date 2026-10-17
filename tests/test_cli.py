"""The CLI wires commands to the right code and exit codes. Network and Telegram are faked."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from lens import cli
from lens.data import collect
from lens.pipeline import cycle as cycle_module
from lens.pipeline.cycle import CycleResult, Outcome
from tests.pipeline.factories import asset_data_from, make_inputs

runner = CliRunner()


def test_help_lists_the_command_groups() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for name in ("cycle", "backtest", "strategy", "readiness", "doctor", "ops", "owner", "webhook"):
        assert name in result.output


@pytest.mark.parametrize(
    ("outcome", "code"), [(Outcome.SENT, 0), (Outcome.DEGRADED_SENT, 3), (Outcome.FAILED, 1)]
)
def test_cycle_run_maps_outcomes_to_exit_codes(
    outcome: Outcome, code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(*args: Any, **kwargs: Any) -> CycleResult:
        return CycleResult(outcome, date(2026, 10, 16), ["<b>hello</b>"])

    monkeypatch.setattr(cycle_module, "run_cycle", fake)
    result = runner.invoke(cli.app, ["cycle", "run", "--trigger", "schedule_1"])
    assert result.exit_code == code


def test_dry_run_prints_the_briefing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(*args: Any, **kwargs: Any) -> CycleResult:
        assert kwargs["dry_run"] is True
        return CycleResult(Outcome.PREVIEW, date(2026, 10, 16), ["first", "second"])

    monkeypatch.setattr(cycle_module, "run_cycle", fake)
    result = runner.invoke(cli.app, ["cycle", "run", "--dry-run"])
    assert result.exit_code == 0
    assert "first\n\n----- next message -----\n\nsecond" in result.stdout


def _fake_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    data = asset_data_from(make_inputs())

    async def collect_all(
        self: object, instruments: list[Any], stored: object = None
    ) -> dict[str, Any]:
        return {i.symbol: data[i.symbol] for i in instruments if i.symbol in data}

    monkeypatch.setattr(collect.Collector, "collect_all", collect_all)


def test_readiness_prints_reasons_per_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_collect(monkeypatch)
    result = runner.invoke(cli.app, ["readiness"])
    assert result.exit_code == 0
    assert "SPY" in result.output
    assert "ready" in result.output
    assert "fewer verified sessions than required" in result.output
    assert runner.invoke(cli.app, ["readiness", "TSLA"]).exit_code != 0


def test_backtest_writes_reports_without_a_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_collect(monkeypatch)
    monkeypatch.delenv("DATABASE_URL_DIRECT", raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        cli.app, ["backtest", "--baseline-runs", "5", "--out", str(tmp_path / "reports")]
    )
    assert result.exit_code == 0, result.output
    report = next((tmp_path / "reports").glob("pullback_in_uptrend-*.json"))
    body = json.loads(report.read_text(encoding="utf-8"))
    assert body["strategy"] == "pullback_in_uptrend"
    assert body["assumptions"][0].startswith("Entry at the signal session's close")
    assert "report written to files only" in result.output


def test_verify_restore_refuses_production_before_connecting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DRILL_DATABASE_URL", "postgresql://u:p@db.supabase.co:5432/postgres")
    result = runner.invoke(cli.app, ["ops", "verify-restore", "--manifest", str(manifest)])
    assert result.exit_code != 0
    assert "not local" in str(result.exception)


@respx.mock
def test_doctor_reports_each_check(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL_DIRECT",
        "DATABASE_URL_POOLED",
        "TELEGRAM_BOT_TOKEN",
        "HEALTHCHECK_PING_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "42")
    respx.get(
        url__regex=r"https://(query1\.finance\.yahoo\.com|api\.exchange\.coinbase\.com|www\.alphavantage\.co"
        r"|api\.bnm\.gov\.my).*"
    ).mock(return_value=httpx.Response(200))
    result = runner.invoke(cli.app, ["doctor"], env={"DATABASE_URL_DIRECT": ""})
    assert result.exit_code == 1
    assert "FAIL  database (direct)" in result.output
    assert "PASS  provider coinbase" in result.output
    assert "FAIL  telegram" in result.output
    assert "PASS  owner" in result.output
