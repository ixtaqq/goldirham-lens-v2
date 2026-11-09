"""Render a BriefingDocument as Telegram HTML sections. Pure: the same document, the same text."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from lens.delivery.format import (
    MARKET_LABELS,
    amount,
    esc,
    long_day,
    money,
    move,
    pct,
    price,
    r_multiple,
    short_day,
    signed_pct,
)
from lens.domain.briefing import BriefingDocument, ChangeKind, Mode, WeekLine
from lens.domain.evaluation import EventKind
from lens.domain.holdings import MarkStatus, ReviewAction
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


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _summary(doc: BriefingDocument) -> str | None:
    """One line on what needs the owner today, counted from the document. None when degraded."""
    if doc.mode is Mode.DEGRADED:
        return None
    reviews = (
        sum(1 for h in doc.portfolio.holdings if h.review is not ReviewAction.HOLD)
        if doc.portfolio
        else 0
    )
    counts = [
        (reviews, "holding to review", "holdings to review"),
        (len(doc.setups), "new setup", "new setups"),
        (len(doc.level_alerts), "price alert reached", "price alerts reached"),
        (len(doc.open_signals), "signal update", "signal updates"),
    ]
    parts = [_plural(n, one, many) for n, one, many in counts if n]
    return " · ".join(parts) + "." if parts else "Quiet day. Nothing to act on."


def _header(doc: BriefingDocument) -> str:
    lines = [f"<b>Goldirham Lens</b> · {long_day(doc.briefing_date)}"]
    if doc.mode is Mode.DEGRADED:
        lines.append(
            f"<b>Degraded briefing.</b> {esc(doc.degraded_reason or 'The database was unreachable.')}"
        )
    if doc.late:
        lines.append("<i>Sent late: the scheduled run did not finish by 08:00.</i>")
    summary = _summary(doc)
    if summary:
        lines.append(summary)
    if doc.data_as_of:
        lines.append(
            "Closes from "
            + " · ".join(
                f"{MARKET_LABELS[d.market]} {short_day(d.session)}"
                for d in doc.data_as_of
                if d.session
            )
        )
    return "\n".join(lines)


def _table(rows: Sequence[Sequence[str]], right: frozenset[int]) -> str:
    """Rows as a monospace block, columns padded to line up. Escaped after padding."""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = [
        "  ".join(
            cell.rjust(width) if i in right else cell.ljust(width)
            for i, (cell, width) in enumerate(zip(row, widths, strict=True))
        ).rstrip()
        for row in rows
    ]
    return "<pre>" + esc("\n".join(lines)) + "</pre>"


def _bar(value: Decimal) -> str:
    """A 0 to 100 reading as ten segments."""
    filled = int((value / 10).quantize(Decimal(1), ROUND_HALF_UP))
    return "▰" * filled + "▱" * (10 - filled)


def _data_notes(doc: BriefingDocument) -> str:
    if doc.healthy:
        return "Data: every source verified."
    grouped: dict[tuple[ReasonCode, ...], list[str]] = {}
    for issue in doc.data_issues:
        grouped.setdefault(issue.reasons, []).append(issue.subject)
    notes = [
        f"• {esc(', '.join(subjects))}: {esc('; '.join(LABELS[r] for r in reasons) or 'check required')}"
        for reasons, subjects in grouped.items()
    ]
    notes += [f"• {esc(source)}: unavailable this run" for source in doc.sources_unavailable]
    return (
        f"<blockquote expandable><b>Data notes</b> · {len(notes)}\n"
        + "\n".join(notes)
        + "</blockquote>"
    )


def _sentence(reasons: tuple[ReasonCode, ...]) -> str:
    text = "; ".join(LABELS[r] for r in reasons)
    return text[:1].upper() + text[1:]


def _portfolio(doc: BriefingDocument) -> str | None:
    section = doc.portfolio
    if section is None:
        return f"<b>Portfolio</b>\n{esc(doc.portfolio_note)}" if doc.portfolio_note else None
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
            f"{price(line.mark, line.currency)}"
            + (f" {move(line.day_change_pct)}" if line.day_change_pct is not None else "")
            if line.mark is not None
            else "no verified price"
        )
        facts = [
            f"{pct(line.weight_pct)} of portfolio" if line.weight_pct is not None else None,
            f"{signed_pct(line.unrealized_pct)} unrealised"
            if line.unrealized_pct is not None
            else None,
            f"close {short_day(line.mark_day)}{_MARK[line.mark_status]}"
            if line.mark_day is not None
            else None,
        ]
        lines += ["", f"<b>{line.review.value}</b> {esc(line.symbol)} · {mark}"]
        lines.append(" · ".join(f for f in facts if f))
        if line.review is not ReviewAction.HOLD:
            stop = (
                f" Review stop {price(line.review_stop, line.currency)}."
                if line.review_stop is not None
                else ""
            )
            lines.append(f"{esc(_sentence(line.review_reasons))}.{stop}")
    if section.exposure_by_asset_class:
        lines += [
            "",
            "Exposure: "
            + " · ".join(f"{esc(k)} {pct(v)}" for k, v in section.exposure_by_asset_class.items()),
        ]
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
    lines = [f"<b>Setups</b> · {len(doc.setups)} new"]
    for s in doc.setups:
        ladder = [
            ("T2", price(s.t2, s.currency), _away(s.t2, s.entry)),
            ("T1", price(s.t1, s.currency), _away(s.t1, s.entry)),
            ("Entry", price(s.entry, s.currency), ""),
            ("Stop", price(s.stop, s.currency), _away(s.stop, s.entry)),
        ]
        lines += [
            "",
            f"<b>{esc(s.symbol)}</b> {esc(s.name)} · {esc(s.strategy)}",
            _table(ladder, right=frozenset({1, 2})),
            f"Size {pct(s.size_pct)} of equity{' (capped)' if s.size_capped else ''} · reward to risk {s.reward_risk}",
            "Why: " + esc(", ".join(_SHORT_REASON.get(r, LABELS[r]) for r in s.reasons)),
            f"Invalidation: a close below {price(s.stop, s.currency)}.",
            f"<i>{esc(s.source)} · session {short_day(s.session)} · {esc(s.quality.value.replace('_', ' '))}</i>",
        ]
    return "\n".join(lines)


def _away(level: Decimal, entry: Decimal) -> str:
    return signed_pct((level / entry - 1) * 100)


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
    lines = [f"<b>Market</b> · {_REGIME[market.regime]}"]
    if market.benchmarks:
        rows = [
            (
                b.symbol,
                b.currency,
                amount(b.close),
                move(b.change_pct) if b.change_pct is not None else "",
            )
            for b in market.benchmarks
        ]
        lines.append(_table(rows, right=frozenset({2})))
    gauges = []
    if market.breadth_pct is not None:
        gauges.append(("Above 200-day", _bar(market.breadth_pct), pct(market.breadth_pct)))
    if market.fear_greed is not None:
        gauges.append(
            (
                "Crypto mood",
                _bar(Decimal(market.fear_greed)),
                f"{market.fear_greed} {market.fear_greed_label or ''}".rstrip(),
            )
        )
    if gauges:
        lines.append(_table(gauges, right=frozenset()))
    return "\n".join(lines)


def _headlines(doc: BriefingDocument) -> str | None:
    limit = 3 if doc.detail == "concise" else 5
    if not doc.market.headlines:
        return None
    return (
        "<blockquote expandable><b>Headlines</b> · context only\n"
        + "\n".join(
            f"• {esc(h.title)} <i>({esc(h.source)})</i>" for h in doc.market.headlines[:limit]
        )
        + "</blockquote>"
    )


def _level_alerts(doc: BriefingDocument) -> str | None:
    if not doc.level_alerts:
        return None
    lines = ["<b>Price alerts</b>"]
    lines += [
        f"• {esc(a.symbol)} closed at {price(a.close, a.currency)} on {short_day(a.day)}, "
        f"{a.direction.value} your {price(a.level, a.currency)} level. This alert is now done."
        for a in doc.level_alerts
    ]
    return "\n".join(lines)


def _week(doc: BriefingDocument) -> str | None:
    week = doc.week
    if week is None:
        return None
    every = (*week.benchmarks, *week.holdings, *week.gainers, *week.decliners)
    if not every:
        return None
    start, end = min(w.from_day for w in every), max(w.to_day for w in every)

    def line(label: str, items: tuple[WeekLine, ...]) -> str | None:
        if not items:
            return None
        return f"{label}: " + " · ".join(
            f"{esc(w.symbol)} {signed_pct(w.change_pct)}"
            + (
                ""
                if (w.from_day, w.to_day) == (start, end)
                else f" ({short_day(w.from_day)} to {short_day(w.to_day)})"
            )
            for w in items
        )

    rows = [
        line("Benchmarks", week.benchmarks),
        line("Holdings", week.holdings),
        line("Up most", week.gainers),
        line("Down most", week.decliners),
    ]
    header = f"<b>This week</b> · {short_day(start)} to {short_day(end)}"
    return "\n".join([header, *(r for r in rows if r)])


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
        _market(doc),
        _portfolio(doc),
        _changes(doc),
        _level_alerts(doc),
        _setups(doc),
        _signals(doc),
        _week(doc),
        _narrative(doc),
        _headlines(doc),
        _data_notes(doc),
        _footer(doc),
    ]
    return [p for p in parts if p]


def render_text(doc: BriefingDocument) -> str:
    return "\n\n".join(render_sections(doc))
