"""Pure composition of the briefing document from inputs and analysis."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from lens.domain.briefing import (
    BriefingDocument,
    ChangeKind,
    ChangeLine,
    DataAsOf,
    DataIssue,
    HoldingLine,
    LevelAlertLine,
    MarketContext,
    Mode,
    NarrativeSection,
    PortfolioSection,
    SetupLine,
    SignalLine,
    WeekLine,
    WeekSection,
)
from lens.domain.evaluation import EventKind
from lens.domain.holdings import ReviewAction
from lens.domain.instruments import Market
from lens.domain.reasons import PASS_CODES, ReasonCode
from lens.pipeline.analysis import Analysis, AssetAnalysis
from lens.pipeline.inputs import CycleInputs

MATERIAL_MOVE_PCT = Decimal(2)
_NOT_SHOWN_AS_WHY = frozenset({ReasonCode.SETUP_BUILT, ReasonCode.CONCENTRATION_CAP_REACHED})
REPORTED_EVENTS = frozenset(
    {
        EventKind.T1_TOUCHED,
        EventKind.STOPPED,
        EventKind.T2_HIT,
        EventKind.EXPIRED,
        EventKind.UNVERIFIABLE,
    }
)


def compose(inputs: CycleInputs, analysis: Analysis) -> BriefingDocument:
    watched = [a for a in analysis.assets.values() if a.asset.watched]

    sessions: dict[Market, date] = {}
    for item in watched:
        if item.asset.closed_sessions:
            day = item.asset.closed_sessions[-1]
            sessions[item.asset.market] = max(day, sessions.get(item.asset.market, day))
    data_as_of = tuple(DataAsOf(market=m, session=sessions[m]) for m in sorted(sessions))

    issues = [
        DataIssue(subject=a.asset.symbol, reasons=a.asset.readiness)
        for a in watched
        if a.asset.readiness
    ]
    issues.extend(
        DataIssue(subject=f"{s.name} {s.version}", reasons=(ReasonCode.STRATEGY_NOT_ACTIVATED,))
        for s in analysis.strategies
        if s.enabled and s.version not in inputs.active_versions
    )

    portfolio = None
    portfolio_note = None
    if analysis.portfolio is not None:
        lines = []
        for holding in analysis.portfolio.holdings:
            review = analysis.reviews.get(holding.symbol)
            asset = analysis.assets.get(holding.symbol)
            lines.append(
                HoldingLine(
                    symbol=holding.symbol,
                    name=asset.asset.name if asset else holding.symbol,
                    currency=holding.currency,
                    quantity=holding.quantity,
                    mark=holding.mark.price,
                    mark_day=holding.mark.day,
                    mark_source=holding.mark.source,
                    mark_status=holding.mark.status,
                    value_base=_q(holding.value_base, "0.01"),
                    unrealized_pct=_q(holding.unrealized_pct, "0.01"),
                    weight_pct=_q(holding.weight_pct, "0.1"),
                    day_change_pct=asset.change_pct if asset else None,
                    review=review.action if review else ReviewAction.REVIEW,
                    review_reasons=review.reasons if review else (ReasonCode.MARK_UNAVAILABLE,),
                    review_stop=review.chandelier_stop.quantize(Decimal("0.0001"))
                    if review and review.chandelier_stop
                    else None,
                )
            )
        severity = {
            ReviewAction.EXIT: 0,
            ReviewAction.REDUCE: 1,
            ReviewAction.REVIEW: 2,
            ReviewAction.HOLD: 3,
        }
        lines.sort(key=lambda line: (severity[line.review], line.symbol))
        snapshot = analysis.portfolio
        portfolio = PortfolioSection(
            base_currency=snapshot.base_currency,
            total_base=snapshot.total_base.quantize(Decimal("0.01")),
            fx_days=snapshot.fx_days,
            excluded_from_total=snapshot.excluded_from_total,
            exposure_by_asset_class={
                k.value: v.quantize(Decimal("0.1"))
                for k, v in sorted(snapshot.exposure_by_asset_class.items())
            },
            holdings=tuple(lines),
        )
    elif not inputs.transactions:
        portfolio_note = "No positions recorded yet. Add one with /buy."

    changes: list[ChangeLine] = []
    if portfolio is not None:
        for line in portfolio.holdings:
            if line.day_change_pct is not None and abs(line.day_change_pct) >= MATERIAL_MOVE_PCT:
                changes.append(
                    ChangeLine(
                        kind=ChangeKind.MATERIAL_MOVE,
                        symbol=line.symbol,
                        change_pct=line.day_change_pct,
                    )
                )
            previous = inputs.previous_reviews.get(line.symbol)
            if previous is not None and previous is not line.review:
                changes.append(
                    ChangeLine(
                        kind=ChangeKind.REVIEW_CHANGED,
                        symbol=line.symbol,
                        previous_review=previous,
                        review=line.review,
                    )
                )
    current_setups = {d.symbol for d in analysis.setups}
    previous_setups = set(inputs.previous.setup_symbols) if inputs.previous else set()
    changes += [
        ChangeLine(kind=ChangeKind.NEW_SETUP, symbol=s)
        for s in sorted(current_setups - previous_setups)
    ]
    changes += [
        ChangeLine(kind=ChangeKind.REMOVED_SETUP, symbol=s)
        for s in sorted(previous_setups - current_setups)
    ]

    setups = []
    for decision in analysis.setups:
        assert decision.setup is not None
        asset = analysis.assets[decision.symbol]
        latest = asset.latest
        assert latest is not None
        setups.append(
            SetupLine(
                symbol=decision.symbol,
                name=asset.asset.name,
                strategy=decision.strategy,
                strategy_version=decision.strategy_version,
                currency=asset.asset.currency,
                session=decision.session,
                source=latest.provider,
                quality=latest.quality,
                entry=decision.setup.entry,
                stop=decision.setup.stop,
                t1=decision.setup.t1,
                t2=decision.setup.t2,
                reward_risk=decision.setup.reward_risk,
                size_pct=decision.setup.size_pct,
                size_capped=decision.setup.size_capped,
                reasons=tuple(
                    r for r in decision.reasons if r in PASS_CODES and r not in _NOT_SHOWN_AS_WHY
                ),
            )
        )

    signal_lines: list[SignalLine] = []
    for update in analysis.signal_updates:
        asset = analysis.assets.get(update.signal.symbol)
        currency = asset.asset.currency if asset else ""
        signal_lines.extend(
            SignalLine(
                symbol=update.signal.symbol,
                event=e.kind,
                day=e.day,
                price=e.price,
                r=_q(e.r, "0.01"),
                currency=currency,
            )
            for e in update.events
            if e.kind in REPORTED_EVENTS
        )

    market = MarketContext(
        regime=analysis.regime,
        breadth_pct=analysis.breadth_pct,
        benchmarks=analysis.benchmarks,
        fear_greed=inputs.context.fear_greed,
        fear_greed_label=inputs.context.fear_greed_label,
        headlines=inputs.context.headlines,
    )
    narrative = None
    mode = Mode(inputs.mode)
    if inputs.narrative is not None:
        narrative = NarrativeSection(
            paragraphs=inputs.narrative.paragraphs, model=inputs.narrative.model
        )
        mode = Mode.NARRATED
    return BriefingDocument(
        briefing_date=inputs.briefing_date,
        generated_at=inputs.generated_at,
        cycle_id=inputs.cycle_id,
        mode=mode,
        late=inputs.late,
        detail=inputs.detail,
        degraded_reason=inputs.degraded_reason,
        data_as_of=data_as_of,
        data_issues=tuple(issues),
        sources_unavailable=inputs.sources_unavailable,
        portfolio=portfolio,
        portfolio_note=portfolio_note,
        changes=tuple(changes),
        setups=tuple(setups),
        open_signals=tuple(signal_lines),
        market=market,
        narrative=narrative,
        strategy_versions={s.name: s.version for s in analysis.strategies if s.enabled},
        week=_week(inputs, analysis),
        level_alerts=tuple(
            LevelAlertLine(
                symbol=hit.alert.symbol,
                currency=analysis.assets[hit.alert.symbol].asset.currency,
                direction=hit.alert.direction,
                level=hit.alert.level,
                day=hit.day,
                close=hit.close,
            )
            for hit in analysis.alert_hits
        ),
    )


def _week_line(item: AssetAnalysis) -> WeekLine | None:
    if item.week is None:
        return None
    return WeekLine(
        symbol=item.asset.symbol,
        currency=item.asset.currency,
        from_day=item.week.from_bar.day,
        to_day=item.week.to_bar.day,
        close=item.week.to_bar.close,
        change_pct=item.week.change_pct,
    )


def _week(inputs: CycleInputs, analysis: Analysis) -> WeekSection | None:
    digest = analysis.settings.digest
    if not digest.enabled or inputs.briefing_date.weekday() != digest.weekday:
        return None

    def lines(symbols: list[str]) -> tuple[WeekLine, ...]:
        found = (_week_line(analysis.assets[s]) for s in symbols if s in analysis.assets)
        return tuple(line for line in found if line is not None)

    watched = lines(sorted(s for s, a in analysis.assets.items() if a.asset.watched))
    holdings = analysis.portfolio.holdings if analysis.portfolio else ()
    return WeekSection(
        benchmarks=lines(list(analysis.settings.benchmarks.values())),
        holdings=lines([h.symbol for h in holdings]),
        gainers=tuple(
            sorted(
                (w for w in watched if w.change_pct > 0), key=lambda w: (-w.change_pct, w.symbol)
            )
        )[: digest.movers],
        decliners=tuple(
            sorted((w for w in watched if w.change_pct < 0), key=lambda w: (w.change_pct, w.symbol))
        )[: digest.movers],
    )


def _q(value: Decimal | None, places: str) -> Decimal | None:
    return None if value is None else value.quantize(Decimal(places))
