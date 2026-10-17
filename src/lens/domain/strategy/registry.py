from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lens.domain.strategy.base import LongSetupParams, Strategy, strategy_version
from lens.domain.strategy.breakout import Breakout52w
from lens.domain.strategy.pullback import PullbackInUptrend

STRATEGIES: dict[str, Strategy] = {
    PullbackInUptrend.name: PullbackInUptrend(),
    Breakout52w.name: Breakout52w(),
}


@dataclass(frozen=True, slots=True)
class ConfiguredStrategy:
    strategy: Strategy
    params: LongSetupParams
    enabled: bool

    @property
    def name(self) -> str:
        return self.strategy.name

    @property
    def version(self) -> str:
        return strategy_version(self.strategy.name, self.params, self.strategy.code_version)


class UnknownStrategyError(KeyError):
    pass


def configure(entries: Mapping[str, tuple[bool, Mapping[str, Any]]]) -> list[ConfiguredStrategy]:
    """Parse `{name: (enabled, params)}` from settings into validated strategies."""
    configured = []
    for name, (enabled, raw_params) in entries.items():
        strategy = STRATEGIES.get(name)
        if strategy is None:
            raise UnknownStrategyError(name)
        configured.append(
            ConfiguredStrategy(strategy, strategy.params_model.model_validate(raw_params), enabled)
        )
    return configured
