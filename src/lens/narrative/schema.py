"""The only shape the model may return. Numbers appear solely as {{f:ID}} placeholders."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Caveat = Literal["uncertainty", "position_sizing", "data_quality"]

CAVEATS: dict[str, str] = {
    "uncertainty": "Targets are scenarios, not forecasts, and missing data limits every conclusion.",
    "position_sizing": "Sizing limits planned risk; a gap can still move past a stop.",
    "data_quality": "Some prices could not be verified today, so read those lines with care.",
}


class AssetNote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    symbol: str
    sentences: list[str] = Field(max_length=3)


class NarrativeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    market: list[str] = Field(max_length=3)
    holdings: list[AssetNote] = Field(max_length=20)
    setups: list[AssetNote] = Field(max_length=3)
    caveat: Caveat


def _strings(max_items: int) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "maxItems": max_items}


def _notes(max_items: int) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": max_items,
        "items": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}, "sentences": _strings(3)},
            "required": ["symbol", "sentences"],
            "additionalProperties": False,
        },
    }


JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "market": _strings(3),
        "holdings": _notes(20),
        "setups": _notes(3),
        "caveat": {"type": "string", "enum": list(CAVEATS)},
    },
    "required": ["market", "holdings", "setups", "caveat"],
    "additionalProperties": False,
}
