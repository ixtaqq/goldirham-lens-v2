"""Render a BriefingDocument as Telegram HTML sections. Pure: the same document, the same text."""

from __future__ import annotations

from decimal import Decimal
from functools import partial

from lens.delivery.format import (
    MARKET_LABELS,
    esc,
    long_day,
    money,
    pct,
    price,
    r_multiple,
    short_day,
    signed_pct,
)
from lens.domain.briefing import BriefingDocument, ChangeKind, Mode
from lens.domain.evaluation import EventKind
from lens.domain.holdings import MarkStatus
from lens.domain.reasons import LABELS, ReasonCode

TELEGRAM_LIMIT = 4096

_REGIME = {
    "risk_on": "risk-on",
    "neutral": "mixed",
    "risk_off": "risk-off",
    "unknown": "not enough data",
}
_EVENT = {
    EventKind.T1_TOUCHED: "reached T1",
    EventKind.T2_HIT: "reached T2",
    EventKind.STOPPED: "stopped out",
    EventKind.EXPIRED: "expired",
    EventKind.UNVERIFIABLE: "could not be verified past expiry",
}
_MARK = {
    MarkStatus.FRESH: "",
    MarkStatus.STALE: " · stale",
    MarkStatus.DISPUTED: " · latest close disputed",
    MarkStatus.UNAVAILABLE: " · no verified price",
}
_SHORT_REASON = {
    ReasonCode.TREND_OK: "trend up",
    ReasonCode.FLOOR_OK: "above floor",
    ReasonCode.VOLATILITY_OK: "volatility in range",
    ReasonCode.RSI_TRIGGER: "oversold",
    ReasonCode.SUPPORT_TRIGGER: "testing support",
    ReasonCode.BREAKOUT_TRIGGER: "new 52-week high",
    ReasonCode.FUNDAMENTALS_OK: "fundamentals in range",
    ReasonCode.FUNDAMENTALS_UNAVAILABLE: "no fundamentals on file",
}


def _header(doc: BriefingDocument) -> str:
    lines = [f"<b>Goldirham Lens</b> · {long_day(doc.briefing_date)}"]
    if doc.data_as_of:
        lines.append(
            "Data as of "
            + " · ".join(
                f"{MARKET_LABELS[d.market]} {short_day(d.session)}"
                for d in doc.data_as_of
                if d.session
            )
        )
    if doc.mode is Mode.DEGRADED:
        lines.append(
            f"<b>Degraded briefing.</b> {esc(doc.degraded_reason or 'The database was unreachable.')}"
        )
    if doc.late:
        lines.append("<i>Sent late: the scheduled run did not finish by 08:00.</i>")
    return "\n".join(lines)


def _data_status(doc: BriefingDocument) -> str:
    if doc.healthy:
        return "Data: every source verified."
    lines = ["<b>Data status</b>"]
    grouped: dict[tuple[ReasonCode, ...], list[str]] = {}
    for issue in doc.data_issues:
        grouped.setdefault(issue.reasons, []).append(issue.subject)
    for reasons, subjects in grouped.items():
        text = "; ".join(LABELS[r] for r in reasons) or "check required"
        lines.append(f"• {esc(', '.join(subjects))}: {esc(text)}")
    lines.extend(f"• {esc(source)}: unavailable this run" for source in doc.sources_unavailable)
    return "\n".join(lines)


def _portfolio(doc: BriefingDocument) -> str | None:
    section = doc.portfolio
    if section is None:
        return esc(doc.portfolio_note) if doc.portfolio_note else None
    lines = [f"<b>Portfolio</b> · {money(section.total_base, section.base_currency)}"]
    if section.fx_days:
        lines.append("FX dated " + ", ".join(short_day(d) for d in section.fx_days))
    if section.excluded_from_total:
        lines.append(
            "Not in total (no price or FX rate): "
            + ", ".join(esc(s) for s in section.excluded_from_total)
        )
    for line in section.holdings:
        mark = (
            f"{price(line.mark, line.currency)} ({short_day(line.mark_day)})"
            if line.mark is not None and line.mark_day is not None
            else "no verified price"
        )
        change = f" {signed_pct(line.day_change_pct)}" if line.day_change_pct is not None else ""
        weight = f" · {pct(line.weight_pct)} of portfolio" if line.weight_pct is not None else ""
        pnl = (
            f" · {signed_pct(line.unrealized_pct)} unrealised"
            if line.unrealized_pct is not None
            else ""
        )
        lines.append(
            f"<b>{line.review.value}</b> {esc(line.symbol)} {mark}{change}{_MARK[line.mark_status]}{weight}{pnl}"
        )
        if line.review.value != "HOLD":
            why = "; ".join(LABELS[r] for r in line.review_reasons)
            stop = (
                f" Review stop {price(line.review_stop, line.currency)}."
                if line.review_stop is not None
                else ""
            )
            lines.append(f"   {esc(why)}.{stop}")
    if section.exposure_by_asset_class:
        lines.append(
            "Exposure: "
            + " · ".join(f"{esc(k)} {pct(v)}" for k, v in section.exposure_by_asset_class.items())
        )
    return "\n".join(lines)


def _changes(doc: BriefingDocument) -> str | None:
    if not doc.changes:
        return None
    lines = ["<b>What changed</b>"]
    for change in doc.changes:
        match change.kind:
            case ChangeKind.MATERIAL_MOVE:
                assert change.change_pct is not None
                lines.append(f"• {esc(change.symbol)} moved {signed_pct(change.change_pct)}")
            case ChangeKind.NEW_SETUP:
                lines.append(f"• New setup: {esc(change.symbol)}")
            case ChangeKind.REMOVED_SETUP:
                lines.append(f"• No longer a setup: {esc(change.symbol)}")
            case ChangeKind.REVIEW_CHANGED:
                assert change.previous_review
                assert change.review
                lines.append(
                    f"• {esc(change.symbol)} review {change.previous_review.value} → {change.review.value}"
                )
    return "\n".join(lines)


def _setups(doc: BriefingDocument) -> str:
    if not doc.setups:
        return (
            "<b>Setups</b>\nNo new setups today. Most days look like this, and that is the point."
        )
    lines = [f"<b>Setups</b> ({len(doc.setups)})"]
    for s in doc.setups:
        level = partial(_level, s.entry, s.currency)
        lines += [
            "",
            f"<b>{esc(s.symbol)}</b> {esc(s.name)} · {esc(s.strategy)}",
            f"Entry {price(s.entry, s.currency)} · {level('Stop', s.stop)}",
            f"{level('T1', s.t1)} · {level('T2', s.t2)}",
            f"Size {pct(s.size_pct)} of equity{' (capped)' if s.size_capped else ''} · reward to risk {s.reward_risk}",
            "Why: " + esc(", ".join(_SHORT_REASON.get(r, LABELS[r]) for r in s.reasons)),
            f"Invalidation: a close below {price(s.stop, s.currency)}.",
            f"<i>{esc(s.source)} · session {short_day(s.session)} · {esc(s.quality.value.replace('_', ' '))}</i>",
        ]
    return "\n".join(lines)


def _level(entry: Decimal, currency: str, name: str, value: Decimal) -> str:
    return f"{name} {price(value, currency)} ({signed_pct((value / entry - 1) * 100)})"


def _signals(doc: BriefingDocument) -> str | None:
    if not doc.open_signals:
        return None
    lines = ["<b>Open signals</b>"]
    for signal in doc.open_signals:
        detail = (
            f" at {price(signal.price, signal.currency)}"
            if signal.price is not None and signal.currency
            else ""
        )
        r = f" ({r_multiple(signal.r)})" if signal.r is not None else ""
        lines.append(
            f"• {esc(signal.symbol)} {_EVENT[signal.event]}{detail} on {short_day(signal.day)}{r}"
        )
    return "\n".join(lines)


def _market(doc: BriefingDocument) -> str:
    market = doc.market
    lines = ["<b>Market</b>"]
    breadth = (
        f" · {pct(market.breadth_pct)} of watchlist above its 200-day average"
        if market.breadth_pct is not None
        else ""
    )
    lines.append(f"Regime: {_REGIME[market.regime]}{breadth}")
    if market.benchmarks:
        lines.append(
            " · ".join(
                f"{esc(b.symbol)} {price(b.close, b.currency)}"
                + (f" {signed_pct(b.change_pct)}" if b.change_pct is not None else "")
                for b in market.benchmarks
            )
        )
    if market.fear_greed is not None:
        lines.append(
            f"Crypto Fear &amp; Greed: {market.fear_greed} ({esc(market.fear_greed_label or '')})"
        )
    limit = 3 if doc.detail == "concise" else 5
    if market.headlines:
        lines.append("Headlines (context only):")
        lines += [f"• {esc(h.title)} <i>({esc(h.source)})</i>" for h in market.headlines[:limit]]
    return "\n".join(lines)


def _narrative(doc: BriefingDocument) -> str | None:
    if doc.narrative is None:
        return None
    return "<b>In plain words</b>\n" + "\n".join(esc(p) for p in doc.narrative.paragraphs)


def _footer(doc: BriefingDocument) -> str:
    versions = " · ".join(f"{esc(k)} {esc(v)}" for k, v in doc.strategy_versions.items())
    return (
        f"<i>{esc(doc.disclaimer)}</i>\n"
        f"<code>cycle {esc(doc.cycle_id[:8])}{(' · ' + versions) if versions else ''}</code>\n"
        "Ask /why TICKER for the full reasoning on any asset."
    )


def render_sections(doc: BriefingDocument) -> list[str]:
    parts = [
        _header(doc),
        _data_status(doc),
        _portfolio(doc),
        _changes(doc),
        _setups(doc),
        _signals(doc),
        _market(doc),
        _narrative(doc),
        _footer(doc),
    ]
    return [p for p in parts if p]


def render_text(doc: BriefingDocument) -> str:
    return "\n\n".join(render_sections(doc))
