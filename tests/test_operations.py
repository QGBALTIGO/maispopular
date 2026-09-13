"""Payment and admin authorization/ledger regression tests; no live writes."""
import asyncio
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from test_webapp import WebAppRouteTests, signed_init

from payments import PaymentUnavailable
from ui_common import home_rows
from ui_entry import grant_credit


class OperationsTests(WebAppRouteTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.panel.settings = replace(self.panel.settings, admin_ids=frozenset({9}),
            max_deposit_brl=Decimal(100), cakto_offers={v: f"offer-{v}" for v in range(20,101,5)})
        self.store.register_user(7, "ana", "Ana Cliente")
        self.store.register_user(9, "admin", "Admin Loja")
        self.cakto.create_pix.return_value = {"id":"external-pix", "baseAmount":"25.00", "status":"waiting_payment",
            "pix":{"qrCode":"fixture-not-a-payable-pix", "expirationDate":"2099-01-01T00:00:00+00:00"}}
        self.cakto.order.return_value = {"baseAmount":"25.00", "status":"paid"}
        self.customer = {"request_id":str(uuid4()), "amount":25, "name":"Ana Cliente", "email":"ana@example.com",
                         "phone":"67999999999", "document":"52998224725"}
        self.admin_headers = {"X-Telegram-Init-Data": signed_init(9)}

    async def test_payment_create_retry_scope_and_no_sensitive_output(self):
        first, second = await asyncio.gather(*[self.client.post("/api/payments",json=self.customer,headers=self.headers) for _ in range(2)])
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["id"],second.json()["id"])
        self.assertEqual(self.cakto.create_pix.await_count, 1)
        self.assertTrue(first.json()["qrImage"].startswith("data:image/png;base64,"))
        for field in ("email", "document", "customer_json", "checkoutUrl", "cakto"):
            self.assertNotIn(field,first.text)
        token = first.json()["id"]
        self.assertEqual(self.store.payment(token)["customer_json"],"{}")
        for method,path in [("get",f"/api/payments/{token}"),("post",f"/api/payments/{token}/refresh"),("post",f"/api/payments/{token}/retry")]:
            response = await getattr(self.client,method)(path,headers=self.admin_headers)
            self.assertEqual(response.status_code,404)
        changed = await self.client.post("/api/payments",json={**self.customer,"amount":30},headers=self.headers)
        self.assertEqual(changed.status_code,400)

    async def test_payment_confirmation_credits_once_and_reversal_once(self):
        result = await self.client.post("/api/payments",json=self.customer,headers=self.headers)
        token = result.json()["id"]
        for _ in range(2):
            response = await self.client.post(f"/api/payments/{token}/refresh",headers=self.headers)
            self.assertEqual(response.json()["status"],"PAID")
        self.assertEqual(self.store.balance_cents(7),2500)
        self.store.update_payment_status(token,"refunded")
        self.store.update_payment_status(token,"refunded")
        self.store.update_payment_status(token,"paid")
        self.assertEqual(self.store.payment(token)["status"],"REVERSED")
        self.assertEqual(self.store.balance_cents(7),0)

    async def test_affiliate_endpoint_is_private_and_uses_bot_deep_link(self):
        self.store.bind_referrer(7, 9)
        response = await self.client.get("/api/affiliate", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rate"], 15)
        self.assertTrue(response.json()["link"].endswith("?start=aff_7"))
        self.assertEqual(
            (await self.client.get("/api/affiliate", headers={"X-Telegram-Init-Data": signed_init(8)})).json()["invited"],
            0,
        )

    async def test_broadcast_admin_guard_idempotency_and_recipient_snapshot(self):
        payload = {"request_id": str(uuid4()), "message": "Novidades da loja!", "button_text": "Abrir catálogo",
                   "button_target": "catalog", "confirmation": "CONFIRMO"}
        denied = await self.client.post("/api/admin/broadcasts", json=payload, headers=self.headers)
        self.assertEqual(denied.status_code, 403)
        first = await self.client.post("/api/admin/broadcasts", json=payload, headers=self.admin_headers)
        second = await self.client.post("/api/admin/broadcasts", json=payload, headers=self.admin_headers)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["total"], 2)
        listing = await self.client.get("/api/admin/broadcasts", headers=self.admin_headers)
        self.assertEqual(listing.json()["audience"], 2)
        invalid = await self.client.post("/api/admin/broadcasts", json={**payload, "request_id": str(uuid4()),
                                         "button_text": "", "button_target": "catalog"}, headers=self.admin_headers)
        self.assertEqual(invalid.status_code, 400)

    async def test_interest_tracking_and_raffle_views_are_private(self):
        tracked = await self.client.post(
            "/api/interests",
            json={"platform": "Instagram", "service_id": 42, "label": "Seguidores"},
            headers=self.headers,
        )
        self.assertEqual(tracked.status_code, 200, tracked.text)
        row = self.store.db.execute(
            "SELECT * FROM interest_events WHERE user_id=7 AND status='ACTIVE'"
        ).fetchone()
        self.assertEqual((row["service_id"], row["label"]), (42, "Seguidores"))
        raffle = await self.client.get("/api/raffle", headers=self.headers)
        self.assertEqual(raffle.status_code, 200)
        self.assertEqual(len(raffle.json()["channels"]), 4)
        self.assertTrue(raffle.json()["joinUrl"].endswith("?start=sorteio"))
        self.assertEqual(
            (await self.client.get("/api/admin/raffle", headers=self.headers)).status_code,
            403,
        )
        self.assertEqual(
            (await self.client.get("/api/admin/raffle", headers=self.admin_headers)).status_code,
            200,
        )

    async def test_unknown_payment_resumes_same_provider_key(self):
        self.cakto.create_pix.side_effect = PaymentUnavailable("timeout")
        response = await self.client.post("/api/payments",json=self.customer,headers=self.headers)
        self.assertEqual(response.json()["status"],"UNKNOWN")
        first_key = self.cakto.create_pix.call_args.args[4]
        self.cakto.create_pix.side_effect = None
        response = await self.client.post(f"/api/payments/{response.json()['id']}/retry",headers=self.headers)
        self.assertEqual(response.json()["status"],"PENDING")
        self.assertEqual(self.cakto.create_pix.call_args.args[4],first_key)

    async def test_payment_amounts_and_identity_are_validated(self):
        for update in ({"amount":19},{"amount":105},{"amount":21},{"amount":True},{"document":"00000000000"}):
            response = await self.client.post("/api/payments",json={**self.customer,**update},headers=self.headers)
            self.assertIn(response.status_code,(400,422))
        self.cakto.create_pix.assert_not_awaited()
        response = await self.client.get("/api/bootstrap",headers=self.headers)
        self.assertEqual(response.json()["depositOptions"],list(range(20,101,5)))

    async def test_admin_guard_atomic_credit_and_audit(self):
        payload = {"request_id":str(uuid4()), "user_id":7, "amount":"25,00", "reason":"Bonificação"}
        denied = await self.client.post("/api/admin/credits",json=payload,headers=self.headers)
        self.assertEqual(denied.status_code,403)
        for path in ("/api/admin","/api/admin/users"):
            self.assertEqual((await self.client.get(path,headers=self.headers)).status_code,403)
        results = await asyncio.gather(*[self.client.post("/api/admin/credits",json=payload,headers=self.admin_headers) for _ in range(2)])
        self.assertTrue(all(r.status_code==200 for r in results))
        self.assertEqual(self.store.balance_cents(7),2500)
        self.assertEqual(len(self.store.ledger(7)),1)
        audit = self.store.db.execute("SELECT * FROM admin_credits").fetchone()
        self.assertEqual((audit["admin_id"],audit["user_id"],audit["amount_cents"]),(9,7,2500))
        changed = await self.client.post("/api/admin/credits",json={**payload,"amount":"30"},headers=self.admin_headers)
        self.assertEqual(changed.status_code,400)
        for update in ({"amount":"-1"},{"amount":"NaN"},{"amount":"5001"},{"amount":"0"},{"user_id":456}):
            result = await self.client.post("/api/admin/credits",json={**payload,"request_id":str(uuid4()),**update},headers=self.admin_headers)
            self.assertIn(result.status_code,(400,422))
        self.assertEqual(self.store.balance_cents(7),2500)

    async def test_start_has_only_three_buttons_and_command_replay_is_safe(self):
        buttons = [b for row in home_rows(True,"https://example.com") for b in row]
        self.assertEqual(len(buttons),3)
        self.assertTrue(buttons[0].web_app)
        self.assertIn("view=orders",buttons[1].web_app.url)
        self.assertEqual(buttons[2].url,"https://t.me/suportemaispopular")
        context = SimpleNamespace(args=["7","20","Bonificação"],application=SimpleNamespace(bot_data={"panel":self.panel}))
        update = SimpleNamespace(effective_user=SimpleNamespace(id=9),update_id=123)
        with patch("ui_entry.say",new_callable=AsyncMock):
            await grant_credit(update,context)
            await grant_credit(update,context)
        self.assertEqual(self.store.balance_cents(7),2000)
        update.effective_user.id = 7
        with self.assertRaises(PermissionError):
            await grant_credit(update,context)

    async def test_order_detail_and_actions_enforce_owner(self):
        row = await self.panel.quote(7,42,"https://instagram.com/test","100")
        token = row["id"]
        for method,path in [("get",f"/api/orders/{token}"),("post",f"/api/orders/{token}/refresh"),("post",f"/api/orders/{token}/actions/refill")]:
            result = await getattr(self.client,method)(path,headers=self.admin_headers)
            self.assertIn(result.status_code,(400,404))
        result = await self.client.get(f"/api/orders/{token}",headers=self.headers)
        self.assertEqual(result.status_code,200)

    async def test_refund_after_spending_keeps_wallet_readable(self):
        response = await self.client.post("/api/payments",json=self.customer,headers=self.headers)
        token = response.json()["id"]
        await self.panel.reconcile_payment(token)
        with self.store.db:
            self.store._adjust_wallet(7,-1000,"ORDER","fixture-order","Compra")
        self.store.update_payment_status(token,"refunded")
        response = await self.client.get("/api/account",headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["balance"],"-10.00")

    async def test_order_action_confirmation_is_idempotent(self):
        row = await self.panel.quote(7,42,"https://instagram.com/test","100")
        self.panel.grant_credit(9,7,"20","Teste",str(uuid4()))
        row = await self.panel.submit(row["id"],7)
        self.api.refill.return_value = "refill-1"
        action = await self.client.post(f"/api/orders/{row['id']}/actions/refill",headers=self.headers)
        token = action.json()["id"]
        for _ in range(2):
            result = await self.client.post(f"/api/actions/{token}/confirm",headers=self.headers)
            self.assertEqual(result.json()["state"],"SUBMITTED")
        self.api.refill.assert_awaited_once()
        denied = await self.client.get(f"/api/actions/{token}",headers=self.admin_headers)
        self.assertEqual(denied.status_code,404)

    async def test_user_cannot_resolve_admin_orders(self):
        row = await self.panel.quote(7,42,"https://instagram.com/test","100")
        self.panel.grant_credit(9,7,"20","Teste",str(uuid4()))
        self.store.claim_order(row["id"],7)
        self.store.mark_order(row["id"],"UNKNOWN")
        payload = {"decision":"naocriado","confirmation":"CONFIRMO"}
        path = f"/api/admin/orders/{row['id']}/resolve"
        self.assertEqual((await self.client.post(path,json=payload,headers=self.headers)).status_code,403)
        self.assertEqual((await self.client.post(path,json=payload,headers=self.admin_headers)).status_code,200)
        self.assertEqual(self.store.balance_cents(7),2000)
        self.assertEqual((await self.client.post(path,json=payload,headers=self.admin_headers)).status_code,400)
        self.assertEqual(self.store.balance_cents(7),2000)
