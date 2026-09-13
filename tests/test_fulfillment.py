"""Queue lifecycle and cross-process races using isolated SQLite and fake providers."""

import asyncio
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import test_core
import test_webapp

from bot import poll_fulfillment
from fulfillment import dispatch, manual_transition
from provider import ProviderError, UncertainWrite
from storage import Store


class FulfillmentTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_core.EngineTests.asyncSetUp
    asyncTearDown = test_core.EngineTests.asyncTearDown

    async def queued(self):
        self.api.balance.return_value = {"balance": "0", "currency": "BRL"}
        draft = await self.p.quote(1, 42, "@target", "100")
        return await self.p.submit(draft["id"], 1)

    async def test_insufficient_supplier_accepts_once_and_resumes_once(self):
        row = await self.queued()
        self.assertEqual(row["state"], "QUEUED")
        self.assertEqual(self.store.balance_cents(1), 1800)
        self.api.add.assert_not_awaited()
        await self.p.submit(row["id"], 1)
        self.assertEqual(self.store.balance_cents(1), 1800)
        self.api.balance.return_value = {"balance": "100", "currency": "BRL"}
        await asyncio.gather(dispatch(self.p, row["id"]), dispatch(self.p, row["id"]))
        self.api.add.assert_awaited_once()
        self.assertEqual(self.store.order(row["id"])["state"], "SUBMITTED")

    async def test_manual_claim_wins_during_balance_check_across_connections(self):
        row = await self.queued()
        second = Store(self.p.settings.db_path)
        try:
            other = SimpleNamespace(store=second, require_admin=self.p.require_admin)

            async def balance():
                manual_transition(other, 99, row["id"], "claim", "Atendimento assumido")
                return {"balance": "100", "currency": "BRL"}

            self.api.balance.side_effect = balance
            self.assertEqual((await dispatch(self.p, row["id"]))["state"], "MANUAL")
            self.api.add.assert_not_awaited()
        finally:
            second.close()

    async def test_sending_blocks_manual_claim(self):
        row = await self.queued()
        self.api.balance.return_value = {"balance": "100", "currency": "BRL"}

        async def add(_):
            with self.assertRaises(ValueError):
                manual_transition(
                    self.p, 99, row["id"], "claim", "Tentativa concorrente"
                )
            return "external-1"

        self.api.add.side_effect = add
        self.assertEqual((await dispatch(self.p, row["id"]))["state"], "SUBMITTED")

    async def test_manual_complete_audit_and_no_auto_dispatch(self):
        row = await self.queued()
        manual_transition(self.p, 99, row["id"], "claim", "Pedido assumido")
        manual_transition(
            self.p, 99, row["id"], "complete", "Entrega externa confirmada ref ABC"
        )
        with self.assertRaises(ValueError):
            manual_transition(
                self.p, 99, row["id"], "complete", "Não repetir conclusão"
            )
        await dispatch(self.p, row["id"])
        self.api.add.assert_not_awaited()
        self.assertEqual(self.store.balance_cents(1), 1800)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM fulfillment_audit").fetchone()[
                0
            ],
            2,
        )

    async def test_other_admin_cannot_release_someone_elses_manual_delivery(self):
        self.p.settings = replace(self.p.settings, admin_ids=frozenset({99, 100}))
        row = await self.queued()
        manual_transition(
            self.p, 99, row["id"], "claim", "Entrega assumida pelo primeiro admin"
        )
        for operation in ("release", "complete", "refund"):
            with self.assertRaisesRegex(ValueError, "outro administrador"):
                manual_transition(
                    self.p,
                    100,
                    row["id"],
                    operation,
                    "Outro admin não pode liberar entrega em curso",
                )
        self.assertEqual(self.store.order(row["id"])["state"], "MANUAL")

    async def test_worker_notifies_admin_and_manual_completion_once(self):
        row = await self.queued()
        telegram = SimpleNamespace(send_message=AsyncMock())
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"panel": self.p}), bot=telegram
        )
        await poll_fulfillment(context)
        await poll_fulfillment(context)
        self.assertEqual(telegram.send_message.await_count, 1)
        self.assertEqual(telegram.send_message.call_args.args[0], 99)
        manual_transition(self.p, 99, row["id"], "claim", "Assumir entrega de teste")
        manual_transition(
            self.p, 99, row["id"], "complete", "Entrega de teste confirmada"
        )
        await poll_fulfillment(context)
        await poll_fulfillment(context)
        self.assertEqual(telegram.send_message.await_count, 2)
        self.assertEqual(telegram.send_message.call_args.args[0], 1)
        self.assertIn("concluído", telegram.send_message.call_args.args[1])

    async def test_refund_once_and_non_admin_rejected(self):
        row = await self.queued()
        with self.assertRaises(PermissionError):
            manual_transition(self.p, 1, row["id"], "refund", "Não autorizado")
        manual_transition(
            self.p, 99, row["id"], "refund", "Cliente solicitou cancelamento"
        )
        with self.assertRaises(ValueError):
            manual_transition(self.p, 99, row["id"], "refund", "Repetição cancelamento")
        self.assertEqual(self.store.balance_cents(1), 2000)

    async def test_restart_preserves_queue_and_manual_release(self):
        row = await self.queued()
        manual_transition(self.p, 99, row["id"], "claim", "Assumido manualmente")
        self.store.recover()
        self.assertEqual(self.store.order(row["id"])["state"], "MANUAL")
        manual_transition(
            self.p, 99, row["id"], "release", "Não entregue; devolver à fila"
        )
        self.store.recover()
        self.assertEqual(self.store.order(row["id"])["state"], "QUEUED")
        second = Store(self.p.settings.db_path)
        try:
            self.assertEqual(second.order(row["id"])["state"], "QUEUED")
        finally:
            second.close()

    async def test_changed_cost_holds_queue_without_extra_charge(self):
        row = await self.queued()
        self.api.services.return_value = [test_core.service(rate="20")]
        result = await dispatch(self.p, row["id"])
        self.assertEqual(result["state"], "QUEUED")
        self.assertIn("custo mudou", result["queue_reason"])
        self.assertEqual(self.store.balance_cents(1), 1800)
        self.api.add.assert_not_awaited()

    async def test_definite_funds_error_queues_but_unknown_never_retries(self):
        row = await self.queued()
        self.api.balance.return_value = {"balance": "100", "currency": "BRL"}
        self.api.add.side_effect = ProviderError("Not enough funds")
        self.assertEqual((await dispatch(self.p, row["id"]))["state"], "QUEUED")
        self.api.add.side_effect = UncertainWrite("Unconfirmed response")
        self.assertEqual((await dispatch(self.p, row["id"]))["state"], "UNKNOWN")
        await dispatch(self.p, row["id"])
        self.assertEqual(self.api.add.await_count, 2)
        self.assertEqual(self.store.balance_cents(1), 1800)

    async def test_duplicate_target_and_insufficient_customer_wallet_blocked(self):
        await self.queued()
        same = await self.p.quote(1, 42, "@target", "100")
        with self.assertRaises(ValueError):
            await self.p.submit(same["id"], 1)
        expensive = await self.p.quote(1, 42, "@other", "10000")
        with self.assertRaisesRegex(ValueError, "Saldo insuficiente"):
            await self.p.submit(expensive["id"], 1)
        self.assertEqual(self.store.balance_cents(1), 1800)


class FulfillmentRouteTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_webapp.WebAppRouteTests.asyncSetUp
    asyncTearDown = test_webapp.WebAppRouteTests.asyncTearDown

    async def test_admin_only_manual_routes_and_public_state_privacy(self):
        self.panel.settings = replace(self.panel.settings, admin_ids=frozenset({9}))
        self.store.register_user(7, "ana", "Ana")
        self.panel.grant_credit(9, 7, "20", "Fixture credit", "qa-credit")
        self.api.balance.return_value = {"balance": "0", "currency": "BRL"}
        draft = await self.panel.quote(7, 42, "@target", "100")
        response = await self.client.post(
            f"/api/orders/{draft['id']}/confirm", headers=self.headers, json={}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "QUEUED")
        self.assertNotIn("operacional", response.text)
        self.assertNotIn("queue_reason", response.text)
        denied = await self.client.get("/api/admin/fulfillment", headers=self.headers)
        self.assertEqual(denied.status_code, 403)
        admin = {"X-Telegram-Init-Data": test_webapp.signed_init(9)}
        queue = await self.client.get("/api/admin/fulfillment", headers=admin)
        self.assertEqual(len(queue.json()["orders"]), 1)
        operation = {
            "operation": "claim",
            "note": "Assumir atendimento",
            "confirmation": "CONFIRMO",
        }
        denied = await self.client.post(
            f"/api/admin/fulfillment/{draft['id']}",
            headers=self.headers,
            json=operation,
        )
        self.assertEqual(denied.status_code, 403)
        result = await self.client.post(
            f"/api/admin/fulfillment/{draft['id']}", headers=admin, json=operation
        )
        self.assertEqual(result.json()["state"], "MANUAL")
        repeated = await self.client.post(
            f"/api/admin/fulfillment/{draft['id']}", headers=admin, json=operation
        )
        self.assertEqual(repeated.status_code, 400)
