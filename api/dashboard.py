"""Vercel entry point for the private dashboard. Deploy it as its own project with its own variables."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lens.dashboard.app import app

__all__ = ["app"]
