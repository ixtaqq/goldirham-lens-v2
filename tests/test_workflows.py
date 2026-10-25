"""Workflow details the code cannot check at run time, pinned with the reason for each."""

from __future__ import annotations

from pathlib import Path

import yaml


def _run_steps(workflow: str) -> str:
    raw = yaml.safe_load(Path(".github/workflows", workflow).read_text(encoding="utf-8"))
    return "\n".join(
        step.get("run", "") for job in raw["jobs"].values() for step in job.get("steps", [])
    )


def test_the_backup_dumps_only_the_application_schema() -> None:
    # Supabase keeps auth, storage and realtime schemas the app role cannot read and a plain
    # Postgres cannot restore. --schema, unlike a table pattern, also works on an empty database.
    assert "--schema=public" in _run_steps("backup.yml")


def test_the_restore_drill_replaces_the_empty_public_schema() -> None:
    # A --schema=public dump creates schema public, which every new database already has.
    assert "--clean --if-exists" in _run_steps("restore-drill.yml")
