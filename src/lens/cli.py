"""`lens` command line. Every operation the workflows run is a command here."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Coroutine
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer

from lens.logs import configure_logging, get_logger
from lens.settings import Secrets, Settings, load_settings

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Goldirham Lens: numbers before narrative."
)
cycle_app = typer.Typer(no_args_is_help=True, help="The daily briefing cycle.")
owner_app = typer.Typer(no_args_is_help=True, help="Messages to the owner.")
strategy_app = typer.Typer(no_args_is_help=True, help="Strategy versions and activation.")
webhook_app = typer.Typer(no_args_is_help=True, help="Telegram webhook registration.")
demo_app = typer.Typer(no_args_is_help=True, help="Showcase demo data.")
alerts_app = typer.Typer(no_args_is_help=True, help="Close-based holding alerts.")
for sub, name in (
    (cycle_app, "cycle"),
    (owner_app, "owner"),
    (strategy_app, "strategy"),
    (webhook_app, "webhook"),
    (demo_app, "demo"),
    (alerts_app, "alerts"),
):
    app.add_typer(sub, name=name)

T = TypeVar("T")
SettingsOption = Annotated[Path | None, typer.Option("--settings", help="Path to settings.yaml")]


def _setup(settings_path: Path | None) -> tuple[Settings, Secrets]:
    secrets = Secrets()
    configure_logging(secrets.secret_values())
    return load_settings(settings_path), secrets


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _print(chunks: list[str]) -> None:
    out = "\n\n----- next message -----\n\n".join(chunks)
    sys.stdout.buffer.write(out.encode("utf-8") + b"\n")


@cycle_app.command("run")
def cycle_run(
    trigger: Annotated[
        str, typer.Option(help="schedule_1, schedule_2, dispatch or manual")
    ] = "manual",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Read only: no writes, no sends.")
    ] = False,
    settings_path: SettingsOption = None,
) -> None:
    """Run today's cycle. Exit codes: 0 ok or already done, 1 failed, 3 degraded briefing sent."""
    from lens.pipeline.cycle import EXIT_CODES, run_cycle

    settings, secrets = _setup(settings_path)
    result = _run(
        run_cycle(
            settings,
            secrets,
            trigger=trigger,
            dry_run=dry_run,
            github_run_id=os.environ.get("GITHUB_RUN_ID"),
        )
    )
    get_logger("lens.cli").info(
        "cycle finished",
        outcome=result.outcome.value,
        briefing_date=result.briefing_date.isoformat(),
        detail=result.detail,
    )
    if dry_run:
        _print(result.chunks)
    raise typer.Exit(EXIT_CODES[result.outcome])


@app.command()
def replay(
    day: Annotated[str | None, typer.Option("--date", help="Briefing date, YYYY-MM-DD")] = None,
    settings_path: SettingsOption = None,
) -> None:
    """Rebuild a stored briefing from its inputs and compare it byte for byte."""
    from lens.pipeline.replay import replay_briefing

    _settings, secrets = _setup(settings_path)
    target = date.fromisoformat(day) if day else None
    result = _run(replay_briefing(secrets, target))
    typer.echo(result.summary)
    raise typer.Exit(0 if result.identical else 1)


@app.command()
def readiness(
    symbol: Annotated[str | None, typer.Argument()] = None, settings_path: SettingsOption = None
) -> None:
    """Collect live data and print each asset's readiness and reasons."""
    from lens.data.collect import Collector, calendar_gaps, provider_factories
    from lens.domain.reasons import LABELS

    settings, secrets = _setup(settings_path)
    instruments = [
        i for i in settings.instruments() if symbol is None or i.symbol == symbol.upper()
    ]
    if not instruments:
        raise typer.BadParameter(f"{symbol} is not on the configured watchlist")
    key = (
        secrets.alpha_vantage_api_key.get_secret_value() if secrets.alpha_vantage_api_key else None
    )
    collector = Collector(settings, datetime.now(UTC), factories=provider_factories(key))
    data = _run(collector.collect_all(instruments))
    for item in data.values():
        status = (
            "ready"
            if item.readiness.ready
            else "; ".join(LABELS[r] for r in item.readiness.reasons)
        )
        latest = (
            item.readiness.latest_session.isoformat() if item.readiness.latest_session else "none"
        )
        typer.echo(
            f"{item.instrument.symbol:10} {item.readiness.verified_sessions:4}/{item.readiness.required_sessions}"
            f"  latest {latest}  {status}"
            + (f"  [{'; '.join(item.errors)}]" if item.errors else "")
        )
    for market, days in calendar_gaps(data).items():
        typer.echo(
            f"calendar check {market}: every asset lacks {', '.join(d.isoformat() for d in days)}. "
            "If these were exchange holidays, add them to calendar_holidays in settings.yaml."
        )


@app.command()
def doctor(settings_path: SettingsOption = None) -> None:
    """Check configuration, database, migrations, providers, Telegram and backups."""
    from lens.ops.doctor import run_doctor

    settings, secrets = _setup(settings_path)
    rows = _run(run_doctor(settings, secrets))
    width = max(len(name) for name, _, _ in rows)
    for name, ok, detail in rows:
        typer.echo(f"{'PASS' if ok else 'FAIL'}  {name:{width}}  {detail}")
    raise typer.Exit(0 if all(ok for _, ok, _ in rows) else 1)


@app.command()
def backtest(
    strategy: Annotated[
        str, typer.Option(help="Strategy name from settings.yaml")
    ] = "pullback_in_uptrend",
    sessions: Annotated[int, typer.Option(help="History to fetch per asset (max 1000)")] = 1000,
    baseline_runs: Annotated[int, typer.Option(help="Random-entry baseline runs")] = 200,
    out: Annotated[Path, typer.Option(help="Directory for the Markdown and JSON report")] = Path(
        "reports"
    ),
    settings_path: SettingsOption = None,
) -> None:
    """Replay history through the live rules and save a report (required before activation)."""
    from lens.backtest.engine import AssetHistory
    from lens.backtest.report import build_report
    from lens.data.collect import Collector, provider_factories
    from lens.domain.strategy.base import RiskInputs
    from lens.pipeline.analysis import strategies_from
    from lens.storage.db import Database
    from lens.storage.strategies import StrategyRepo

    settings, secrets = _setup(settings_path)
    configured = next((s for s in strategies_from(settings) if s.name == strategy), None)
    if configured is None:
        raise typer.BadParameter(f"{strategy} is not configured in settings.yaml")
    long_settings = settings.model_copy(
        update={"data": settings.data.model_copy(update={"history_sessions": min(sessions, 1000)})}
    )
    key = (
        secrets.alpha_vantage_api_key.get_secret_value() if secrets.alpha_vantage_api_key else None
    )
    collector = Collector(long_settings, datetime.now(UTC), factories=provider_factories(key))
    data = _run(collector.collect_all(list(settings.instruments())))
    histories = [
        AssetHistory(
            item.instrument,
            tuple(b for b in item.bars if b.usable),
            settings.tick_rule(item.instrument.market),
        )
        for item in data.values()
        if item.bars
    ]
    start = min(h.bars[0].day for h in histories)
    end = max(h.bars[-1].day for h in histories)
    report = build_report(
        histories,
        configured,
        RiskInputs(settings.risk.risk_per_trade_pct, settings.risk.max_position_pct),
        start=start,
        end=end,
        min_sessions=settings.data.min_sessions,
        baseline_runs=baseline_runs,
    )
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"{configured.name}-{configured.version}"
    stem.with_suffix(".md").write_text(report.markdown, encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps(report.body, indent=2), encoding="utf-8")
    typer.echo(report.markdown)
    if secrets.database_url_direct is None:
        typer.echo(
            "DATABASE_URL_DIRECT is not set: report written to files only; activation needs it stored."
        )
        return

    async def store() -> int:
        db = Database(secrets.require("database_url_direct"))
        try:
            async with db.session() as session:
                repo = StrategyRepo(session)
                await repo.ensure(configured)
                return await repo.save_report(
                    version=configured.version,
                    name=configured.name,
                    params=report.body["params"],
                    from_day=start,
                    to_day=end,
                    report=report.body,
                    report_hash=report.report_hash,
                )
        finally:
            await db.dispose()

    report_id = _run(store())
    typer.echo(
        f"stored report {report_id} for {configured.name} {configured.version} ({report.report_hash[:16]})"
    )


@strategy_app.command("list")
def strategy_list(settings_path: SettingsOption = None) -> None:
    """Show configured strategies, their versions, reports and activation."""
    from lens.pipeline.analysis import strategies_from
    from lens.storage.db import Database
    from lens.storage.strategies import StrategyRepo

    settings, secrets = _setup(settings_path)

    async def load() -> list[Any]:
        db = Database(secrets.require("database_url_direct"), rollback_only=True)
        try:
            async with db.session() as session:
                return list(await StrategyRepo(session).versions())
        finally:
            await db.dispose()

    stored = {v.version: v for v in _run(load())}
    for configured in strategies_from(settings):
        info = stored.get(configured.version)
        live = "LIVE" if info and info.activated_at else "not live"
        report = f"report {info.report_id}" if info and info.report_id else "no report linked"
        typer.echo(
            f"{configured.name:22} {configured.version}  enabled={configured.enabled}  {live}  {report}"
        )


@strategy_app.command("activate")
def strategy_activate(name: str, version: str, settings_path: SettingsOption = None) -> None:
    """Make an exact version live. Refused unless a backtest report exists for it."""
    from lens.storage.db import Database
    from lens.storage.strategies import ActivationRefusedError, StrategyRepo

    _settings, secrets = _setup(settings_path)

    async def activate() -> int:
        db = Database(secrets.require("database_url_direct"))
        try:
            async with db.session() as session:
                return await StrategyRepo(session).activate(name, version, datetime.now(UTC))
        finally:
            await db.dispose()

    try:
        report_id = _run(activate())
    except ActivationRefusedError as error:
        typer.echo(f"refused: {error}")
        raise typer.Exit(1) from error
    typer.echo(f"{name} {version} is live (backtest report {report_id})")


@owner_app.command("notify")
def owner_notify(
    text: Annotated[str, typer.Argument()], settings_path: SettingsOption = None
) -> None:
    """Send one plain message to the owner (used by workflow failure steps)."""
    from lens.pipeline.cycle import CycleDeps, notify_owner

    _settings, secrets = _setup(settings_path)
    sent = _run(notify_owner(secrets, CycleDeps(), text[:3500]))
    raise typer.Exit(0 if sent else 1)


@webhook_app.command("set")
def webhook_set(
    url: Annotated[str, typer.Argument(help="https://<project>.vercel.app/api/telegram")],
) -> None:
    """Register the Telegram webhook with the secret token from TELEGRAM_WEBHOOK_SECRET."""
    from lens.delivery.telegram import TelegramClient

    secrets = Secrets()
    configure_logging(secrets.secret_values())

    async def register() -> dict[str, Any]:
        client = TelegramClient(secrets.require("telegram_bot_token"))
        try:
            await client.set_webhook(url, secrets.require("telegram_webhook_secret"))
            return await client.webhook_info()
        finally:
            await client.close()

    info = _run(register())
    typer.echo(
        f"webhook url: {info.get('url')}  pending updates: {info.get('pending_update_count')}"
    )


DEMO_OUT = Path("web/data/demo.json")


@demo_app.command("export")
def demo_export(
    out: Annotated[Path, typer.Option(help="Where the showcase reads its data")] = DEMO_OUT,
    strategy_doc: Annotated[Path, typer.Option(help="Rule tables for the method section")] = Path(
        "docs/STRATEGY.md"
    ),
    check: Annotated[
        bool, typer.Option("--check", help="Fail if the committed file is out of date")
    ] = False,
    settings_path: SettingsOption = None,
) -> None:
    """Run the real pipeline over the seeded synthetic market and write the showcase data."""
    from lens.demo import export, render_json

    settings = load_settings(settings_path)
    text = render_json(export(settings, strategy_doc.read_text(encoding="utf-8")))
    if check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != text:
            typer.echo(f"{out} is out of date; run `lens demo export` and commit the result")
            raise typer.Exit(1)
        typer.echo(f"{out} is up to date")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    typer.echo(f"wrote {out} ({len(text):,} bytes)")


ops_app = typer.Typer(no_args_is_help=True, help="Backups, restore drills and operational events.")
app.add_typer(ops_app, name="ops")


@app.command("backfill")
def backfill_command(symbol: str, settings_path: SettingsOption = None) -> None:
    """Fetch and store history for one asset, then tell the owner its readiness."""
    from lens.ops.jobs import backfill
    from lens.pipeline.cycle import CycleDeps, notify_owner

    settings, secrets = _setup(settings_path)
    text = _run(backfill(settings, secrets, symbol, datetime.now(UTC)))
    typer.echo(text)
    _run(notify_owner(secrets, CycleDeps(), text))


@alerts_app.command("run")
def alerts_run(settings_path: SettingsOption = None) -> None:
    """Send close-based EXIT or REDUCE review alerts (immediate mode only, once per episode)."""
    from lens.ops.jobs import holding_alerts

    settings, secrets = _setup(settings_path)
    sent = _run(holding_alerts(settings, secrets, datetime.now(UTC)))
    typer.echo(f"alerts sent: {len(sent)}")


@ops_app.command("manifest")
def ops_manifest(
    out: Annotated[Path, typer.Option()] = Path("manifest.json"),
    url_env: Annotated[
        str, typer.Option(help="Environment variable holding the URL")
    ] = "DATABASE_URL_DIRECT",
) -> None:
    """Write per-table row counts and checksums for the database in URL_ENV."""
    from lens.ops.backup import manifest
    from lens.storage.db import Database

    configure_logging(Secrets().secret_values())
    url = os.environ.get(url_env)
    if not url:
        raise typer.BadParameter(f"{url_env} is not set")

    async def build() -> dict[str, Any]:
        db = Database(url, rollback_only=True)
        try:
            return await manifest(db)
        finally:
            await db.dispose()

    out.write_text(json.dumps(_run(build()), indent=2, sort_keys=True), encoding="utf-8")
    typer.echo(f"manifest written to {out}")


@ops_app.command(
    "with-pg-env", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def ops_with_pg_env(
    ctx: typer.Context,
    url_env: Annotated[
        str, typer.Option(help="Environment variable holding the URL")
    ] = "DATABASE_URL_DIRECT",
) -> None:
    """Run the command after `--` with PG* variables from URL_ENV, keeping the URL off its arguments."""
    from lens.ops.backup import libpq_environment

    url = os.environ.get(url_env)
    if not url:
        raise typer.BadParameter(f"{url_env} is not set")
    if not ctx.args:
        raise typer.BadParameter("give the command to run after --")
    env = os.environ | libpq_environment(url)
    completed = subprocess.run(ctx.args, env=env, check=False)  # noqa: S603 - the operator's own command
    raise typer.Exit(completed.returncode)


@ops_app.command("verify-restore")
def ops_verify_restore(
    manifest_path: Annotated[Path, typer.Option("--manifest")],
    target_env: Annotated[str, typer.Option()] = "DRILL_DATABASE_URL",
) -> None:
    """Compare a restored drill database with the backup's manifest. Refuses non-drill targets."""
    from lens.ops.backup import compare_manifests, ensure_drill_target, manifest
    from lens.storage.db import Database

    target = os.environ.get(target_env, "")
    ensure_drill_target(target)
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))

    async def build() -> dict[str, Any]:
        db = Database(target, rollback_only=True)
        try:
            return await manifest(db)
        finally:
            await db.dispose()

    result = compare_manifests(expected, _run(build()), now=datetime.now(UTC))
    for difference in result.differences:
        typer.echo(f"DIFF {difference}")
    typer.echo("restore drill passed" if result.ok else "restore drill FAILED")
    raise typer.Exit(0 if result.ok else 1)


@ops_app.command("record")
def ops_record(kind: str, detail: Annotated[str, typer.Option()] = "") -> None:
    """Record an operational event such as backup_ok or restore_drill_ok."""
    from lens.storage.db import Database
    from lens.storage.ops import OpsRepo

    secrets = Secrets()
    configure_logging(secrets.secret_values())

    async def record() -> None:
        db = Database(secrets.require("database_url_direct"))
        try:
            async with db.session() as session:
                await OpsRepo(session).record_event(
                    kind=kind,
                    severity="info",
                    source="workflow",
                    details={"detail": detail[:500]},
                    dedupe_key=f"{kind}:{datetime.now(UTC).isoformat()}",
                )
        finally:
            await db.dispose()

    _run(record())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
