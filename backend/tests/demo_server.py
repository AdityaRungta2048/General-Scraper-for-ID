"""TEST/DEMO ONLY — never used in production.

Runs the real FastAPI app with all platform HTTP routed to the in-memory fake
Twitch/Kick/YouTube world from tests/scenarios.py, so the UI can be exercised end-to-end in
environments without network access to the platforms:

    cd backend && PYTHONPATH=. python -m tests.demo_server   # serves on :8000
"""

from __future__ import annotations

import os

import uvicorn

# No keys preset: the UI opens on the API-keys screen. The fake accepts any key except "wrong".
os.environ.setdefault("DATA_DIR", "./data-demo")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data-demo/demo.db")
os.environ.setdefault("RETRY_BASE_DELAY", "0")

from app.main import create_app
from app.services.context import set_default_transport
from tests.fakes import FakePlatforms
from tests.scenarios import (
    build_all_platforms_world,
    build_kick_world,
    build_twitch_world,
    build_youtube_world,
)


def main() -> None:
    world = FakePlatforms()
    build_kick_world(world)
    build_twitch_world(world)
    build_youtube_world(world)
    build_all_platforms_world(world)
    world.youtube_keys = None
    world.keys_checked = False
    world.failures = [f for f in world.failures if f.times < 10**6]  # keep only transient failures
    set_default_transport(world.transport())
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()
