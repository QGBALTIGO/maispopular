"""Mini App autenticado do catálogo Mais Popular."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import platform_banners
import product_banners
from catalog_copy import display_name, presentation
from config import Settings
from domain import family_sort_key, money_brl, platform_sort_key
from engine import Panel
from payments import Cakto
from provider import ProviderError, ServiceProvider
from storage import Store
from web_operations import install_operations

STATIC_DIR = Path(__file__).with_name("webapp_static")


def validate_init_data(
    raw: str, bot_token: str, *, max_age: int = 3600, now: int | None = None
) -> dict:
    """Valida o initData conforme o algoritmo oficial do Telegram."""
    if not raw or len(raw) > 8192:
        raise ValueError("Abra esta página pelo botão do bot no Telegram.")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise ValueError("Sessão do Telegram inválida.") from None
    data: dict[str, str] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("Sessão do Telegram inválida.")
        data[key] = value
    supplied_hash = data.pop("hash", "")
    if len(supplied_hash) != 64:
        raise ValueError("Sessão do Telegram inválida.")
    check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied_hash):
        raise ValueError("Sessão do Telegram inválida.")
    try:
        auth_date = int(data["auth_date"])
        user = json.loads(data["user"])
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("Sessão do Telegram incompleta.") from None
    current = int(time.time()) if now is None else now
    if user_id <= 0 or auth_date > current + 60 or current - auth_date > max_age:
        raise ValueError("Sua sessão expirou. Feche e abra a loja novamente.")
    return user


class RateLimiter:
    def __init__(self, maximum: int = 80, window: int = 60):
        self.maximum, self.window = maximum, window
        self.events: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int) -> None:
        current = time.monotonic()
        events = self.events[user_id]
        while events and events[0] <= current - self.window:
            events.popleft()
        if len(events) >= self.maximum:
            raise HTTPException(429, "Muitas tentativas. Aguarde um minuto.")
        events.append(current)


class QuoteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    service_id: int = Field(gt=0)
    target: str = Field(min_length=2, max_length=1500)
    value: str | None = Field(default=None, max_length=3500)
    answer: str | None = Field(default=None, max_length=6)


def service_json(
    item, multiplier: Decimal, retail_rate: Decimal | None = None, banner_rows=None
) -> dict:
    from pricing import unit_label

    raw_retail_rate = item.rate * multiplier if retail_rate is None else retail_rate
    unit = (
        raw_retail_rate if item.kind.casefold() == "package" else raw_retail_rate / 1000
    )
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "platform": item.platform,
        "family": item.family,
        "kind": item.kind.casefold(),
        "minimum": item.minimum,
        "maximum": item.maximum,
        "retailRate": format(raw_retail_rate, "f"),
        "rateLabel": money_brl(raw_retail_rate),
        "unitPrice": format(unit, "f"),
        "unitPriceLabel": unit_label(unit),
        "refill": item.refill,
        "cancel": item.cancel,
        "banner": product_banners.artwork(item, banner_rows or {}),
        **presentation(item),
    }


def public_order(row: dict, balance_cents: int) -> dict:
    return {
        "id": row["id"],
        "state": row["state"],
        "serviceName": row["service_name"],
        "cost": row["cost"],
        "costLabel": money_brl(row["cost"]),
        "balance": f"{Decimal(balance_cents) / 100:.2f}",
        "balanceLabel": money_brl(Decimal(balance_cents) / 100),
        "error": "A equipe está verificando o pedido."
        if row["state"] == "UNKNOWN"
        else "",
    }


def create_app(panel: Panel, *, own_resources: bool = False) -> FastAPI:
    limiter = RateLimiter()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if own_resources:
            await panel.api.close()
            await panel.payments.close()
            panel.store.close()

    app = FastAPI(
        title="Mais Popular",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.panel = panel

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        try:
            body_size = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            body_size = 16_385
        from banners import MAX_BODY

        banner_upload = request.method == "POST" and (
            request.url.path == "/api/admin/platform-banners"
            or request.url.path in {f"/api/admin/banners/{s}" for s in (1, 2, 3)}
            or re.fullmatch(
                r"/api/admin/product-banners/[1-9][0-9]{0,18}", request.url.path
            )
        )
        if body_size > (MAX_BODY if banner_upload else 16_384):
            return JSONResponse({"detail": "Requisição muito grande."}, status_code=413)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://telegram.org; "
            "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "font-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        if request.url.path.startswith("/api/") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    def authenticated(init_data: str) -> dict:
        try:
            user = validate_init_data(init_data, panel.settings.bot_token)
        except ValueError as exc:
            raise HTTPException(401, str(exc)) from None
        limiter.check(int(user["id"]))
        panel.store.register_user(
            int(user["id"]),
            str(user.get("username", "")),
            " ".join(
                filter(
                    None,
                    (str(user.get("first_name", "")), str(user.get("last_name", ""))),
                )
            ),
        )
        return user

    @app.exception_handler(ProviderError)
    async def provider_error(_: Request, __: ProviderError):
        return JSONResponse(
            {"detail": "O catálogo está temporariamente indisponível."}, status_code=503
        )

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/api/bootstrap")
    async def bootstrap(
        init_data: Annotated[
            str, Header(alias="X-Telegram-Init-Data", max_length=8192)
        ],
    ):
        user = authenticated(init_data)
        services = await panel.catalog()
        counts = {
            name: sum(s.platform == name for s in services)
            for name in {s.platform for s in services}
        }
        platforms = [
            {"name": name, "count": counts[name]}
            for name in sorted(counts, key=platform_sort_key)
        ]
        platform_banner_rows = platform_banners.metadata(panel.store)
        from pricing import unit_label

        for platform in platforms:
            items = [s for s in services if s.platform == platform["name"]]
            quantities = [s for s in items if s.kind.casefold() != "package"]
            priced = [
                (
                    panel.retail_rate(s)
                    / (1000 if s.kind.casefold() != "package" else 1),
                    s,
                )
                for s in (quantities or items)
            ]
            price, cheapest = min(priced, key=lambda item: item[0])
            families = sorted({s.family for s in items}, key=family_sort_key)
            short = [f.split(" / ")[0].split("/")[0].strip() for f in families[:3]]
            platform.update(
                summary=", ".join(short) + ".",
                fromPriceLabel=unit_label(price),
                fromMinimum=cheapest.minimum,
                fromKind=cheapest.kind.casefold(),
                banner=platform_banners.artwork(platform["name"], platform_banner_rows),
            )
        balance = panel.store.balance_cents(int(user["id"]))
        return {
            "user": {
                "id": int(user["id"]),
                "firstName": str(user.get("first_name", "Cliente"))[:80],
                "username": str(user.get("username", ""))[:80],
            },
            "balance": f"{Decimal(balance) / 100:.2f}",
            "balanceLabel": money_brl(Decimal(balance) / 100),
            "platforms": platforms,
            "serviceCount": len(services),
            "depositOptions": [
                a
                for a in sorted(panel.settings.cakto_offers)
                if 20 <= a <= 100 and a % 5 == 0
            ],
            "isAdmin": panel.is_admin(int(user["id"])),
            "botUrl": f"https://t.me/{panel.settings.bot_username}",
        }

    @app.get("/api/catalog")
    async def catalog(
        platform: str,
        init_data: Annotated[
            str, Header(alias="X-Telegram-Init-Data", max_length=8192)
        ],
    ):
        authenticated(init_data)
        platform = platform.strip()[:80]
        services = [s for s in await panel.catalog() if s.platform == platform]
        if not services:
            raise HTTPException(404, "Esta rede não está mais disponível.")
        families = sorted({s.family for s in services}, key=family_sort_key)
        banner_rows = product_banners.metadata(panel.store)
        return {
            "platform": platform,
            "families": families,
            "services": [
                service_json(
                    s,
                    panel.settings.price_multiplier,
                    panel.retail_rate(s),
                    banner_rows,
                )
                for s in services
            ],
        }

    @app.post("/api/quote")
    async def quote(
        payload: QuoteInput,
        init_data: Annotated[
            str, Header(alias="X-Telegram-Init-Data", max_length=8192)
        ],
    ):
        user = authenticated(init_data)
        try:
            row = await panel.quote(
                int(user["id"]),
                payload.service_id,
                payload.target,
                payload.value,
                payload.answer,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return public_order(row, panel.store.balance_cents(int(user["id"])))

    @app.get("/api/account")
    async def account(
        init_data: Annotated[
            str, Header(alias="X-Telegram-Init-Data", max_length=8192)
        ],
    ):
        user = authenticated(init_data)
        user_id = int(user["id"])
        balance = panel.store.balance_cents(user_id)
        return {
            "balance": f"{Decimal(balance) / 100:.2f}",
            "balanceLabel": money_brl(Decimal(balance) / 100),
            "movements": [
                {
                    "id": row["id"],
                    "amountCents": row["amount_cents"],
                    "amountLabel": ("+ " if row["amount_cents"] >= 0 else "− ")
                    + money_brl(Decimal(abs(row["amount_cents"])) / 100),
                    "label": {
                        "DEPOSIT": "Recarga via Pix",
                        "ORDER": "Compra de serviço",
                        "ORDER_REFUND": "Reembolso de pedido",
                        "REVERSAL": "Estorno de recarga",
                    }.get(
                        row["kind"].upper(),
                        "Crédito na carteira"
                        if row["amount_cents"] > 0
                        else "Débito na carteira",
                    ),
                    "createdAt": row["created_at"],
                }
                for row in panel.store.ledger(user_id, 30)
            ],
        }

    @app.get("/api/orders")
    async def orders(
        init_data: Annotated[
            str, Header(alias="X-Telegram-Init-Data", max_length=8192)
        ],
        page: int = Query(default=0, ge=0, le=100000),
    ):
        user = authenticated(init_data)
        rows, total = panel.store.list_orders(int(user["id"]), page, 12)
        return {
            "total": total,
            "page": page,
            "hasMore": (page + 1) * 12 < total,
            "orders": [
                {
                    "id": row["id"],
                    "serviceName": display_name(row["service_name"]),
                    "costLabel": money_brl(row["cost"]),
                    "state": row["state"],
                    "status": row["provider_status"],
                    "createdAt": row["created_at"],
                    "target": row["target"],
                }
                for row in rows
            ],
        }

    @app.post("/api/orders/{token}/confirm")
    async def confirm(
        token: str,
        init_data: Annotated[
            str, Header(alias="X-Telegram-Init-Data", max_length=8192)
        ],
    ):
        user = authenticated(init_data)
        if len(token) != 16 or any(c not in "0123456789abcdef" for c in token):
            raise HTTPException(404, "Pedido não encontrado.")
        try:
            row = await panel.submit(token, int(user["id"]))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return public_order(row, panel.store.balance_cents(int(user["id"])))

    install_operations(app, panel, authenticated)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
    return app


def default_app() -> FastAPI:
    settings = Settings.load()
    store = Store(settings.db_path)
    panel = Panel(
        settings,
        ServiceProvider(settings.api_key),
        Cakto(settings.cakto_client_id, settings.cakto_client_secret),
        store,
    )
    return create_app(panel, own_resources=True)
