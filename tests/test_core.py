"""Testes offline do catálogo, carteira, pedidos e pagamentos."""
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from config import Settings
from domain import Service, build_payload, money_brl, retail_price, validate_target
from engine import Panel
from payments import Cakto, PaymentError, validate_customer
from provider import ProviderError, ServiceProvider
from storage import Store

RAW = {"service": 42, "name": "Seguidores Instagram", "category": "Instagram",
       "type": "Default", "rate": "10", "min": "100", "max": "10000",
       "description": "Entrega gradual", "refill": True, "cancel": False}


def service(**changes):
    return Service.parse({**RAW, **changes})


def settings(path: Path) -> Settings:
    return Settings(
        bot_token="123456:dummy", api_key="dummy", admin_ids=frozenset({99}),
        allowed_services=frozenset(), db_path=path, max_order_cost=Decimal(5000),
        poll_seconds=60, bot_name="Mais Popular", price_multiplier=Decimal(2),
        min_deposit_brl=Decimal(20), max_deposit_brl=Decimal(5000),
        cakto_client_id="client", cakto_client_secret="secret", cakto_offer_id="offer1",
        cakto_unit_price_brl=5, cakto_pix_expires=3600, fingerprint_secret="fingerprint-secret",
    )


class DomainTests(unittest.TestCase):
    def test_price_is_exactly_double_and_rounded_to_cents(self):
        self.assertEqual(retail_price("10"), Decimal("20.00"))
        self.assertEqual(retail_price("0.001"), Decimal("0.01"))

    def test_money_is_brazilian(self):
        self.assertEqual(money_brl("1234.5"), "R$ 1.234,50")

    def test_platform_first_classification(self):
        self.assertEqual(service().platform, "Instagram")
        self.assertEqual(service(name="Membros Telegram", category="Diversos").platform, "Telegram")

    def test_non_product_and_unsupported_are_hidden(self):
        self.assertFalse(service(name="Serviço teste").sellable)
        self.assertFalse(service(type="Subscriptions").sellable)

    def test_description_removes_vendor_link_and_brand(self):
        item = service(description="Veja SouPopular em https://soupopular.net/services para regras")
        self.assertNotIn("soupopular", item.description.lower())
        self.assertNotIn("http", item.description.lower())

    def test_default_order_cost(self):
        payload, cost = build_payload(service(), "https://instagram.com/p/abc", "250")
        self.assertEqual(cost, Decimal("2.5"))
        self.assertEqual(payload["quantity"], 250)

    def test_invalid_targets(self):
        for value in ("", "http://localhost/a", "http://127.0.0.1/a", "javascript:alert(1)"):
            with self.assertRaises(ValueError):
                validate_target(value)

    def test_customer_validation(self):
        customer = validate_customer("Maria da Silva", "maria@example.com", "67999999999", "52998224725")
        self.assertEqual(customer["phone"], "5567999999999")
        with self.assertRaises(ValueError):
            validate_customer("Maria Silva", "bad", "67999999999", "52998224725")
        with self.assertRaises(ValueError):
            validate_customer("Maria Silva", "maria@example.com", "67999999999", "11111111111")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite3")
        self.store.register_user(1, "user", "User One")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def paid_wallet(self, amount=20):
        row = self.store.create_payment(1, amount * 100, {"name": "User One"})
        self.store.payment_created(row["id"], {
            "id": "cakto-" + row["id"], "refId": "REF", "status": "waiting_payment",
            "checkoutUrl": "https://pay.cakto.com.br/REF",
            "pix": {"qrCode": "000201", "expirationDate": "tomorrow"},
        })
        return self.store.update_payment_status(row["id"], "paid")[0]

    def test_payment_credit_is_idempotent(self):
        row = self.paid_wallet(20)
        self.assertEqual(self.store.balance_cents(1), 2000)
        _, changed = self.store.update_payment_status(row["id"], "paid")
        self.assertFalse(changed)
        self.assertEqual(self.store.balance_cents(1), 2000)

    def test_chargeback_reverses_once(self):
        row = self.paid_wallet(20)
        self.store.update_payment_status(row["id"], "chargedback")
        self.store.update_payment_status(row["id"], "chargedback")
        self.assertEqual(self.store.balance_cents(1), 0)

    def test_paid_payments_remain_in_reconciliation_rotation(self):
        row = self.paid_wallet(20)
        self.store.payment_notified(row["id"], "paid")
        self.assertIn(row["id"], {item["id"] for item in self.store.pending_payments()})

    def test_order_claim_debits_and_refund_is_idempotent(self):
        self.paid_wallet(20)
        row = self.store.create_order(1, service(), {"service": 42, "link": "@abc", "quantity": 100},
                                      Decimal(1), Decimal(2))
        self.assertTrue(self.store.claim_order(row["id"], 1))
        self.assertEqual(self.store.balance_cents(1), 1800)
        self.store.refund_order(row["id"], "refund")
        self.store.refund_order(row["id"], "refund")
        self.assertEqual(self.store.balance_cents(1), 2000)

    def test_reject_and_refund_is_atomic_and_idempotent(self):
        self.paid_wallet(20)
        row = self.store.create_order(1, service(), {"service": 42, "link": "@abc", "quantity": 100},
                                      Decimal(1), Decimal(2))
        self.store.claim_order(row["id"], 1)
        self.store.reject_order_and_refund(row["id"], "refund", "rejected")
        self.store.reject_order_and_refund(row["id"], "refund", "rejected")
        self.assertEqual(self.store.order(row["id"])["state"], "REJECTED")
        self.assertEqual(self.store.balance_cents(1), 2000)

    def test_insufficient_wallet_blocks_claim(self):
        row = self.store.create_order(1, service(), {"service": 42, "link": "@abc", "quantity": 100},
                                      Decimal(1), Decimal(2))
        with self.assertRaisesRegex(ValueError, "Saldo insuficiente"):
            self.store.claim_order(row["id"], 1)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite3")
        self.store.register_user(1, "u", "User")
        pay = self.store.create_payment(1, 2000, {"name": "User"})
        self.store.payment_created(pay["id"], {"id": "pay-id", "status": "waiting_payment",
            "pix": {"qrCode": "code"}, "checkoutUrl": "https://pay.cakto.com.br/X"})
        self.store.update_payment_status(pay["id"], "paid")
        self.api = AsyncMock(spec=ServiceProvider)
        self.api.services.return_value = [service(), service(service=99, type="Subscriptions")]
        self.api.balance.return_value = {"balance": "100", "currency": "BRL"}
        self.api.add.return_value = "77"
        self.cakto = AsyncMock(spec=Cakto)
        self.p = Panel(settings(Path(self.tmp.name) / "db.sqlite3"), self.api, self.cakto, self.store)

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_catalog_filters_and_quote_doubles(self):
        self.assertEqual([x.id for x in await self.p.catalog()], [42])
        row = await self.p.quote(1, 42, "@target", "100")
        self.assertEqual(Decimal(row["provider_cost"]), Decimal(1))
        self.assertEqual(Decimal(row["cost"]), Decimal("2.00"))

    async def test_submit_debits_wallet_and_sends_once(self):
        row = await self.p.quote(1, 42, "@target", "100")
        first = await self.p.submit(row["id"], 1)
        second = await self.p.submit(row["id"], 1)
        self.assertEqual(first["state"], "SUBMITTED")
        self.assertEqual(second["provider_id"], "77")
        self.assertEqual(self.store.balance_cents(1), 1800)
        self.api.add.assert_awaited_once()

    async def test_explicit_rejection_refunds_wallet(self):
        self.api.add.side_effect = ProviderError("recusado")
        row = await self.p.quote(1, 42, "@target", "100")
        result = await self.p.submit(row["id"], 1)
        self.assertEqual(result["state"], "REJECTED")
        self.assertEqual(self.store.balance_cents(1), 2000)

    async def test_payment_minimum(self):
        with self.assertRaises(ValueError):
            await self.p.create_payment(1, 19, {"name": "User"})

    async def test_payment_must_match_offer_unit(self):
        with self.assertRaisesRegex(ValueError, "múltiplo"):
            await self.p.create_payment(1, 22, {"name": "User"})

    async def test_reconcile_refuses_amount_mismatch(self):
        row = self.store.create_payment(1, 2000, {"name": "User"})
        self.store.payment_created(row["id"], {"id": "other-pay-id", "status": "waiting_payment",
            "pix": {"qrCode": "code"}, "checkoutUrl": "https://pay.cakto.com.br/X"})
        self.cakto.order.return_value = {"status": "paid", "baseAmount": "19.99"}
        with self.assertRaises(PaymentError):
            await self.p.reconcile_payment(row["id"])
        self.assertEqual(self.store.balance_cents(1), 2000)

    async def test_payment_uses_persisted_idempotency(self):
        self.cakto.create_pix.return_value = {"id": "new-pay", "refId": "A", "status": "waiting_payment",
            "baseAmount": "20.00", "checkoutUrl": "https://pay.cakto.com.br/A",
            "pix": {"qrCode": "pix-code", "expirationDate": "date"}}
        row = await self.p.create_payment(1, 20, {"name": "User", "email": "u@example.com"})
        self.assertEqual(row["status"], "PENDING")
        args = self.cakto.create_pix.await_args.args
        self.assertEqual(args[1], 20)
        self.assertEqual(args[2], 5)
        self.assertTrue(args[5])


class CaktoClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_pix_request_is_authenticated_and_idempotent(self):
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.path.endswith("/token/"):
                return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
            body = json.loads(request.content)
            self.assertEqual(body["items"][0]["quantity"], 4)
            self.assertEqual(request.headers["x-idempotency-key"], "idem")
            return httpx.Response(201, json={"id": "order", "baseAmount": "20.00",
                "status": "waiting_payment", "pix": {"qrCode": "code"}})
        client = Cakto("id", "secret", transport=httpx.MockTransport(handler))
        try:
            data = await client.create_pix("offer", 20, 5, {
                "name": "User Name", "email": "u@example.com", "phone": "5567999999999",
                "docType": "cpf", "docNumber": "52998224725"}, "finger", "idem", 3600)
            self.assertEqual(data["id"], "order")
            self.assertEqual(len(calls), 2)
        finally:
            await client.close()

    async def test_offer_must_match_configured_unit_price(self):
        def handler(request):
            if request.url.path.endswith("/token/"):
                return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
            return httpx.Response(200, json={"id": "offer", "price": 2, "status": "active", "type": "unique"})
        client = Cakto("id", "secret", transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(PaymentError):
                await client.validate_offer("offer", 1)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
