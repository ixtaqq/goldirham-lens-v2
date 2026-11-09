"""Pack rendered sections into Telegram-sized chunks without splitting a section or a tag."""

from __future__ import annotations

import re
from collections.abc import Sequence

from lens.delivery.renderer import TELEGRAM_LIMIT

_BLOCK = re.compile(r"<(/?)(pre|blockquote)\b[^>]*>")
_RESERVE = len("<blockquote expandable>") + len("</blockquote>")


def _open_after(opener: str, line: str) -> str:
    """The block tag still open once `line` is read, given the one open before it."""
    for match in _BLOCK.finditer(line):
        opener = "" if match.group(1) else match.group(0)
    return opener


def _closing(opener: str) -> str:
    match = _BLOCK.match(opener)
    return f"</{match.group(2)}>" if match else ""


def _split_long(section: str, limit: int) -> list[str]:
    """Split one oversized section at line boundaries. Inline tags close on their own line;
    a multi-line pre or blockquote is closed at the split and reopened in the next piece."""
    budget = limit - _RESERVE
    pieces: list[str] = []
    current = ""
    opener = ""
    for line in section.split("\n"):
        if len(line) > budget:
            line = line[: budget - 1] + "…"
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > budget and current:
            pieces.append(current + _closing(opener))
            current = opener + line
        else:
            current = candidate
        opener = _open_after(opener, line)
    if current:
        pieces.append(current)
    return pieces


def chunk(sections: Sequence[str], limit: int = TELEGRAM_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""
    for section in sections:
        parts = [section] if len(section) <= limit else _split_long(section, limit)
        for part in parts:
            candidate = f"{current}\n\n{part}" if current else part
            if len(candidate) > limit:
                chunks.append(current)
                current = part
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks
