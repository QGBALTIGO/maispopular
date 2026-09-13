"""Verificação read-only do Mini App local, sem imprimir credenciais."""
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from urllib.parse import urlencode

import httpx

from config import Settings


def signed_session(settings: Settings) -> str:
    user_id = min(settings.admin_ids)
    with sqlite3.connect(f"file:{settings.db_path.resolve()}?mode=ro", uri=True) as db:
        row = db.execute("SELECT username,display_name FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        raise ValueError("O administrador precisa abrir o bot antes da verificação autenticada.")
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "production-health-check",
        "user": json.dumps({"id": user_id, "first_name": row[1], "username": row[0]}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def main() -> None:
    settings = Settings.load()
    base_url = os.getenv("WEBAPP_INTERNAL_URL", "http://127.0.0.1:8031")
    with httpx.Client(base_url=base_url, timeout=30) as client:
        health = client.get("/health")
        health.raise_for_status()
        page = client.get("/")
        page.raise_for_status()
        denied = client.get("/api/bootstrap", headers={"X-Telegram-Init-Data": "invalid"})
        headers = {"X-Telegram-Init-Data": signed_session(settings)}
        catalog = client.get("/api/bootstrap", headers=headers)
        catalog.raise_for_status()
        account = client.get("/api/account", headers=headers)
        account.raise_for_status()
        orders = client.get("/api/orders", headers=headers)
        orders.raise_for_status()
        payments = client.get("/api/payments", headers=headers)
        payments.raise_for_status()
        admin = client.get("/api/admin", headers=headers)
        admin.raise_for_status()
        queue = client.get("/api/admin/fulfillment", headers=headers)
        queue.raise_for_status()
        prices = client.get("/api/admin/prices",headers=headers)
        prices.raise_for_status()
        reviews = client.get("/api/reviews",headers=headers)
        reviews.raise_for_status()
        search = client.get("/api/search",params={"q":"Instagram"},headers=headers)
        search.raise_for_status()
        assert search.json()["services"]
        assert prices.json()["services"]
        assert catalog.json()["depositOptions"] == list(range(20,101,5))
        assert catalog.json()["isAdmin"] is True
        streaming = client.get("/api/catalog", params={"platform":"Streaming e Apps"}, headers=headers)
        streaming.raise_for_status()
        names = [s["displayName"] for s in streaming.json()["services"]]
        assert any("Netflix" in name for name in names)
        assert any("YouTube Premium" in name for name in names)
        assert any("Disney+" in name for name in names)
        for asset in re.findall(r'(?:src|href)="(/assets/[^"<>]+)"',page.text):
            client.get(asset).raise_for_status()
        for path in ("/assets/app.js?v=7", "/assets/app.css?v=6", "/assets/operations.js?v=7", "/assets/theme.js?v=8", "/assets/logo.jpg",
                     "/assets/storefront.js?v=6", "/assets/storefront.css?v=6", "/assets/banners/social.png",
                     "/assets/banners/services.png", "/assets/banners/support.png",
                     "/assets/brands/instagram.svg", "/assets/brands/kwai.png",
                     "/assets/prices.js?v=7", "/assets/reviews.js?v=8", "/assets/blue-store.js?v=8",
                     "/assets/blue-store.css?v=8", "/assets/experience.css?v=7",
                     "/assets/banners/social-blue-v2.png", "/assets/banners/streaming-blue-v2.png"):
            client.get(path).raise_for_status()
        assert "bottomNav" in page.text
        assert 'id="heroSlides"' in page.text
        assert 'id="reviewsSection"' not in page.text
        assert 'id="welcomeText"' not in page.text
        assert 'id="manageBanners"' in page.text
        banners=client.get('/api/banners',headers=headers)
        banners.raise_for_status()
        assert len(banners.json()['banners'])==3
        for banner in banners.json()['banners']:client.get(banner['url']).raise_for_status()
        assert 'id="managePrices"' in page.text
        assert 'href="https://baltigoflix.com.br"' in page.text
        assert 'id="themeToggle"' in page.text
        assert 'name="help-faq"' in page.text
        assert 'href="https://t.me/suportemaispopular"' in page.text
        assert "cakto" not in page.text.lower()
    payload = catalog.json()
    assert denied.status_code == 401
    assert "content-security-policy" in page.headers
    assert payload["serviceCount"] > 0 and payload["platforms"]
    print(json.dumps({"health": health.json().get("ok"), "unauthorized": denied.status_code,
                      "services": payload["serviceCount"],
                      "first_platform": payload["platforms"][0]["name"],
                      "wallet": account.status_code, "orders": orders.status_code,
                      "payments": payments.status_code, "admin": admin.status_code,
                      "depositAmounts": catalog.json()["depositOptions"],
                      "subscriptions": len(names), "fulfillment": queue.status_code,
                      "prices":prices.status_code,"reviews":reviews.status_code,"reviewCount":reviews.json()["count"],
                      "search":search.status_code,"assets": "ok"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
