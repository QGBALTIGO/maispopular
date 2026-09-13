import base64
import unittest
from dataclasses import replace
from io import BytesIO

import test_webapp
from PIL import Image

import banners
from storage import Store


class BannerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_webapp.WebAppRouteTests.asyncSetUp
    asyncTearDown = test_webapp.WebAppRouteTests.asyncTearDown

    def payload(self, **changes):
        self.panel.settings = replace(self.panel.settings, admin_ids=frozenset({7}))
        data = {
            "title": "Banner de teste",
            "target": "social",
            "fit": "contain",
            "position": "center",
            "revision": 0,
        }
        return data | changes

    def image(self):
        buffer = BytesIO()
        Image.new("RGB", (160, 90), "blue").save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    async def save(self, payload, headers=None):
        return await self.client.post(
            "/api/admin/banners/1", headers=headers or self.headers, json=payload
        )

    async def test_upload_persists_and_serves_raster_with_fitting(self):
        result = await self.save(
            self.payload(image=self.image(), fit="cover", position="top")
        )
        self.assertEqual(result.status_code, 200)
        item = result.json()
        self.assertEqual(item["revision"], 1)
        self.assertTrue(item["custom"])
        content = await self.client.get(item["url"])
        self.assertEqual(content.headers["content-type"], "image/webp")
        self.assertIn("immutable", content.headers["cache-control"])
        with Image.open(BytesIO(content.content)) as rendered:
            self.assertEqual(rendered.format, "WEBP")
            self.assertEqual(rendered.size, (160, 90))
        second = Store(self.panel.settings.db_path)
        try:
            self.assertEqual(banners.listing(second)[0]["position"], "top")
        finally:
            second.close()

    async def test_nonadmin_and_unsigned_cannot_upload(self):
        payload = self.payload(image=self.image())
        denied = await self.save(
            payload, {"X-Telegram-Init-Data": test_webapp.signed_init(8)}
        )
        self.assertEqual(denied.status_code, 403)
        denied = await self.client.post("/api/admin/banners/1", json=payload)
        self.assertEqual(denied.status_code, 422)
        self.assertEqual(banners.listing(self.store)[0]["revision"], 0)

    async def test_stale_writer_and_restore(self):
        self.assertEqual(
            (await self.save(self.payload(image=self.image()))).status_code, 200
        )
        self.assertEqual(
            (await self.save(self.payload(title="Outra sessão"))).status_code, 400
        )
        result = await self.save(self.payload(revision=1, reset=True))
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()["custom"])
        self.assertEqual(result.json()["revision"], 2)
        self.assertEqual((await self.client.get("/media/banners/1")).status_code, 404)

    async def test_invalid_raster_and_external_targets_rejected(self):
        for raw in (
            "abc",
            "<svg/>",
            base64.b64encode(b'<svg onload="alert(1)"/>').decode(),
        ):
            self.assertEqual(
                (await self.save(self.payload(image=raw))).status_code, 400
            )
        for extra in (
            {"target": "https://evil.invalid"},
            {"fit": "bad"},
            {"position": "left"},
            {"revision": -1},
        ):
            self.assertEqual((await self.save(self.payload(**extra))).status_code, 422)
        self.assertEqual(banners.listing(self.store)[0]["revision"], 0)

    async def test_metadata_update_keeps_image(self):
        await self.save(self.payload(image=self.image()))
        result = await self.save(
            self.payload(revision=1, title="Novo título", target="wallet")
        )
        self.assertTrue(result.json()["custom"])
        self.assertEqual(result.json()["destination"], "wallet")

    async def test_oversized_stream_and_file_rejected(self):
        self.payload()

        async def stream():
            for _ in range(7):
                yield b"x" * 1024 * 1024

        r = await self.client.post(
            "/api/admin/banners/1", headers=self.headers, content=stream()
        )
        self.assertEqual(r.status_code, 413)
        with self.assertRaisesRegex(ValueError, "4 MB"):
            banners.validate_image(
                base64.b64encode(b"x" * (banners.MAX_IMAGE + 1)).decode()
            )

    async def test_defaults_and_compact_home_contract(self):
        response = await self.client.get("/api/banners", headers=self.headers)
        self.assertEqual(len(response.json()["banners"]), 3)
        home = (await self.client.get("/")).text
        self.assertNotIn('id="welcomeText"', home)
        self.assertNotIn('id="reviewsSection"', home)
        self.assertNotIn("/assets/reviews.js", home)
        self.assertIn('id="manageBanners"', home)
        self.assertIn('id="manageBroadcasts"', home)
        self.assertIn('id="affiliateEntry"', home)
        self.assertLess(home.index('id="heroSlides"'), home.index('id="socialSection"'))
        platform = (
            await self.client.get("/api/bootstrap", headers=self.headers)
        ).json()["platforms"][0]
        self.assertEqual(platform["fromPriceLabel"], "R$ 0,02")
        self.assertTrue(platform["summary"])
        self.assertEqual(platform["fromMinimum"], 100)

    async def test_existing_images_can_be_optimized_once(self):
        raw = base64.b64decode(self.image())
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO shop_banners VALUES(1,'Teste','social','cover','center',?,'image/png',1,7,1)",
                (raw,),
            )
        result = banners.optimize_stored_images(self.store)
        self.assertEqual(result["changed"], 1)
        row = self.store.db.execute("SELECT mime,revision,image FROM shop_banners").fetchone()
        self.assertEqual((row["mime"], row["revision"]), ("image/webp", 2))
        self.assertEqual(banners.optimize_stored_images(self.store)["changed"], 0)
