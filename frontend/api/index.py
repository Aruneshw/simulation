"""Vercel serverless entry point: serves the RoboVerse FastAPI app under /api.
The Vercel project's Root Directory is `frontend`; the backend package lives in ../backend."""
import sys
from pathlib import Path

here = Path(__file__).resolve()
for base in (here.parents[2] / "backend", here.parents[1] / "backend", Path.cwd() / "backend", Path.cwd().parent / "backend"):
    if (base / "roboverse").is_dir():
        sys.path.insert(0, str(base))
        break

from roboverse.db import init_db  # noqa: E402
from roboverse.main import app  # noqa: E402,F401

init_db()  # ASGI lifespan events are not guaranteed on serverless; create tables up front
