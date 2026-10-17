"""Stable reason codes. Every rejection, quarantine and review carries one or more."""

from __future__ import annotations

from enum import StrEnum


class ReasonCode(StrEnum):
    # data quality and readiness
    INSUFFICIENT_HISTORY = "insufficient_history"
    STALE_SESSION = "stale_session"
    MISSING_SESSION = "missing_session"
    NO_COMPLETED_HISTORY = "no_completed_history"
    DISPUTED_BAR = "disputed_bar"
    SUSPECT_BAR = "suspect_bar"
    INVALID_BAR = "invalid_bar"
    CORPORATE_ACTION_PENDING = "corporate_action_pending"
    SINGLE_SOURCE_UNVERIFIED = "single_source_unverified"
    UNSUPPORTED_MARKET = "unsupported_market"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    # strategy rules
    TREND_FILTER_FAILED = "trend_filter_failed"
    BELOW_FLOOR = "below_floor"
    VOLATILITY_TOO_HIGH = "volatility_too_high"
    NO_PULLBACK_TRIGGER = "no_pullback_trigger"
    NO_BREAKOUT = "no_breakout"
    VOLUME_NOT_CONFIRMED = "volume_not_confirmed"
    REWARD_RISK_BELOW_MINIMUM = "reward_risk_below_minimum"
    FUNDAMENTALS_EXCLUDED = "fundamentals_excluded"
    PRECISION_TOO_COARSE = "precision_too_coarse"
    STOP_NOT_POSITIVE = "stop_not_positive"
    CONCENTRATION_CAP_REACHED = "concentration_cap_reached"
    ASSET_CLASS_CAP_REACHED = "asset_class_cap_reached"
    INDICATORS_UNAVAILABLE = "indicators_unavailable"
    STRATEGY_NOT_ACTIVATED = "strategy_not_activated"
    # passes, recorded so /why can show the whole trail
    TREND_OK = "trend_ok"
    FLOOR_OK = "floor_ok"
    VOLATILITY_OK = "volatility_ok"
    RSI_TRIGGER = "rsi_trigger"
    SUPPORT_TRIGGER = "support_trigger"
    BREAKOUT_TRIGGER = "breakout_trigger"
    FUNDAMENTALS_OK = "fundamentals_ok"
    FUNDAMENTALS_UNAVAILABLE = "fundamentals_unavailable"
    SETUP_BUILT = "setup_built"
    # holding reviews
    BELOW_CHANDELIER_STOP = "below_chandelier_stop"
    BELOW_MA200 = "below_ma200"
    ABOVE_CONCENTRATION_CAP = "above_concentration_cap"
    DRAWDOWN_FROM_PEAK = "drawdown_from_peak"
    MARK_STALE = "mark_stale"
    MARK_UNAVAILABLE = "mark_unavailable"
    HOLDING_OK = "holding_ok"


LABELS: dict[ReasonCode, str] = {
    ReasonCode.INSUFFICIENT_HISTORY: "fewer verified sessions than required",
    ReasonCode.STALE_SESSION: "the latest closed session is missing",
    ReasonCode.MISSING_SESSION: "a session inside the required window is missing",
    ReasonCode.NO_COMPLETED_HISTORY: "no completed price history yet",
    ReasonCode.DISPUTED_BAR: "price sources disagree on a recent close",
    ReasonCode.SUSPECT_BAR: "a bar moved sharply without volume confirmation",
    ReasonCode.INVALID_BAR: "a bar failed basic price checks",
    ReasonCode.CORPORATE_ACTION_PENDING: "a possible split or adjustment is unconfirmed",
    ReasonCode.SINGLE_SOURCE_UNVERIFIED: "only one price source covers this asset",
    ReasonCode.UNSUPPORTED_MARKET: "this market is not supported",
    ReasonCode.PROVIDER_UNAVAILABLE: "the price source was unavailable",
    ReasonCode.TREND_FILTER_FAILED: "the medium-term trend is not clearly up",
    ReasonCode.BELOW_FLOOR: "price is too far below the 200-session average",
    ReasonCode.VOLATILITY_TOO_HIGH: "daily range is too wide for the stop rule",
    ReasonCode.NO_PULLBACK_TRIGGER: "no oversold reading or support test",
    ReasonCode.NO_BREAKOUT: "price has not closed above its 52-week high",
    ReasonCode.VOLUME_NOT_CONFIRMED: "volume did not confirm the move",
    ReasonCode.REWARD_RISK_BELOW_MINIMUM: "reward to risk is below the minimum",
    ReasonCode.FUNDAMENTALS_EXCLUDED: "valuation or growth is outside the allowed range",
    ReasonCode.PRECISION_TOO_COARSE: "levels collapse at the exchange price increment",
    ReasonCode.STOP_NOT_POSITIVE: "the stop would be at or below zero",
    ReasonCode.CONCENTRATION_CAP_REACHED: "position size was limited by the concentration cap",
    ReasonCode.ASSET_CLASS_CAP_REACHED: "the asset-class exposure cap is already reached",
    ReasonCode.INDICATORS_UNAVAILABLE: "indicators could not be computed",
    ReasonCode.STRATEGY_NOT_ACTIVATED: "strategy has no backtest report yet, so it is not live",
    ReasonCode.TREND_OK: "medium-term trend is up",
    ReasonCode.FLOOR_OK: "price is above the floor",
    ReasonCode.VOLATILITY_OK: "volatility is within range",
    ReasonCode.RSI_TRIGGER: "momentum is oversold",
    ReasonCode.SUPPORT_TRIGGER: "price is testing recent support",
    ReasonCode.BREAKOUT_TRIGGER: "price closed above its 52-week high",
    ReasonCode.FUNDAMENTALS_OK: "valuation and growth are within range",
    ReasonCode.FUNDAMENTALS_UNAVAILABLE: "no fundamentals on file; rule skipped",
    ReasonCode.SETUP_BUILT: "a setup passed every rule",
    ReasonCode.BELOW_CHANDELIER_STOP: "closed below the trailing review stop",
    ReasonCode.BELOW_MA200: "closed below the 200-session average for several sessions",
    ReasonCode.ABOVE_CONCENTRATION_CAP: "position is above the concentration cap",
    ReasonCode.DRAWDOWN_FROM_PEAK: "drawdown from the post-entry peak is large",
    ReasonCode.MARK_STALE: "the latest verified price is not current",
    ReasonCode.MARK_UNAVAILABLE: "no verified price is available",
    ReasonCode.HOLDING_OK: "no review rule fired",
}

PASS_CODES: frozenset[ReasonCode] = frozenset(
    {
        ReasonCode.TREND_OK,
        ReasonCode.FLOOR_OK,
        ReasonCode.VOLATILITY_OK,
        ReasonCode.RSI_TRIGGER,
        ReasonCode.SUPPORT_TRIGGER,
        ReasonCode.BREAKOUT_TRIGGER,
        ReasonCode.FUNDAMENTALS_OK,
        ReasonCode.FUNDAMENTALS_UNAVAILABLE,
        ReasonCode.SETUP_BUILT,
        ReasonCode.HOLDING_OK,
        ReasonCode.CONCENTRATION_CAP_REACHED,
    }
)


def label(code: ReasonCode) -> str:
    return LABELS[code]
