"""Vercel entry point for the Telegram webhook. Vercel serves the ASGI `app` at /api/telegram."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lens.webhook import app

__all__ = ["app"]
