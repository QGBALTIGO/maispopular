"""Local-only visual QA using live catalog in an isolated wallet. Never submits.

No changes to production authentication. This test app uses a test token, an
in-memory SQLite DB and a provider mock; only catalog reads use the real API.
"""
import asyncio
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock

import uvicorn
from fastapi.responses import HTMLResponse, Response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_webapp import settings, signed_init

from config import Settings
from engine import Panel
from payments import Cakto
from provider import ServiceProvider
from storage import Store
from webapp import create_app


async def catalog():
    api = ServiceProvider(Settings.load().api_key)
    try:
        return await api.services()
    finally:
        await api.close()


if __name__ == "__main__":
    services = asyncio.run(catalog())
    with TemporaryDirectory(prefix="maispopular-preview-", ignore_cleanup_errors=True) as folder:
        path = Path(folder) / "preview.sqlite3"
        store = Store(path)
        provider = AsyncMock(spec=ServiceProvider)
        provider.services.return_value = services
        provider.balance.return_value = {"balance": "0", "currency": "BRL"}
        provider.add.side_effect = AssertionError("Visual preview cannot send orders")
        config = replace(settings(path), admin_ids=frozenset({7}), max_deposit_brl=Decimal(100),
                         cakto_offers={v: f"offer-{v}" for v in range(20,101,5)})
        payments = AsyncMock(spec=Cakto)
        fixture_amounts = {}
        async def create_pix(offer, amount, customer, fingerprint, key, expiry):
            fixture_amounts[key] = amount
            return {"id":key, "baseAmount":str(amount), "status":"waiting_payment",
                    "pix":{"qrCode":"VISUAL-QA-NOT-A-PAYABLE-PIX", "expirationDate":"2099-01-01T00:00:00+00:00"}}
        async def check_pix(key):
            return {"baseAmount":str(fixture_amounts[key]), "status":"paid"}
        payments.create_pix.side_effect = create_pix
        payments.order.side_effect = check_pix
        store.register_user(7, "ana", "Ana Cliente")
        store.register_user(8, "cliente", "Cliente de QA")
        panel = Panel(config, provider, payments, store)
        panel.grant_credit(7,7,"100","Saldo fictício de QA","preview-wallet")
        fixture_service = replace(services[0],name="Pedido exclusivo de QA · avaliação")
        fixture_order = store.create_order(7,fixture_service,{'link':'@fixture','quantity':100},Decimal(1),Decimal(2))
        store.claim_order(fixture_order['id'],7)
        store.mark_order(fixture_order['id'],'COMPLETED')
        app = create_app(panel)
        @app.get("/preview")
        async def preview_page():
            html = (ROOT / "webapp_static" / "index.html").read_text(encoding="utf-8")
            return HTMLResponse(html.replace(
                '<script src="https://telegram.org/js/telegram-web-app.js?63"></script>',
                '<script src="/preview-auth.js"></script>',
            ))

        @app.get("/preview-auth.js")
        async def preview_auth():
            return Response(
                'window.__MAISPOPULAR_PREVIEW_INIT=new URLSearchParams(location.search).get("init")||"";',
                media_type="application/javascript",
            )
        print("Preview uses test auth and isolated wallet; no live orders.", flush=True)
        # Publicly-known test token, not a production credential.
        print("TEST_INIT=" + signed_init(), flush=True)
        try:
            uvicorn.run(app, host="127.0.0.1", port=8039, log_level="warning")
        finally:
            store.close()
