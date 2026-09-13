import base64
import unittest
from dataclasses import replace
from io import BytesIO

import test_webapp
from PIL import Image

import platform_banners
import product_banners
from pricing import identity
from storage import Store


class ProductBannerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_webapp.WebAppRouteTests.asyncSetUp
    asyncTearDown = test_webapp.WebAppRouteTests.asyncTearDown

    async def payload(self, **changes):
        self.panel.settings = replace(self.panel.settings, admin_ids=frozenset({7}))
        buffer = BytesIO()
        Image.new("RGB", (160, 90), "blue").save(buffer, format="PNG")
        return {
            "identity": identity(await self.panel.service(42)),
            "revision": 0,
            "image": base64.b64encode(buffer.getvalue()).decode(),
                "fit": "cover",
            "position": "top",
        } | changes

    async def save(self, payload, service_id=42, headers=None):
        return await self.client.post(
            f"/api/admin/product-banners/{service_id}",
            headers=headers or self.headers,
            json=payload,
        )

    async def test_upload_catalog_search_and_persistence_price_unchanged(self):
        payload = await self.payload()
        result = await self.save(payload)
        self.assertEqual(result.status_code, 200, result.text)
        item = result.json()
        self.assertEqual(item["revision"], 1)
        self.assertTrue(item["custom"])
        media = await self.client.get(item["url"])
        self.assertEqual(media.content, base64.b64decode(payload["image"]))
        self.assertEqual(media.headers["content-type"], "image/png")
        catalog = (
            await self.client.get(
                "/api/catalog?platform=Instagram", headers=self.headers
            )
        ).json()["services"][0]
        self.assertEqual(catalog["banner"], item)
        self.assertEqual(catalog["unitPriceLabel"], "R$ 0,02")
        search = (
            await self.client.get("/api/search?q=Instagram", headers=self.headers)
        ).json()["services"][0]
        self.assertEqual(search["banner"], item)
        second = Store(self.panel.settings.db_path)
        try:
            self.assertEqual(product_banners.metadata(second)[42]["position"], "top")
        finally:
            second.close()
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM shop_banners").fetchone()[0], 0
        )

    async def test_admin_required_for_list_and_upload(self):
        payload = await self.payload()
        headers = {"X-Telegram-Init-Data": test_webapp.signed_init(8)}
        self.assertEqual((await self.save(payload, headers=headers)).status_code, 403)
        self.assertEqual(
            (
                await self.client.get("/api/admin/product-banners", headers=headers)
            ).status_code,
            403,
        )
        self.assertEqual(
            (
                await self.client.post("/api/admin/product-banners/42", json=payload)
            ).status_code,
            422,
        )
        self.assertFalse(product_banners.metadata(self.store))

    async def test_revision_restore_and_metadata_only(self):
        initial = (await self.save(await self.payload())).json()
        self.assertEqual((await self.save(await self.payload())).status_code, 400)
        edited = await self.save(
            await self.payload(revision=1, image="", position="bottom")
        )
        self.assertTrue(edited.json()["custom"])
        self.assertEqual(edited.json()["position"], "bottom")
        self.assertEqual((await self.client.get(initial["url"])).status_code, 404)
        restored = await self.save(await self.payload(revision=2, image="", reset=True))
        self.assertFalse(restored.json()["custom"])
        self.assertEqual(restored.json()["revision"], 3)

    async def test_service_identity_prevents_wrong_product_and_independent_images(self):
        original = await self.panel.service(42)
        self.api.services.return_value = [
            original,
            replace(original, id=43, name="Outro produto"),
        ]
        await self.save(await self.payload())
        rows = product_banners.metadata(self.store)
        other = await self.panel.service(43)
        self.assertFalse(product_banners.artwork(other, rows)["custom"])
        changed = replace(original, name="Novo produto reutilizando código")
        self.api.services.return_value = [changed, other]
        self.assertFalse(product_banners.artwork(changed, rows)["custom"])
        stale = await self.payload(revision=1, identity=identity(original))
        self.assertEqual((await self.save(stale)).status_code, 400)
        self.assertEqual(
            (await self.save(await self.payload(revision=1, image=""))).status_code, 400
        )

    async def test_invalid_images_fields_missing_service_and_large_stream(self):
        for changes in (
            {"image": "bad"},
            {"image": base64.b64encode(b"<svg/>").decode()},
            {"image": ""},
        ):
            self.assertEqual(
                (await self.save(await self.payload(**changes))).status_code, 400
            )
        for changes in (
            {"fit": "bad"},
            {"position": "left"},
            {"revision": -1},
            {"target": "https://example.com"},
        ):
            self.assertEqual(
                (await self.save(await self.payload(**changes))).status_code, 422
            )
        self.assertEqual(
            (await self.save(await self.payload(), service_id=999)).status_code, 400
        )

        async def stream():
            for _ in range(7):
                yield b"x" * 1024 * 1024

        result = await self.client.post(
            "/api/admin/product-banners/42", headers=self.headers, content=stream()
        )
        self.assertEqual(result.status_code, 413)
        self.assertFalse(product_banners.metadata(self.store))

    async def test_editor_and_admin_listing(self):
        await self.payload()
        listing = await self.client.get(
            "/api/admin/product-banners", headers=self.headers
        )
        self.assertEqual(listing.status_code, 200)
        self.assertFalse(listing.json()["platforms"][0]["banner"]["custom"])
        self.assertEqual(listing.json()["services"], [])
        home = (await self.client.get("/")).text
        self.assertIn('id="manageProductBanners"', home)
        self.assertIn('id="productBannerFile"', home)
        self.assertNotIn('id="reviewsSection"', home)

    async def test_social_network_uses_one_general_catalog_banner(self):
        payload = await self.payload()
        platform_payload = {
            "platform": "Instagram",
            "identity": platform_banners.identity("Instagram"),
            "revision": 0,
            "image": payload["image"],
            "fit": "contain",
            "position": "bottom",
        }
        result = await self.client.post(
            "/api/admin/platform-banners", headers=self.headers, json=platform_payload
        )
        self.assertEqual(result.status_code, 200, result.text)
        artwork = result.json()
        self.assertTrue(artwork["custom"])
        self.assertEqual(artwork["fit"], "cover")
        self.assertEqual(artwork["position"], "bottom")
        bootstrap = (
            await self.client.get("/api/bootstrap", headers=self.headers)
        ).json()
        instagram = next(p for p in bootstrap["platforms"] if p["name"] == "Instagram")
        self.assertEqual(instagram["banner"], artwork)
        catalog = (
            await self.client.get(
                "/api/catalog?platform=Instagram", headers=self.headers
            )
        ).json()
        self.assertFalse(catalog["services"][0]["banner"]["custom"])
        media = await self.client.get(artwork["url"])
        self.assertEqual(media.headers["content-type"], "image/png")
        stale = await self.client.post(
            "/api/admin/platform-banners", headers=self.headers, json=platform_payload
        )
        self.assertEqual(stale.status_code, 400)
        restored = await self.client.post(
            "/api/admin/platform-banners",
            headers=self.headers,
            json=platform_payload | {"revision": 1, "image": "", "reset": True},
        )
        self.assertFalse(restored.json()["custom"])
        self.assertEqual((await self.client.get(artwork["url"])).status_code, 404)

    async def test_social_banner_rejects_nonadmin_unknown_network_and_wrong_identity(
        self,
    ):
        payload = await self.payload()
        data = {
            "platform": "Instagram",
            "identity": platform_banners.identity("Instagram"),
            "revision": 0,
            "image": payload["image"],
        }
        denied = await self.client.post(
            "/api/admin/platform-banners",
            headers={"X-Telegram-Init-Data": test_webapp.signed_init(8)},
            json=data,
        )
        self.assertEqual(denied.status_code, 403)
        unknown = await self.client.post(
            "/api/admin/platform-banners",
            headers=self.headers,
            json=data | {"platform": "Rede inexistente"},
        )
        self.assertEqual(unknown.status_code, 404)
        wrong = await self.client.post(
            "/api/admin/platform-banners",
            headers=self.headers,
            json=data | {"identity": "0" * 64},
        )
        self.assertEqual(wrong.status_code, 400)
        self.assertFalse(platform_banners.metadata(self.store))
