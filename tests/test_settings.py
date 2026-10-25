from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from lens.domain.instruments import Market
from lens.settings import Secrets, load_settings


def test_shipped_settings_load_and_cover_every_market() -> None:
    settings = load_settings()

    markets = {instrument.market for instrument in settings.instruments()}
    assert markets == {Market.XNYS, Market.XKLS, Market.CRYPTO_UTC}
    assert settings.tick_rule(Market.XKLS).nearest(Decimal("9.876")) == Decimal("9.88")
    assert settings.providers.for_instrument(settings.instruments()[3]).primary == "binance"


def test_owner_today_is_the_owner_calendar_day_not_utc() -> None:
    owner = load_settings().owner

    assert owner.today(datetime(2026, 10, 24, 23, 30, tzinfo=UTC)) == date(2026, 10, 25)
    assert owner.today(datetime(2026, 10, 25, 15, 59, tzinfo=UTC)) == date(2026, 10, 25)


def test_the_delivery_deadline_is_the_owner_local_time_on_the_briefing_day() -> None:
    owner = load_settings().owner
    assert owner.deadline_on(date(2026, 10, 16)) == datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
    assert not owner.is_late(datetime(2026, 10, 16, 0, 0, tzinfo=UTC))
    assert owner.is_late(datetime(2026, 10, 16, 0, 1, tzinfo=UTC))

    london = owner.model_copy(
        update={"timezone": "Europe/London", "delivery_deadline": time(7, 30)}
    )
    assert london.deadline_on(date(2026, 7, 1)) == datetime(2026, 7, 1, 6, 30, tzinfo=UTC)
    assert london.deadline_on(date(2026, 12, 1)) == datetime(2026, 12, 1, 7, 30, tzinfo=UTC)


def _write(tmp_path: Path, mutate: object) -> Path:
    raw = yaml.safe_load(Path("config/settings.yaml").read_text(encoding="utf-8"))
    assert callable(mutate)
    mutate(raw)
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_risk_per_trade_above_five_percent_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, lambda raw: raw["risk"].update(risk_per_trade_pct=6))
    with pytest.raises(ValidationError, match="risk_per_trade_pct"):
        load_settings(path)


def test_duplicate_watchlist_symbols_are_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path, lambda raw: raw["watchlist"].append({"symbol": "AAPL", "asset_class": "stock"})
    )
    with pytest.raises(ValidationError, match="unique"):
        load_settings(path)


def test_unsupported_symbol_is_rejected_at_load(tmp_path: Path) -> None:
    path = _write(
        tmp_path, lambda raw: raw["watchlist"].append({"symbol": "7203.T", "asset_class": "stock"})
    )
    with pytest.raises(ValidationError, match="unsupported market"):
        load_settings(path)


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, lambda raw: raw["owner"].update(timezon="UTC"))
    with pytest.raises(ValidationError, match="timezon"):
        load_settings(path)


def test_secrets_expose_values_for_redaction_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:AAEexampleexampleexampleexample12")
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "42")
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]

    assert "123456789:AAEexampleexampleexampleexample12" in secrets.secret_values()
    assert "AAEexample" not in repr(secrets)
    assert secrets.owner_id() == 42


def test_empty_secret_from_a_missing_github_secret_counts_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL_DIRECT", "")
    assert Secrets(_env_file=None).database_url_direct is None  # type: ignore[call-arg]
