"""The showcase export: deterministic, labelled, and telling the three-day story it claims."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lens import cli
from lens.delivery.renderer import TELEGRAM_LIMIT
from lens.demo import LABEL, export, render_json
from lens.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


@pytest.fixture(scope="module")
def payload() -> dict[str, object]:
    return export(load_settings(), (ROOT / "docs" / "STRATEGY.md").read_text(encoding="utf-8"))


def test_export_is_byte_identical_across_runs(payload: dict[str, object]) -> None:
    again = export(load_settings(), (ROOT / "docs" / "STRATEGY.md").read_text(encoding="utf-8"))
    assert render_json(again) == render_json(payload)


def test_days_tell_quiet_setup_then_withdrawn(payload: dict[str, object]) -> None:
    days = payload["days"]
    assert isinstance(days, list)
    assert [d["id"] for d in days] == ["quiet", "setup", "degraded"]
    quiet, setup, degraded = days
    assert quiet["healthy"]
    assert quiet["setups"] == []
    assert "No new setups today." in "\n".join(quiet["sections"])
    assert setup["setups"] == ["KSTL"]
    assert "FERN-USD: price sources disagree on a recent close" in "\n".join(setup["sections"])
    assert degraded["setups"] == []
    assert "No longer a setup: KSTL" in "\n".join(degraded["sections"])
    assert "fear &amp; greed index: unavailable this run" in "\n".join(degraded["sections"])


def test_messages_fit_telegram_and_rejoin_to_the_sections(payload: dict[str, object]) -> None:
    for day in payload["days"]:  # type: ignore[attr-defined]
        assert all(len(m) <= TELEGRAM_LIMIT for m in day["messages"])
        assert "\n\n".join(day["messages"]) == "\n\n".join(day["sections"])


def test_labelled_and_free_of_real_tickers(payload: dict[str, object]) -> None:
    assert payload["label"] == LABEL
    text = render_json(payload)
    for real in ("SPY", "AAPL", "BTC-USD", "Maybank", "1155.KL"):
        assert real not in text


def test_method_tables_come_from_strategy_doc(payload: dict[str, object]) -> None:
    method = payload["method"]
    assert isinstance(method, dict)
    assert method["rules"][0] == ["Rule", "Passes when", "Reason codes"]
    assert any(row[0] == "Trend" for row in method["rules"])


def test_cli_check_passes_on_fresh_output_and_fails_on_stale(tmp_path: Path) -> None:
    out = tmp_path / "demo.json"
    doc = str(ROOT / "docs" / "STRATEGY.md")
    written = runner.invoke(cli.app, ["demo", "export", "--out", str(out), "--strategy-doc", doc])
    assert written.exit_code == 0, written.output
    fresh = runner.invoke(
        cli.app, ["demo", "export", "--out", str(out), "--strategy-doc", doc, "--check"]
    )
    assert fresh.exit_code == 0, fresh.output
    data = json.loads(out.read_text(encoding="utf-8"))
    data["seed"] = 1
    out.write_text(json.dumps(data), encoding="utf-8")
    stale = runner.invoke(
        cli.app, ["demo", "export", "--out", str(out), "--strategy-doc", doc, "--check"]
    )
    assert stale.exit_code == 1
    assert "out of date" in stale.output
