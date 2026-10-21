"""Vercel serverless entry point: serves the RoboVerse FastAPI app under /api."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from roboverse.db import init_db  # noqa: E402
from roboverse.main import app  # noqa: E402,F401

init_db()  # ASGI lifespan events are not guaranteed on serverless; create tables up front
