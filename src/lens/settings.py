"""Product settings (YAML) and secrets (environment). Both are validated at startup."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from lens.domain.instruments import AssetClass, Instrument, Market
from lens.domain.money import TickRule

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OwnerSettings(_Model):
    timezone: str = "Asia/Kuala_Lumpur"
    base_currency: str = "MYR"
    delivery_deadline: time = time(8, 0)
    healthcheck_grace_minutes: int = Field(15, ge=0, le=180)
    detail: Literal["concise", "detailed"] = "concise"

    def today(self, now: datetime) -> date:
        return now.astimezone(ZoneInfo(self.timezone)).date()

    def deadline_on(self, day: date) -> datetime:
        return datetime.combine(day, self.delivery_deadline, ZoneInfo(self.timezone))

    def is_late(self, now: datetime) -> bool:
        return now > self.deadline_on(self.today(now))


class RiskSettings(_Model):
    risk_per_trade_pct: Decimal = Field(Decimal("1.0"), gt=0, le=5)
    max_position_pct: Decimal = Field(Decimal("20.0"), gt=0, le=100)
    max_asset_class_pct: dict[AssetClass, Decimal] = Field(default_factory=dict)


class DataSettings(_Model):
    min_sessions: int = Field(200, ge=50, le=1000)
    cross_check_tolerance_pct: Decimal = Field(Decimal("2.0"), gt=0)
    cross_check_sessions: int = Field(5, ge=1, le=60)
    suspect_jump_pct: dict[AssetClass, Decimal] = Field(default_factory=dict)
    history_sessions: int = Field(420, ge=260)
    degraded_mode_history_sessions: int = Field(260, ge=220)
    single_source_allowed_markets: tuple[Market, ...] = (Market.XKLS,)


class TickBandSetting(_Model):
    below: Decimal | None
    tick: Decimal


class StrategyEntry(_Model):
    enabled: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class HoldingsSettings(_Model):
    chandelier_atr_multiple: Decimal = Field(Decimal("3.0"), gt=0)
    exit_below_ma200_sessions: int = Field(3, ge=1)
    drawdown_review_pct: Decimal = Field(Decimal("25"), gt=0, lt=100)
    stale_review_sessions: int = Field(3, ge=1)


class AlertsSettings(_Model):
    mode: Literal["digest", "immediate"] = "digest"
    quiet_hours: tuple[time, time] = (time(23, 0), time(7, 0))


class ScorecardSettings(_Model):
    window_days: int = Field(365, ge=30)
    min_sample: int = Field(20, ge=5)
    exit_model: Literal["full_to_t2", "half_at_t1_breakeven"] = "full_to_t2"


class NarrativeSettings(_Model):
    enabled: bool = False
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high"] = "low"
    max_calls_per_day: int = Field(3, ge=0, le=20)
    daily_budget_usd: Decimal = Field(Decimal("0.50"), ge=0)
    max_output_tokens: int = Field(1200, ge=200, le=4000)
    deadline_seconds: int = Field(45, ge=5, le=120)
    input_usd_per_mtok: Decimal = Field(Decimal("4.00"), ge=0)
    output_usd_per_mtok: Decimal = Field(Decimal("20.00"), ge=0)
    rates_verified_on: date | None = None


class ContextSettings(_Model):
    fear_greed_url: str = "https://api.alternative.me/fng/"
    headline_feeds: tuple[str, ...] = ()
    max_headlines: int = Field(5, ge=0, le=10)


class WatchlistItem(_Model):
    symbol: str
    asset_class: AssetClass
    name: str | None = None

    def instrument(self) -> Instrument:
        return Instrument.create(self.symbol, self.asset_class, self.name)


class ProviderChoice(_Model):
    primary: str
    cross_check: str | None = None


class ProvidersSettings(_Model):
    markets: dict[Market, ProviderChoice]
    symbols: dict[str, ProviderChoice] = Field(default_factory=dict)

    def for_instrument(self, instrument: Instrument) -> ProviderChoice:
        return self.symbols.get(instrument.symbol) or self.markets[instrument.market]


class Settings(_Model):
    owner: OwnerSettings = OwnerSettings()
    risk: RiskSettings = RiskSettings()
    data: DataSettings = DataSettings()
    ticks: dict[Market, tuple[TickBandSetting, ...]]
    strategies: dict[str, StrategyEntry]
    holdings: HoldingsSettings = HoldingsSettings()
    alerts: AlertsSettings = AlertsSettings()
    scorecard: ScorecardSettings = ScorecardSettings()
    narrative: NarrativeSettings = NarrativeSettings()
    context: ContextSettings = ContextSettings()
    watchlist: tuple[WatchlistItem, ...]
    providers: ProvidersSettings
    benchmarks: dict[Market, str] = Field(default_factory=dict)
    calendar_holidays: dict[Market, tuple[date, ...]] = Field(default_factory=dict)

    @field_validator("watchlist")
    @classmethod
    def _unique_symbols(cls, items: tuple[WatchlistItem, ...]) -> tuple[WatchlistItem, ...]:
        symbols = [item.symbol.upper() for item in items]
        if len(symbols) != len(set(symbols)):
            raise ValueError("watchlist symbols must be unique")
        for item in items:
            item.instrument()
        return items

    @model_validator(mode="after")
    def _every_market_configured(self) -> Settings:
        markets = {item.instrument().market for item in self.watchlist}
        for market in markets:
            if market not in self.ticks:
                raise ValueError(f"no tick table for {market}")
            if market not in self.providers.markets:
                raise ValueError(f"no provider choice for {market}")
        return self

    def tick_rule(self, market: Market) -> TickRule:
        bands = self.ticks[market]
        return TickRule.from_pairs(
            [(None if b.below is None else str(b.below), str(b.tick)) for b in bands]
        )

    def instruments(self) -> tuple[Instrument, ...]:
        return tuple(item.instrument() for item in self.watchlist)


def load_settings(path: Path | str | None = None) -> Settings:
    source = Path(path) if path else DEFAULT_SETTINGS_PATH
    with source.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{source} must contain a mapping")
    return Settings.model_validate(raw)


class Secrets(BaseSettings):
    """Secrets come only from the environment (GitHub secrets, Vercel env, or a local .env)."""

    # A missing GitHub secret arrives as an empty string; treat it as unset, not as a value.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    database_url_direct: SecretStr | None = None
    database_url_pooled: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    owner_telegram_id: int | None = None
    telegram_webhook_secret: SecretStr | None = None
    github_dispatch_token: SecretStr | None = None
    github_repository: str | None = None
    healthcheck_ping_url: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    alpha_vantage_api_key: SecretStr | None = None
    # Private dashboard: a read-only database role, its own cookie key, and the bot's public name
    # for the Telegram Login Widget.
    dashboard_database_url: SecretStr | None = None
    dashboard_session_secret: SecretStr | None = None
    telegram_bot_username: str | None = None

    def secret_values(self) -> list[str]:
        """Every configured secret value, used by the log redactor."""
        values: list[str] = []
        for value in self.__dict__.values():
            if isinstance(value, SecretStr):
                text = value.get_secret_value()
                if len(text) >= 6:
                    values.append(text)
        return values

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if value is None:
            raise MissingSecretError(name.upper())
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        return str(value)

    def owner_id(self) -> int:
        if self.owner_telegram_id is None:
            raise MissingSecretError("OWNER_TELEGRAM_ID")
        return self.owner_telegram_id


class MissingSecretError(RuntimeError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is not set")
        self.name = name
