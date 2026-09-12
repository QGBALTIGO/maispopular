"""Verificação read-only do Mini App local, sem imprimir credenciais."""
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import httpx

from config import Settings


def signed_session(settings: Settings) -> str:
    user_id = min(settings.admin_ids) if settings.admin_ids else 1
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "production-health-check",
        "user": json.dumps({"id": user_id, "first_name": "Admin"}, separators=(",", ":")),
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
        catalog = client.get("/api/bootstrap", headers={
            "X-Telegram-Init-Data": signed_session(settings)})
        catalog.raise_for_status()
    payload = catalog.json()
    assert denied.status_code == 401
    assert "content-security-policy" in page.headers
    assert payload["serviceCount"] > 0 and payload["platforms"]
    print(json.dumps({"health": health.json().get("ok"), "unauthorized": denied.status_code,
                      "services": payload["serviceCount"],
                      "first_platform": payload["platforms"][0]["name"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
