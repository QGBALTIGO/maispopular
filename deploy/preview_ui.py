"""Local-only visual QA using live catalog in an isolated wallet. Never submits.

No changes to production authentication. This test app uses a test token, an
in-memory SQLite DB and a provider mock; only catalog reads use the real API.
"""
import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from config import Settings
from engine import Panel
from payments import Cakto
from provider import ServiceProvider
from storage import Store
from test_webapp import settings, signed_init
from webapp import create_app


async def catalog():
    api = ServiceProvider(Settings.load().api_key)
    try:
        return await api.services()
    finally:
        await api.close()


if __name__ == "__main__":
    services = asyncio.run(catalog())
    with TemporaryDirectory(prefix="maispopular-preview-") as folder:
        path = Path(folder) / "preview.sqlite3"
        store = Store(path)
        provider = AsyncMock(spec=ServiceProvider)
        provider.services.return_value = services
        provider.balance.return_value = {"balance": "1000", "currency": "BRL"}
        provider.add.side_effect = AssertionError("Visual preview cannot send orders")
        app = create_app(Panel(settings(path), provider, AsyncMock(spec=Cakto), store))
        print("Preview uses test auth and isolated wallet; no live orders.", flush=True)
        # Publicly-known test token, not a production credential.
        print("TEST_INIT=" + signed_init(), flush=True)
        uvicorn.run(app, host="127.0.0.1", port=8039, log_level="warning")
