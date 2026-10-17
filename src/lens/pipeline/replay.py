"""Rebuild a stored briefing from its packed inputs and prove it matches byte for byte."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lens.pipeline.cycle import render
from lens.pipeline.inputs import unpack
from lens.settings import Secrets
from lens.storage.cycles import CycleRepo, StoredBriefing
from lens.storage.db import Database


@dataclass(frozen=True, slots=True)
class ReplayResult:
    identical: bool
    summary: str


def compare(stored: StoredBriefing) -> ReplayResult:
    chunks, document = render(unpack(stored.inputs))
    same_text = chunks == stored.chunks
    same_document = document == stored.document
    identical = same_text and same_document
    detail = (
        "identical"
        if identical
        else (
            f"text {'matches' if same_text else 'differs'}, document {'matches' if same_document else 'differs'}"
        )
    )
    return ReplayResult(
        identical, f"briefing {stored.briefing_date} ({stored.code_version[:8]}): {detail}"
    )


async def replay_briefing(secrets: Secrets, day: date | None) -> ReplayResult:
    db = Database(secrets.require("database_url_direct"), rollback_only=True)
    try:
        async with db.session() as session:
            repo = CycleRepo(session)
            owner = secrets.owner_id()
            stored = await (repo.briefing_on(owner, day) if day else repo.latest_briefing(owner))
        if stored is None:
            return ReplayResult(False, "no stored briefing found")
        return compare(stored)
    finally:
        await db.dispose()
