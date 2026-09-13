"""Verificação read-only do Mini App local, sem imprimir credenciais."""
import hashlib
import hmac
import json
import os
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
        streaming = client.get("/api/catalog", params={"platform":"Streaming e Apps"}, headers=headers)
        streaming.raise_for_status()
        names = [s["displayName"] for s in streaming.json()["services"]]
        assert any("Netflix" in name for name in names)
        assert any("YouTube Premium" in name for name in names)
        assert any("Disney+" in name for name in names)
        for path in ("/assets/app.js?v=3", "/assets/app.css?v=3", "/assets/logo.jpg",
                     "/assets/brands/instagram.svg", "/assets/brands/kwai.png"):
            client.get(path).raise_for_status()
        assert "bottomNav" in page.text
    payload = catalog.json()
    assert denied.status_code == 401
    assert "content-security-policy" in page.headers
    assert payload["serviceCount"] > 0 and payload["platforms"]
    print(json.dumps({"health": health.json().get("ok"), "unauthorized": denied.status_code,
                      "services": payload["serviceCount"],
                      "first_platform": payload["platforms"][0]["name"],
                      "wallet": account.status_code, "orders": orders.status_code,
                      "subscriptions": len(names), "assets": "ok"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
