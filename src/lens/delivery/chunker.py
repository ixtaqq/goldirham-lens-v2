"""Pack rendered sections into Telegram-sized chunks without splitting a section or a tag."""

from __future__ import annotations

from collections.abc import Sequence

from lens.delivery.renderer import TELEGRAM_LIMIT


def _split_long(section: str, limit: int) -> list[str]:
    """Split one oversized section at line boundaries. Each rendered line closes its own tags."""
    pieces: list[str] = []
    current = ""
    for line in section.split("\n"):
        if len(line) > limit:
            line = line[: limit - 1] + "…"
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            pieces.append(current)
            current = line
        else:
            current = candidate
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
