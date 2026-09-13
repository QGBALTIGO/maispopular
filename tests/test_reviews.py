"""Reviews must come from the buyer of a charged, completed real order."""

import unittest
from decimal import Decimal

import test_webapp

import reviews
from storage import Store


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_webapp.WebAppRouteTests.asyncSetUp
    asyncTearDown = test_webapp.WebAppRouteTests.asyncTearDown

    def order(self, completed=True, charged=True):
        self.store.register_user(7, "ana", "Ana")
        if charged:
            self.store._adjust_wallet(
                7,
                2000,
                "ADMIN",
                f"fixture:{self.store.db.total_changes}",
                "Isolated test",
            )
            self.store.db.commit()
        service = self.api.services.return_value[0]
        row = self.store.create_order(
            7,
            service,
            {"service": 42, "link": "@fixture", "quantity": 100},
            Decimal(1),
            Decimal(2),
        )
        if charged:
            self.store.claim_order(row["id"], 7)
        if completed:
            self.store.mark_order(row["id"], "COMPLETED")
        return row["id"]

    async def send(self, token, **overrides):
        return await self.client.post(
            f"/api/orders/{token}/review",
            headers=self.headers,
            json={
                "name": "Cliente QA",
                "rating": 4,
                "comment": "Avaliação de teste isolado.",
                "consent": True,
                **overrides,
            },
        )

    async def test_empty_does_not_invent_ratings(self):
        result = await self.client.get("/api/reviews", headers=self.headers)
        self.assertEqual(
            result.json(),
            {"count": 0, "average": None, "hasMore": False, "reviews": []},
        )

    async def test_completed_charged_order_can_review_once_and_average_is_real(self):
        token = self.order()
        self.assertTrue(
            (
                await self.client.get(f"/api/orders/{token}", headers=self.headers)
            ).json()["canReview"]
        )
        self.assertEqual((await self.send(token)).status_code, 200)
        self.assertEqual((await self.send(token)).status_code, 200)
        self.assertEqual((await self.send(token, rating=5)).status_code, 400)
        data = (await self.client.get("/api/reviews", headers=self.headers)).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["average"], "4.0")
        self.assertTrue(data["reviews"][0]["verified"])
        self.assertEqual(
            set(data["reviews"][0]),
            {"name", "rating", "comment", "createdAt", "verified"},
        )
        self.assertNotIn(token, str(data))
        detail = (
            await self.client.get(f"/api/orders/{token}", headers=self.headers)
        ).json()
        self.assertFalse(detail["canReview"])
        self.assertTrue(detail["reviewed"])

    async def test_pending_and_uncharged_orders_cannot_claim_verified_purchase(self):
        for completed, charged in [(False, True), (True, False), (False, False)]:
            token = self.order(completed, charged)
            self.assertEqual((await self.send(token)).status_code, 400)
            self.store.mark_order(token, "ABORTED")
        self.assertEqual(reviews.listing(self.store)["count"], 0)

    async def test_cannot_review_another_customer_order(self):
        token = self.order()
        self.headers = {"X-Telegram-Init-Data": test_webapp.signed_init(8)}
        self.assertEqual((await self.send(token)).status_code, 404)

    async def test_consent_rating_and_name_validation(self):
        token = self.order()
        for changes in (
            {"consent": False},
            {"rating": 0},
            {"rating": 6},
            {"rating": "5"},
            {"rating": True},
            {"name": "<script>"},
            {"comment": "x"},
            {"comment": "x" * 601},
            {"verified": True},
        ):
            self.assertEqual((await self.send(token, **changes)).status_code, 422)
        self.assertEqual(reviews.listing(self.store)["count"], 0)

    async def test_provider_completion_and_low_ratings_are_included(self):
        token = self.order(False)
        self.store.mark_order(token, "SUBMITTED", provider_id="provider-review-test")
        self.store.update_status(token, {"status": "Completed"})
        self.assertEqual(
            (
                await self.send(
                    token, rating=1, comment="<b>Comentário literal de teste.</b>"
                )
            ).status_code,
            200,
        )
        data = reviews.listing(self.store)
        self.assertEqual(data["average"], "1.0")
        self.assertEqual(
            data["reviews"][0]["comment"], "<b>Comentário literal de teste.</b>"
        )
        second = Store(self.panel.settings.db_path)
        try:
            self.assertEqual(reviews.listing(second)["count"], 1)
        finally:
            second.close()

    async def test_dry_run_is_not_eligible_and_listing_requires_auth(self):
        token = self.order()
        with self.store.db:
            self.store.db.execute("UPDATE orders SET dry_run=1 WHERE id=?", (token,))
        self.assertEqual((await self.send(token)).status_code, 400)
        self.assertEqual((await self.client.get("/api/reviews")).status_code, 422)

    async def test_search_uses_current_retail_data_and_requires_auth(self):
        response = await self.client.get(
            "/api/search?q=Instagram", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["services"][0]["unitPrice"], "0.02")
        self.assertNotIn("costUnit", str(response.json()))
        self.assertEqual(
            (await self.client.get("/api/search?q=Instagram")).status_code, 422
        )
        self.assertEqual(
            (await self.client.get("/api/search?q=zzzz", headers=self.headers)).json()[
                "services"
            ],
            [],
        )
