"""Every command's parsing, branches and wording, with the repositories replaced by fakes."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

import lens.bot.commands  # noqa: F401
from lens.bot import router
from lens.bot.commands import briefings, ledger, settings_commands, status
from lens.delivery.sender import DeliveryResult
from lens.domain.evaluation import SignalStatus
from lens.domain.instruments import AssetClass, Instrument
from lens.domain.portfolio import FxRate, Transaction, TxKind
from lens.domain.reasons import ReasonCode
from lens.domain.scorecard import SignalRecord
from lens.pipeline.analysis import analyze
from lens.pipeline.compose import compose
from lens.storage.cycles import DeliveryState
from lens.storage.signals import StoredDecision
from lens.storage.strategies import VersionInfo
from tests.bot.fakes import (
    NOW,
    FakeDb,
    FakeDispatcher,
    FakeSession,
    Repo,
    buttons,
    context,
    say,
    tap,
)
from tests.helpers import make_bars
from tests.pipeline.factories import make_inputs

TODAY = date(2026, 10, 16)
INPUTS = make_inputs()
DOCUMENT = compose(INPUTS, analyze(INPUTS)).model_dump(mode="json")
AAPL = Instrument.create("AAPL", AssetClass.STOCK, "Apple")
MAYBANK = Instrument.create("1155.KL", AssetClass.STOCK, "Maybank")


def _stored(day: date = TODAY, **extra: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": 7,
        "briefing_date": day,
        "document": DOCUMENT,
        "chunks": ["<b>first</b>", "second", "third"],
        "message_ids": [1, None, None],
        "delivery_id": 3,
        "delivery_state": DeliveryState.HELD,
    }
    return SimpleNamespace(**(values | extra))


def _decision(**extra: Any) -> StoredDecision:
    values: dict[str, Any] = {
        "symbol": "QQQ",
        "session": date(2026, 10, 15),
        "strategy": "pullback_in_uptrend",
        "strategy_version": "52df5d457a0c",
        "eligible": True,
        "reasons": (ReasonCode.TREND_OK, ReasonCode.NO_PULLBACK_TRIGGER),
        "readiness": (),
        "indicators": {"close": "480.5", "sma50": 470, "rsi14": 41.25, "atr14": 6.1234},
        "setup": None,
    }
    return StoredDecision(**(values | extra))


def _tx(symbol: str, kind: TxKind, day: date, currency: str = "USD", **amounts: str) -> Transaction:
    return Transaction(
        len(symbol) + day.toordinal(),
        symbol,
        kind,
        day,
        currency,
        **{k: Decimal(v) for k, v in amounts.items()},
    )


# ------------------------------------------------------------------ router


async def test_text_without_a_command_and_unknown_commands_are_explained() -> None:
    ctx = context()
    assert "Send a command" in await say(ctx, "hello")
    assert "Unknown command /nope. Try /help." in await say(ctx, "/nope@lensbot")


async def test_buttons_cancel_refuse_unknown_data_and_expired_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(router, "OpsRepo", Repo(consume_action=None))
    ctx = context()
    assert "Cancelled. Nothing was recorded." in await tap(ctx, "cancel")
    assert "not recognised" in await tap(ctx, "zz")
    assert "already used or has expired" in await tap(ctx, "a:gone")


async def test_a_button_for_a_retired_action_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "OpsRepo", Repo(consume_action=("retired", {})))
    assert "no longer supported" in await tap(context(), "a:token")


async def test_a_failing_handler_answers_with_an_error_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefings, "CycleRepo", Repo(latest_briefing=lambda owner: 1 / 0))
    assert "Something went wrong (error " in await say(context(), "/today")


# ------------------------------------------------------------------ briefings


async def test_today_renders_the_latest_stored_briefing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefings, "CycleRepo", Repo(latest_briefing=None))
    assert "No briefing has been stored yet" in await say(context(), "/today")
    monkeypatch.setattr(briefings, "CycleRepo", Repo(latest_briefing=_stored()))
    assert "<b>Goldirham Lens</b>" in await say(context(), "/today")


async def test_briefing_lists_recent_days_or_shows_one(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = Repo(
        recent_briefings=[
            (TODAY, "deterministic", "SENT"),
            (TODAY - timedelta(1), "degraded", None),
        ],
        briefing_on=lambda owner, day: _stored(day) if day == TODAY else None,
    )
    monkeypatch.setattr(briefings, "CycleRepo", repo)
    ctx = context()

    listing = await say(ctx, "/briefing")
    assert "2026-10-16 · deterministic · sent" in listing
    assert "2026-10-15 · degraded · not delivered" in listing
    assert "2026-10-16 · deterministic · sent" in await say(ctx, "/briefing someday")
    assert "<b>Goldirham Lens</b>" in await say(ctx, "/briefing 2026-10-16")
    assert "No briefing stored for 2026-10-01." in await say(ctx, "/briefing 2026-10-01")

    monkeypatch.setattr(briefings, "CycleRepo", Repo(recent_briefings=[]))
    assert "No briefings stored yet." in await say(ctx, "/briefing")


async def test_why_shows_indicators_reasons_and_the_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    setup = {"entry": "480.5", "stop": "468.25", "t1": "498.87", "t2": "517.25", "size_pct": "20"}
    decisions = [
        _decision(reasons=(ReasonCode.TREND_OK, ReasonCode.ASSET_CLASS_CAP_REACHED), setup=setup),
        _decision(strategy="breakout_52w", strategy_version="b1"),
    ]
    monkeypatch.setattr(briefings, "SignalRepo", Repo(latest_decisions=decisions))

    why = await say(context(), "/why qqq")

    assert "<b>QQQ</b> · session 15 Oct" in why
    assert "Readiness: ready" in why
    assert "Close: USD 480.50" in why
    assert "RSI 14: 41.2" in why
    assert "ATR 14: 6.123" in why
    assert "Recent swing low: n/a" in why
    assert "Setup: entry USD 480.50, stop USD 468.25" in why
    assert "Held back: the asset-class exposure cap is reached." in why
    assert "<b>breakout_52w</b> b1" in why
    assert "✗ " in why


async def test_why_explains_missing_and_unready_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = context()
    assert "Usage: /why TICKER" in await say(ctx, "/why")
    monkeypatch.setattr(briefings, "SignalRepo", Repo(latest_decisions=[]))
    assert "No stored decision for TSLA" in await say(ctx, "/why tsla")

    unready = _decision(symbol="1155.KL", readiness=(ReasonCode.INSUFFICIENT_HISTORY,))
    monkeypatch.setattr(briefings, "SignalRepo", Repo(latest_decisions=[unready]))
    why = await say(ctx, "/why 1155.KL")
    assert "Readiness: fewer verified sessions than required" in why
    assert "Not evaluated: the data is not ready." in why
    assert "Close: MYR 480.50" in why


async def test_readiness_reports_each_watched_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    import lens.storage.market

    watched = [AAPL, MAYBANK, Instrument.create("SPY", AssetClass.ETF)]
    decisions = {
        "AAPL": [_decision(symbol="AAPL")],
        "1155.KL": [_decision(symbol="1155.KL", readiness=(ReasonCode.STALE_SESSION,))],
        "SPY": [],
    }
    monkeypatch.setattr(lens.storage.market, "MarketRepo", Repo(watchlist=watched))
    monkeypatch.setattr(
        briefings, "SignalRepo", Repo(latest_decisions=lambda owner, s: decisions[s])
    )
    ctx = context()

    report = await say(ctx, "/readiness")
    assert "• AAPL (15 Oct): ready" in report
    assert "• 1155.KL (15 Oct): " in report
    assert "• SPY: not evaluated yet" in report
    assert "That asset is not on the watchlist." in await say(ctx, "/readiness TSLA")

    monkeypatch.setattr(lens.storage.market, "MarketRepo", Repo(watchlist=[]))
    assert "The watchlist is empty." in await say(ctx, "/readiness")


async def test_scorecard_hides_rates_until_the_sample_is_large_enough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(briefings, "SignalRepo", Repo(records=[]))
    assert "Fewer than 20 resolved signals" in await say(context(), "/scorecard")

    records = [
        SignalRecord(
            TODAY - timedelta(days=60 + i),
            SignalStatus.T2_HIT if i % 3 else SignalStatus.STOPPED,
            bool(i % 3),
            Decimal(3) if i % 3 else Decimal(-1),
            Decimal("2.25") if i % 3 else Decimal(-1),
            TODAY - timedelta(days=40 + i),
            Decimal(3),
            Decimal("-0.5"),
        )
        for i in range(24)
    ]
    monkeypatch.setattr(briefings, "SignalRepo", Repo(records=records))
    card = await say(context(), "/scorecard")
    assert "Resolved 24 · open 0" in card
    assert "Expectancy " in card
    assert "Win rate " in card
    assert "<i>Definitions</i>" in card


async def test_strategy_lists_versions_and_their_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefings, "StrategyRepo", Repo(versions=[]))
    assert "No strategy versions recorded yet." in await say(context(), "/strategy")

    versions = [
        VersionInfo("v1", "pullback_in_uptrend", {}, NOW, 1),
        VersionInfo("v2", "breakout_52w", {}, None, None),
    ]
    report = SimpleNamespace(
        report={
            "full_to_t2": {
                "out_of_sample": {
                    "resolved": 52,
                    "expectancy_r": "0.06",
                    "expectancy_ci90_r": ["-0.31", "0.49"],
                }
            },
            "random_entry_baseline": {"mean_expectancy_r": "0.27"},
        }
    )
    monkeypatch.setattr(
        briefings,
        "StrategyRepo",
        Repo(versions=versions, latest_report=lambda v: report if v == "v1" else None),
    )
    text = await say(context(), "/strategy")
    assert "• pullback_in_uptrend v1: LIVE" in text
    assert "out of sample: 52 trades, expectancy 0.06R (-0.31R to 0.49R)" in text
    assert "random entries: 0.27R" in text
    assert "• breakout_52w v2: not live" in text
    assert "no backtest report yet" in text


# ------------------------------------------------------------------ ledger


@pytest.fixture
def offers(monkeypatch: pytest.MonkeyPatch) -> Repo:
    repo = Repo(create_action="tok")
    monkeypatch.setattr(router, "OpsRepo", repo)
    return repo


async def test_buy_asks_to_confirm_with_the_owner_day(
    monkeypatch: pytest.MonkeyPatch, offers: Repo
) -> None:
    monkeypatch.setattr(ledger, "MarketRepo", Repo(instrument=None))
    monkeypatch.setattr(ledger, "LedgerRepo", Repo(transactions=[]))
    ctx = context(now=NOW.replace(hour=23, minute=30) - timedelta(days=1))  # 07:30 MYT

    text = await say(ctx, "/buy aapl 10 150 1")

    assert "Please confirm:\nBuy 10 AAPL at USD 150.00, fee USD 1.00, on 16 Oct 2026" in text
    assert buttons(ctx) == ["a:tok", "cancel"]
    ((args, _),) = offers.called("create_action")
    assert args[1] == "transaction"
    assert args[2]["day"] == "2026-10-16"
    assert args[2]["asset_class"] == "stock"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/buy", "Usage: /buy TICKER QUANTITY PRICE"),
        ("/buy AAPL ten 5", "quantity must be a number"),
        ("/buy BAD.SYMBOL 1 1", "unsupported market"),
        ("/sell AAPL 5 150", "Not recorded:"),
        ("/split AAPL 4 2026-10-17", "the date must be in the past"),
    ],
)
async def test_ledger_input_problems_are_explained_without_a_button(
    monkeypatch: pytest.MonkeyPatch, offers: Repo, text: str, expected: str
) -> None:
    monkeypatch.setattr(ledger, "MarketRepo", Repo(instrument=None))
    monkeypatch.setattr(ledger, "LedgerRepo", Repo(transactions=[]))
    assert expected in await say(context(), text)
    assert offers.called("create_action") == []


@pytest.mark.parametrize(
    ("text", "described"),
    [
        ("/dividend 1155.KL 120.5", "Dividend MYR 120.50 for 1155.KL on 16 Oct 2026"),
        ("/fee AAPL 2 2026-10-01", "Fee USD 2.00 for AAPL on 1 Oct 2026"),
        ("/split AAPL 4", "Split AAPL 4-for-1 on 16 Oct 2026"),
    ],
)
async def test_other_ledger_entries_are_described_before_confirming(
    monkeypatch: pytest.MonkeyPatch, offers: Repo, text: str, described: str
) -> None:
    monkeypatch.setattr(ledger, "MarketRepo", Repo(instrument=None))
    held = [_tx("AAPL", TxKind.BUY, date(2026, 1, 5), quantity="10", price="100")]
    held.append(_tx("1155.KL", TxKind.BUY, date(2026, 1, 5), "MYR", quantity="100", price="9"))
    monkeypatch.setattr(ledger, "LedgerRepo", Repo(transactions=held))
    assert described in await say(context(), text)


async def test_confirming_records_the_transaction_once(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "symbol": "AAPL",
        "kind": "BUY",
        "quantity": "10",
        "price": "150",
        "fee": "1",
        "day": "2026-10-16",
        "currency": "USD",
        "asset_class": "stock",
    }
    monkeypatch.setattr(router, "OpsRepo", Repo(consume_action=("transaction", payload)))
    monkeypatch.setattr(ledger, "MarketRepo", Repo(ensure_instruments={"AAPL": 5}))
    book = Repo(transactions=[], add=None)
    monkeypatch.setattr(ledger, "LedgerRepo", book)

    assert "Recorded. Buy 10 AAPL at USD 150.00" in await tap(context(), "a:tok")
    ((args, kwargs),) = book.called("add")
    assert args == (42, 5)
    assert kwargs["day"] == date(2026, 10, 16)

    oversell = payload | {"kind": "SELL", "quantity": "50"}
    monkeypatch.setattr(router, "OpsRepo", Repo(consume_action=("transaction", oversell)))
    assert "Not recorded:" in await tap(context(), "a:tok")
    assert len(book.called("add")) == 1


async def test_portfolio_values_holdings_with_dated_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "LedgerRepo", Repo(transactions=[]))
    assert "No open positions." in await say(context(), "/portfolio")

    transactions = [
        _tx("AAPL", TxKind.BUY, date(2026, 1, 5), quantity="10", price="100"),
        _tx("1155.KL", TxKind.BUY, date(2026, 1, 5), "MYR", quantity="100", price="9"),
        _tx("NVDA", TxKind.BUY, date(2026, 1, 5), quantity="1", price="100"),
    ]
    bars = {
        "AAPL": make_bars("AAPL", [148, 150], days=[date(2026, 10, 14), date(2026, 10, 15)]),
        "1155.KL": make_bars("1155.KL", [10], days=[date(2026, 10, 1)]),
    }
    monkeypatch.setattr(ledger, "LedgerRepo", Repo(transactions=transactions))
    monkeypatch.setattr(
        ledger,
        "MarketRepo",
        Repo(
            instruments_by_symbol={"AAPL": AAPL, "1155.KL": MAYBANK},
            load_bars=bars,
            latest_fx=FxRate("USD", "MYR", Decimal("4.40"), date(2026, 10, 15), "test"),
        ),
    )

    text = await say(context(), "/portfolio")

    assert text.startswith("<b>Portfolio</b> · MYR ")
    assert "• AAPL 10 @ USD 150.00 (15 Oct)" in text
    assert "• 1155.KL 100 @ MYR 10.00 (1 Oct) · stale" in text
    assert "• NVDA 1 @ no verified price" in text
    assert "Not in total (no price or FX rate): NVDA" in text
    assert "FX dated 15 Oct" in text
    assert "By currency: " in text


async def test_journal_lists_trades_closed_lots_and_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "LedgerRepo", Repo(transactions=[], notes={}))
    assert "The journal is empty." in await say(context(), "/journal")

    transactions = [
        _tx("AAPL", TxKind.BUY, date(2026, 1, 5), quantity="10", price="100"),
        _tx("AAPL", TxKind.SPLIT, date(2026, 3, 2), ratio="2"),
        _tx("AAPL", TxKind.DIVIDEND, date(2026, 5, 2), amount="3.5"),
        _tx("AAPL", TxKind.SELL, date(2026, 6, 1), quantity="5", price="80"),
    ]
    monkeypatch.setattr(
        ledger, "LedgerRepo", Repo(transactions=transactions, notes={"AAPL": "Services <growth>"})
    )
    text = await say(context(), "/journal")
    assert "• 2026-01-05 BUY AAPL 10 @ USD 100.00" in text
    assert "• 2026-03-02 SPLIT AAPL 2-for-1" in text
    assert "• 2026-05-02 DIVIDEND AAPL USD 3.50" in text
    assert "<b>Closed lots</b>" in text
    assert "• AAPL: Services &lt;growth&gt;" in text


async def test_journal_notes_need_a_known_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "MarketRepo", Repo(instrument_ids={}))
    assert "TSLA is not known yet." in await say(context(), "/journal note tsla big plans")

    book = Repo(set_note=None)
    monkeypatch.setattr(ledger, "MarketRepo", Repo(instrument_ids={"AAPL": 5}))
    monkeypatch.setattr(ledger, "LedgerRepo", book)
    assert "Saved your note for AAPL." in await say(context(), "/journal note aapl long term")
    assert book.called("set_note") == [((42, 5, "long term"), {})]


async def test_watchlist_views_adds_and_removes(monkeypatch: pytest.MonkeyPatch) -> None:
    market = Repo(watchlist=[AAPL, MAYBANK], set_watched=None, instrument=None)
    monkeypatch.setattr(ledger, "MarketRepo", market)
    dispatcher = FakeDispatcher()
    ctx = context(dispatcher=dispatcher)

    assert "• 1155.KL · Maybank · stock" in await say(ctx, "/watchlist")
    added = await say(ctx, "/watchlist add sol-usd")
    assert "Added SOL-USD (crypto). Backfill started" in added
    assert dispatcher.dispatched == [("backfill.yml", {"symbol": "SOL-USD"})]
    assert "Added SPY (etf)." in await say(context(), "/watchlist add spy etf")
    assert "not on a supported market" in await say(ctx, "/watchlist add BAD.SYMBOL")
    assert "TSLA is not on the watchlist." in await say(ctx, "/watchlist remove tsla")

    monkeypatch.setattr(ledger, "MarketRepo", Repo(instrument=AAPL, set_watched=None, watchlist=[]))
    assert "Removed AAPL. Held positions keep receiving prices." in await say(
        ctx, "/watchlist remove aapl"
    )


# ------------------------------------------------------------------ settings


async def test_preferences_validate_and_save(monkeypatch: pytest.MonkeyPatch) -> None:
    ops = Repo(
        set_preference=None,
        preferences=SimpleNamespace(risk_per_trade_pct=None, detail=None, alerts_mode=None),
    )
    monkeypatch.setattr(settings_commands, "OpsRepo", ops)
    ctx = context()

    assert "Risk per setup is now 0.75%." in await say(ctx, "/preferences risk 0.75%")
    assert "Risk must be a number" in await say(ctx, "/preferences risk lots")
    assert "between 0.1% and 5%" in await say(ctx, "/preferences risk 9")
    assert "Briefings will be detailed." in await say(ctx, "/preferences detail DETAILED")
    view = await say(ctx, "/preferences")
    assert "Risk per setup: 1.0%" in view
    assert "Detail: concise" in view
    assert ops.called("set_preference") == [
        ((42,), {"risk_per_trade_pct": Decimal("0.75")}),
        ((42,), {"detail": "detailed"}),
    ]


async def test_alerts_mode_and_quiet_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_commands, "OpsRepo", Repo(set_preference=None))
    ctx = context()
    assert "Alerts arrive in the morning briefing." in await say(ctx, "/alerts digest")
    assert "after each market close" in await say(ctx, "/alerts immediate")
    assert "Quiet hours 22:00 to 06:30 noted." in await say(ctx, "/alerts quiet 22:00-06:30")
    assert "Use /alerts quiet 23:00-07:00" in await say(ctx, "/alerts quiet late")
    assert "Alerts: digest · quiet 23:00-07:00" in await say(ctx, "/alerts")


async def test_feedback_rates_the_latest_briefing(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = context()
    assert "Use /feedback useful" in await say(ctx, "/feedback great")
    monkeypatch.setattr(settings_commands, "CycleRepo", Repo(latest_briefing=None))
    assert "There is no briefing to rate yet." in await say(ctx, "/feedback useful")

    ops = Repo(save_feedback=None)
    monkeypatch.setattr(settings_commands, "CycleRepo", Repo(latest_briefing=_stored()))
    monkeypatch.setattr(settings_commands, "OpsRepo", ops)
    assert "Recorded 'noisy' for 2026-10-16." in await say(ctx, "/feedback noisy too long")
    assert ops.called("save_feedback") == [((42, 7, "noisy", "too long"), {})]


async def test_static_replies() -> None:
    ctx = context()
    assert "Nothing here places trades" in await say(ctx, "/privacy")
    assert "/why TICKER · The full reasoning" in await say(ctx, "/help")
    assert "Goldirham Lens is connected." in await say(ctx, "/start")


# ------------------------------------------------------------------ status


async def test_health_reports_runs_providers_backups_and_drills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace(id=1, briefing_date=TODAY, trigger="schedule_1", status="SENT")
    stage = SimpleNamespace(
        stage="gather", started_at=NOW, finished_at=NOW + timedelta(seconds=12.5), outcome="ok"
    )
    backup = SimpleNamespace(occurred_at=NOW - timedelta(hours=8))
    drill = SimpleNamespace(kind="restore_drill_failed", occurred_at=NOW - timedelta(days=2))
    cycles = Repo(on_time_rate=(6, 7))
    monkeypatch.setattr(status, "CycleRepo", cycles)
    monkeypatch.setattr(status, "OpsRepo", Repo(provider_health=[("yahoo", 40, 2, 850)]))
    db = FakeDb(FakeSession(scalar=[run, backup, drill], scalars=[[stage]]))

    text = await say(context(db), "/health")

    assert "On time (by 08:00): last 7 days 6/7 · last 30 days 6/7" in text
    assert "Last run 2026-10-16 · schedule_1 · sent" in text
    assert "gather 12.5s ok" in text
    assert "Providers (24h): yahoo 38/40 p95 850ms" in text
    assert "Last backup: 2026-10-15 19:00 UTC" in text
    assert "Last restore drill: FAILED 2026-10-14" in text
    (args, _), _ = cycles.called("on_time_rate")
    assert args[1] == TODAY - timedelta(days=7)


async def test_health_with_nothing_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "CycleRepo", Repo(on_time_rate=(0, 0)))
    monkeypatch.setattr(status, "OpsRepo", Repo(provider_health=[]))
    db = FakeDb(FakeSession(scalar=[None, None, None]))
    text = await say(context(db), "/health")
    assert "Last backup: none recorded" in text
    assert "Last restore drill: none recorded" in text
    assert "Last run" not in text


async def test_usage_shows_the_ai_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = SimpleNamespace(calls=1, committed_usd=Decimal("0.12"), unknown=0)
    monkeypatch.setattr(status, "OpsRepo", Repo(usage=summary))
    text = await say(context(), "/usage")
    assert "Narrative disabled · model claude-opus-5-5" in text
    assert "Calls 1/3 · committed USD 0.12 of USD 0.50" in text
    assert "Rates last verified: not verified" in text


async def test_held_offers_resend_and_dismiss(
    monkeypatch: pytest.MonkeyPatch, offers: Repo
) -> None:
    monkeypatch.setattr(status, "CycleRepo", Repo(hold_stale_sending=0, held_deliveries=[]))
    assert "Nothing is held." in await say(context(), "/held")

    monkeypatch.setattr(
        status, "CycleRepo", Repo(hold_stale_sending=0, held_deliveries=[_stored()])
    )
    ctx = context()
    text = await say(ctx, "/held")
    assert "<b>Held briefing</b> 2026-10-16" in text
    assert "1 of 3 messages were accepted" in text
    assert "Resend sends only the 2 not yet accepted." in text
    assert "&lt;b&gt;first&lt;/b&gt;" in text
    assert buttons(ctx) == ["a:tok", "a:tok"]
    assert [a[1] for a, _ in offers.called("create_action")] == ["held_resend", "held_dismiss"]


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (DeliveryResult(DeliveryState.RESENT, 2), "Resent 2 message(s). The briefing is complete."),
        (
            DeliveryResult(DeliveryState.HELD, 1, "deadline"),
            "Resent 1 message(s) before the time limit. The rest are still held",
        ),
        (
            DeliveryResult(DeliveryState.HELD, 0, "TelegramAmbiguousError"),
            "Resend stopped (TelegramAmbiguousError). It is still held",
        ),
    ],
)
async def test_resend_reports_how_far_it_got(
    monkeypatch: pytest.MonkeyPatch, result: DeliveryResult, expected: str
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_deliver(db: object, messenger: object, **kwargs: Any) -> DeliveryResult:
        calls.append(kwargs)
        return result

    monkeypatch.setattr(status, "deliver", fake_deliver)
    monkeypatch.setattr(status, "CycleRepo", Repo(briefing_for_delivery=_stored()))
    monkeypatch.setattr(router, "OpsRepo", Repo(consume_action=("held_resend", {"delivery_id": 3})))

    assert expected in await tap(context(), "a:tok")
    assert calls[0]["deadline"] == status.RESEND_DEADLINE_SECONDS
    assert calls[0]["allowed"] == frozenset({DeliveryState.HELD})


async def test_resend_and_dismiss_of_a_resolved_briefing(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = _stored(delivery_state=DeliveryState.DISMISSED)
    monkeypatch.setattr(
        status, "CycleRepo", Repo(briefing_for_delivery=resolved, dismiss_held=False)
    )
    monkeypatch.setattr(router, "OpsRepo", Repo(consume_action=("held_resend", {"delivery_id": 3})))
    assert "already resolved" in await tap(context(), "a:tok")

    monkeypatch.setattr(
        router, "OpsRepo", Repo(consume_action=("held_dismiss", {"delivery_id": 3}))
    )
    assert "already resolved" in await tap(context(), "a:tok")
    monkeypatch.setattr(status, "CycleRepo", Repo(dismiss_held=True))
    assert "Dismissed. Nothing will be resent." in await tap(context(), "a:tok")


async def test_run_dispatches_only_when_configured() -> None:
    assert "Workflow dispatch is not configured" in await say(context(), "/run")
    dispatcher = FakeDispatcher()
    assert "Started." in await say(context(dispatcher=dispatcher), "/run")
    assert dispatcher.dispatched == [("daily.yml", {"trigger": "dispatch"})]
