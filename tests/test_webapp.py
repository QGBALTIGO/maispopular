"""Autenticação e rotas do Mini App."""
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import httpx

from config import Settings
from domain import Service
from engine import Panel
from payments import Cakto
from provider import ServiceProvider
from storage import Store
from webapp import create_app, validate_init_data

TOKEN = "123456:unit-test-token"


def signed_init(user_id: int = 7, *, auth_date: int | None = None) -> str:
    values = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "AAE-test",
        "user": json.dumps({"id": user_id, "first_name": "Ana", "username": "ana"},
                           separators=(",", ":"), ensure_ascii=False),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def settings(path: Path) -> Settings:
    return Settings(
        bot_token=TOKEN, api_key="api", admin_ids=frozenset(), allowed_services=frozenset(),
        db_path=path, max_order_cost=Decimal(5000), poll_seconds=60,
        bot_name="Mais Popular", price_multiplier=Decimal(2),
        min_deposit_brl=Decimal(20), max_deposit_brl=Decimal(200),
        cakto_client_id="client", cakto_client_secret="secret",
        cakto_offers={20: "a", 50: "b", 100: "c", 200: "d"},
        cakto_pix_expires=3600, fingerprint_secret="fingerprint",
        webapp_url_file=path.with_name("webapp_url.txt"), bot_username="MaisPopularBot")


class TelegramAuthTests(unittest.TestCase):
    def test_valid_signature_returns_user(self):
        self.assertEqual(validate_init_data(signed_init(123), TOKEN)["id"], 123)

    def test_tampered_or_stale_session_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_init_data(signed_init().replace("Ana", "Bia"), TOKEN)
        with self.assertRaisesRegex(ValueError, "expirou"):
            validate_init_data(signed_init(auth_date=int(time.time()) - 4000), TOKEN)


class WebAppRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "db.sqlite3"
        self.store = Store(path)
        self.api = AsyncMock(spec=ServiceProvider)
        self.api.services.return_value = [Service.parse({
            "service": 42, "name": "Seguidores Instagram", "category": "Instagram",
            "type": "Default", "rate": "10", "min": "100", "max": "10000",
            "description": "Entrega gradual", "refill": True, "cancel": False})]
        self.api.balance.return_value = {"balance": "100", "currency": "BRL"}
        self.api.add.return_value = "provider-1"
        self.cakto = AsyncMock(spec=Cakto)
        self.panel = Panel(settings(path), self.api, self.cakto, self.store)
        self.app = create_app(self.panel)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                        base_url="https://mini.example")
        self.headers = {"X-Telegram-Init-Data": signed_init()}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.store.close()
        self.tmp.cleanup()

    async def test_catalog_requires_telegram_and_exposes_retail_only(self):
        denied = await self.client.get("/api/bootstrap")
        self.assertEqual(denied.status_code, 422)
        bootstrap = await self.client.get("/api/bootstrap", headers=self.headers)
        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.json()["platforms"][0]["name"], "Instagram")
        catalog = await self.client.get("/api/catalog", params={"platform": "Instagram"},
                                        headers=self.headers)
        item = catalog.json()["services"][0]
        self.assertEqual(item["retailRate"], "20")
        self.assertNotIn("provider", json.dumps(item).lower())

    async def test_quote_uses_server_price_and_confirmation_is_idempotent(self):
        self.store.register_user(7, "ana", "Ana")
        payment = self.store.create_payment(7, 2000, {"name": "Ana"})
        self.store.payment_created(payment["id"], {"id": "pay", "status": "waiting_payment",
            "pix": {"qrCode": "code"}, "checkoutUrl": "https://pay.example"})
        self.store.update_payment_status(payment["id"], "paid")
        quote = await self.client.post("/api/quote", headers=self.headers, json={
            "service_id": 42, "target": "@destino", "value": "100"})
        self.assertEqual(quote.status_code, 200)
        self.assertEqual(quote.json()["cost"], "2.00")
        token = quote.json()["id"]
        first = await self.client.post(f"/api/orders/{token}/confirm", headers=self.headers, json={})
        second = await self.client.post(f"/api/orders/{token}/confirm", headers=self.headers, json={})
        self.assertEqual(first.json()["state"], "SUBMITTED")
        self.assertEqual(second.json()["state"], "SUBMITTED")
        self.api.add.assert_awaited_once()

    async def test_private_history_and_wallet_do_not_leak_other_users(self):
        self.store.register_user(8, "other", "Other")
        with self.store.db:
            self.store._adjust_wallet(8, 10000, "deposit", "private-test")
        response = await self.client.get("/api/account", headers=self.headers)
        self.assertEqual(response.json()["balance"], "0.00")
        self.assertEqual(response.json()["movements"], [])
        orders = await self.client.get("/api/orders", headers=self.headers)
        self.assertEqual(orders.json()["orders"], [])
        self.assertEqual((await self.client.get("/api/orders?page=-1", headers=self.headers)).status_code, 422)
        self.assertEqual((await self.client.get("/api/account", headers={"X-Telegram-Init-Data":"invalid"})).status_code, 401)
        self.api.add.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
