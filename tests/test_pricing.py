"""Retail pricing permissions, accuracy, persistence and stale checkout protection."""

import unittest
from dataclasses import replace
from decimal import Decimal

import test_core
import test_webapp

import pricing
from fulfillment import dispatch
from storage import Store


class PricingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_core.EngineTests.asyncSetUp
    asyncTearDown = test_core.EngineTests.asyncTearDown

    def change(self, operation="unit", value="0.015", revision=0, service=None):
        return pricing.change(
            self.p,
            99,
            operation,
            value,
            "Alteração de teste",
            revision,
            service
            if service
            else None
            if operation == "multiplier"
            else test_core.service(),
        )

    async def test_unit_override_flows_through_quote_and_charge(self):
        self.change()
        quote = await self.p.quote(1, 42, "@target", "100")
        self.assertEqual(Decimal(quote["cost"]), Decimal("1.50"))
        await self.p.submit(quote["id"], 1)
        self.assertEqual(self.store.balance_cents(1), 1850)
        self.assertEqual(Decimal(quote["provider_cost"]), Decimal(1))

    async def test_global_rule_preserves_custom_and_reset_restores_general(self):
        self.change()
        self.change("multiplier", "3", 1)
        self.assertEqual(self.p.retail_rate(test_core.service()), Decimal(15))
        self.change("reset", "", 2)
        self.assertEqual(self.p.retail_rate(test_core.service()), Decimal(30))

    async def test_high_precision_rounds_only_total_to_cent(self):
        self.change(value="0.000001")
        quote = await self.p.quote(1, 42, "@target", "100")
        self.assertEqual(Decimal(quote["cost"]), Decimal("0.01"))
        self.assertEqual(pricing.unit_label(Decimal("0.000001")), "R$ 0,000001")

    async def test_old_quote_expires_without_debit(self):
        quote = await self.p.quote(1, 42, "@target", "100")
        self.change()
        with self.assertRaisesRegex(ValueError, "preço mudou"):
            await self.p.submit(quote["id"], 1)
        self.assertEqual(self.store.balance_cents(1), 2000)

    async def test_database_claim_rechecks_revision_inside_transaction(self):
        quote = await self.p.quote(1, 42, "@target", "100")
        self.change()
        with self.assertRaisesRegex(ValueError, "atualizados"):
            self.store.claim_order(quote["id"], 1, queued=True, pricing_revision=0)
        self.assertEqual(self.store.balance_cents(1), 2000)

    async def test_paid_queue_keeps_original_price_after_change(self):
        self.api.balance.return_value = {"balance": "0", "currency": "BRL"}
        quote = await self.p.quote(1, 42, "@target", "100")
        await self.p.submit(quote["id"], 1)
        self.change(value="0.03")
        self.api.balance.return_value = {"balance": "100", "currency": "BRL"}
        result = await dispatch(self.p, quote["id"])
        self.assertEqual(result["state"], "SUBMITTED")
        self.assertEqual(Decimal(result["cost"]), Decimal(2))
        self.assertEqual(self.store.balance_cents(1), 1800)

    async def test_stale_admin_and_non_admin_cannot_change_prices(self):
        self.change()
        with self.assertRaisesRegex(ValueError, "Outro preço"):
            self.change(value="0.04")
        with self.assertRaises(PermissionError):
            pricing.change(
                self.p, 1, "unit", "0.04", "Proibido alterar", 1, test_core.service()
            )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM pricing_audit").fetchone()[0], 1
        )

    async def test_invalid_amounts_rejected_and_package_precision(self):
        for value in ("0", "-1", "NaN", "Infinity", "1e-6", "0.0000001", "5001"):
            with self.assertRaises(ValueError):
                self.change(value=value)
        with self.assertRaises(ValueError):
            self.change(value="1.001", service=test_core.service(type="Package"))

    async def test_override_persists_and_reused_service_id_does_not_inherit(self):
        self.change()
        second = Store(self.p.settings.db_path)
        try:
            self.assertEqual(
                second.db.execute(
                    "SELECT unit_price FROM price_overrides WHERE service_id=42"
                ).fetchone()[0],
                "0.015",
            )
        finally:
            second.close()
        self.assertEqual(
            self.p.retail_rate(test_core.service(name="Outro serviço Instagram")),
            Decimal(20),
        )


class PricingRouteTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_webapp.WebAppRouteTests.asyncSetUp
    asyncTearDown = test_webapp.WebAppRouteTests.asyncTearDown

    async def test_admin_update_catalog_and_customer_authorization(self):
        self.panel.settings = replace(self.panel.settings, admin_ids=frozenset({9}))
        admin = {"X-Telegram-Init-Data": test_webapp.signed_init(9)}
        payload = {
            "operation": "unit",
            "service_id": 42,
            "value": "0,015",
            "reason": "Novo preço de teste",
            "revision": 0,
            "confirmation": "CONFIRMO",
        }
        denied = await self.client.post(
            "/api/admin/prices", headers=self.headers, json=payload
        )
        self.assertEqual(denied.status_code, 403)
        denied = await self.client.get("/api/admin/prices", headers=self.headers)
        self.assertEqual(denied.status_code, 403)
        result = await self.client.post(
            "/api/admin/prices", headers=admin, json=payload
        )
        self.assertEqual(result.status_code, 200, result.text)
        result = await self.client.get(
            "/api/catalog?platform=Instagram", headers=self.headers
        )
        item = result.json()["services"][0]
        self.assertEqual(item["unitPriceLabel"], "R$ 0,015")
        self.assertEqual(Decimal(item["retailRate"]), Decimal(15))
        self.assertNotIn("costUnit", item)
        audit = await self.client.get("/api/admin/prices", headers=admin)
        self.assertEqual(audit.json()["revision"], 1)
        self.assertEqual(audit.json()["audit"][0]["admin_id"], 9)
