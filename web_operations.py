"""Authenticated wallet, order operations and administration for the Mini App."""

import asyncio
import base64
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from typing import Annotated, Literal
from uuid import UUID

import qrcode
from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

import platform_banners
import product_banners
import reviews
from domain import money_brl
from payments import PaymentError, validate_customer
from provider import ProviderError

Auth = Annotated[str, Header(alias="X-Telegram-Init-Data", max_length=8192)]


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    amount: int = Field(strict=True, ge=20, le=100)
    name: str = Field(min_length=5, max_length=120)
    email: str = Field(min_length=3, max_length=160)
    phone: str = Field(min_length=10, max_length=25)
    document: str = Field(min_length=11, max_length=18)


class CreditInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    user_id: int = Field(strict=True, gt=0, le=9007199254740991)
    amount: str = Field(pattern=r"^\d{1,4}([.,]\d{1,2})?$")
    reason: str = Field(min_length=3, max_length=160)


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: str = Field(pattern=r"^(naocriado|[1-9][0-9]{0,19})$")
    confirmation: Literal["CONFIRMO"]


class FulfillmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation: Literal["claim", "release", "complete", "refund"]
    note: str = Field(min_length=5, max_length=300)
    confirmation: Literal["CONFIRMO"]


class PriceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation: Literal["unit", "reset", "multiplier"]
    service_id: int | None = Field(default=None, gt=0)
    value: str = Field(default="", max_length=20)
    reason: str = Field(min_length=5, max_length=200)
    revision: int = Field(ge=0)
    confirmation: Literal["CONFIRMO"]


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=40, pattern=r"^[\wÀ-ÿ .-]+$")
    rating: int = Field(strict=True, ge=1, le=5)
    comment: str = Field(min_length=10, max_length=600)
    consent: Literal[True]


def install_operations(app, panel, authenticated):
    import banners

    def user_id(raw):
        return int(authenticated(raw)["id"])

    def admin(raw):
        value = user_id(raw)
        panel.require_admin(value)
        return value

    @app.get("/api/banners")
    async def banner_list(init_data: Auth):
        user_id(init_data)
        return {"banners": banners.listing(panel.store)}

    @app.get("/media/banners/{slot}")
    async def banner_image(slot: int):
        row = panel.store.db.execute(
            "SELECT image,mime FROM shop_banners WHERE slot=?", (slot,)
        ).fetchone()
        if not row or not row["image"]:
            raise HTTPException(404, "Imagem não encontrada.")
        return Response(
            content=row["image"],
            media_type=row["mime"],
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/api/admin/banners/{slot}")
    async def save_banner(slot: int, request: Request, init_data: Auth):
        actor = admin(init_data)
        if slot not in (1, 2, 3):
            raise HTTPException(404, "Banner não encontrado.")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > banners.MAX_BODY:
                raise HTTPException(413, "Use uma imagem de até 4 MB.")
            body.extend(chunk)
        try:
            payload = banners.BannerInput.model_validate_json(body)
        except ValueError:
            raise HTTPException(
                422, "Confira o título, destino, enquadramento e arquivo do banner."
            ) from None
        data, mime = await asyncio.to_thread(banners.validate_image, payload.image)
        return banners.save(panel.store, actor, slot, payload, data, mime)

    @app.get("/api/admin/product-banners")
    async def product_banner_list(init_data: Auth):
        from domain import platform_sort_key
        from webapp import service_json

        admin(init_data)
        services = await panel.catalog()
        rows = product_banners.metadata(panel.store)
        platform_rows = platform_banners.metadata(panel.store)
        names = sorted(
            {s.platform for s in services if s.platform != "Streaming e Apps"},
            key=platform_sort_key,
        )
        return {
            "platforms": [
                {"name": name, "banner": platform_banners.artwork(name, platform_rows)}
                for name in names
            ],
            "services": [
                service_json(
                    s, panel.settings.price_multiplier, panel.retail_rate(s), rows
                )
                for s in services
                if s.platform == "Streaming e Apps"
            ],
        }

    @app.get("/media/platform-banners/{key}")
    async def platform_banner_image(key: str, v: int):
        row = panel.store.db.execute(
            "SELECT image,mime FROM platform_banners WHERE identity=? AND revision=?",
            (key, v),
        ).fetchone()
        if not row or not row["image"]:
            raise HTTPException(404, "Imagem não encontrada.")
        return Response(
            content=row["image"],
            media_type=row["mime"],
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/api/admin/platform-banners")
    async def save_platform_banner(request: Request, init_data: Auth):
        actor = admin(init_data)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > banners.MAX_BODY:
                raise HTTPException(413, "Use uma imagem de até 4 MB.")
            body.extend(chunk)
        try:
            payload = platform_banners.PlatformBannerInput.model_validate_json(body)
        except ValueError:
            raise HTTPException(
                422, "Confira a rede, o enquadramento e o arquivo do banner."
            ) from None
        names = {
            s.platform
            for s in await panel.catalog()
            if s.platform != "Streaming e Apps"
        }
        if payload.platform not in names:
            raise HTTPException(404, "Rede social não encontrada.")
        data, mime = await asyncio.to_thread(banners.validate_image, payload.image)
        return platform_banners.save(
            panel.store, actor, payload.platform, payload, data, mime
        )

    @app.get("/media/product-banners/{service_id}")
    async def product_banner_image(service_id: int, key: str, v: int):
        row = panel.store.db.execute(
            "SELECT image,mime FROM product_banners WHERE service_id=? AND identity=? AND revision=?",
            (service_id, key, v),
        ).fetchone()
        if not row or not row["image"]:
            raise HTTPException(404, "Imagem não encontrada.")
        return Response(
            content=row["image"],
            media_type=row["mime"],
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/api/admin/product-banners/{service_id}")
    async def save_product_banner(service_id: int, request: Request, init_data: Auth):
        actor = admin(init_data)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > banners.MAX_BODY:
                raise HTTPException(413, "Use uma imagem de até 4 MB.")
            body.extend(chunk)
        try:
            payload = product_banners.ProductBannerInput.model_validate_json(body)
        except ValueError:
            raise HTTPException(
                422, "Confira o produto, enquadramento e arquivo do banner."
            ) from None
        service = await panel.service(service_id)
        data, mime = await asyncio.to_thread(banners.validate_image, payload.image)
        return product_banners.save(panel.store, actor, service, payload, data, mime)

    @app.exception_handler(ValueError)
    async def invalid(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(PermissionError)
    async def forbidden(_: Request, __: PermissionError):
        return JSONResponse(
            {"detail": "Acesso exclusivo de administrador."}, status_code=403
        )

    @app.exception_handler(PaymentError)
    async def unavailable(_: Request, __: PaymentError):
        return JSONResponse(
            {"detail": "Não foi possível consultar o pagamento. Tente novamente."},
            status_code=503,
        )

    def own_payment(token, uid):
        row = panel.store.payment(token, uid)
        if not row:
            raise HTTPException(404, "Recarga não encontrada.")
        return row

    def payment_json(row, include_qr=True):
        expired = False
        if row["expires_at"]:
            try:
                expiry = datetime.fromisoformat(
                    row["expires_at"].replace("Z", "+00:00")
                )
                expired = (
                    expiry.replace(tzinfo=expiry.tzinfo or timezone.utc).timestamp()
                    <= time.time()
                )
            except ValueError:
                pass
        status = "EXPIRED" if expired and row["status"] == "PENDING" else row["status"]
        data = {
            "id": row["id"],
            "status": status,
            "amount": row["amount_cents"] // 100,
            "amountLabel": money_brl(Decimal(row["amount_cents"]) / 100),
            "expiresAt": row["expires_at"],
            "createdAt": row["created_at"],
        }
        if include_qr:
            data["qrCode"] = row["qr_code"] if status == "PENDING" else ""
            data["qrImage"] = ""
            if data["qrCode"]:
                image = qrcode.make(data["qrCode"])
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                data["qrImage"] = (
                    "data:image/png;base64,"
                    + base64.b64encode(buffer.getvalue()).decode()
                )
            balance = panel.store.balance_cents(row["user_id"])
            data.update(
                balance=f"{Decimal(balance) / 100:.2f}",
                balanceLabel=money_brl(Decimal(balance) / 100),
            )
        return data

    @app.get("/api/payments")
    async def payments(init_data: Auth):
        uid = user_id(init_data)
        rows = panel.store.db.execute(
            "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 20",
            (uid,),
        )
        return {"payments": [payment_json(dict(row), False) for row in rows]}

    @app.post("/api/payments")
    async def create_payment(payload: PaymentInput, init_data: Auth):
        uid = user_id(init_data)
        if payload.amount % 5:
            raise ValueError("Escolha um valor de R$ 20 a R$ 100, de 5 em 5.")
        customer = validate_customer(
            payload.name, payload.email, payload.phone, payload.document
        )
        row = await panel.create_payment(
            uid, payload.amount, customer, str(payload.request_id)
        )
        return payment_json(row)

    @app.get("/api/payments/{token}")
    async def get_payment(token: str, init_data: Auth):
        return payment_json(own_payment(token, user_id(init_data)))

    @app.post("/api/payments/{token}/refresh")
    async def refresh_payment(token: str, init_data: Auth):
        row = own_payment(token, user_id(init_data))
        if row["cakto_order_id"] and row["checked_at"] < int(time.time()) - 8:
            row, _ = await panel.reconcile_payment(token)
        return payment_json(row)

    @app.post("/api/payments/{token}/retry")
    async def retry_payment(token: str, init_data: Auth):
        uid = user_id(init_data)
        row = own_payment(token, uid)
        if row["status"] == "CREATING" and row["updated_at"] < time.time() - 180:
            panel.store.payment_failed(token, "UNKNOWN", "Confirmação pendente")
        return payment_json(await panel.retry_payment(token, uid))

    @app.get("/api/orders/{token}")
    async def order_detail(token: str, init_data: Auth):
        uid = user_id(init_data)
        row = panel.store.order(token, uid)
        if not row:
            raise HTTPException(404, "Pedido não encontrado.")
        status = json.loads(row["status_json"])
        supported = {"refill": False, "cancel": False}
        if row["state"] == "SUBMITTED":
            try:
                service = await panel.service(row["service_id"])
                supported = {"refill": service.refill, "cancel": service.cancel}
            except (ValueError, ProviderError):
                pass
        actions = panel.store.actions_for(token, uid)
        return {
            "id": token,
            "serviceName": row["service_name"],
            "state": row["state"],
            "status": row["provider_status"],
            "costLabel": money_brl(row["cost"]),
            "target": row["target"],
            "createdAt": row["created_at"],
            "startCount": str(status.get("start_count", "—"))[:50],
            "remains": str(status.get("remains", "—"))[:50],
            **supported,
            **reviews.eligibility(panel.store, token, uid),
            "actions": [
                {
                    "id": a["id"],
                    "kind": a["kind"],
                    "state": a["state"],
                    "hasRefill": bool(json.loads(a["result_json"]).get("refill")),
                }
                for a in actions
            ],
        }

    @app.get("/api/reviews")
    async def customer_reviews(
        init_data: Auth, page: int = Query(default=0, ge=0, le=10000)
    ):
        user_id(init_data)
        return reviews.listing(panel.store, page)

    @app.get("/api/search")
    async def search_catalog(
        init_data: Auth, q: str = Query(min_length=2, max_length=80)
    ):
        from webapp import service_json

        user_id(init_data)
        term = q.strip().casefold()
        if len(term) < 2:
            return {"services": [], "hasMore": False}
        items = []
        banner_rows = product_banners.metadata(panel.store)
        for service in await panel.catalog():
            item = service_json(
                service,
                panel.settings.price_multiplier,
                panel.retail_rate(service),
                banner_rows,
            )
            if all(
                word
                in f"{item['displayName']} {service.platform} {service.id} {service.family}".casefold()
                for word in term.split()
            ):
                items.append(item)
                if len(items) > 30:
                    break
        return {"services": items[:30], "hasMore": len(items) > 30}

    @app.post("/api/orders/{token}/review")
    async def review_order(token: str, payload: ReviewInput, init_data: Auth):
        uid = user_id(init_data)
        if not panel.store.order(token, uid):
            raise HTTPException(404, "Pedido não encontrado.")
        return reviews.create(
            panel.store, token, uid, payload.name, payload.rating, payload.comment
        )

    @app.post("/api/orders/{token}/refresh")
    async def refresh_order(token: str, init_data: Auth):
        uid = user_id(init_data)
        row = panel.store.order(token, uid)
        if not row:
            raise HTTPException(404, "Pedido não encontrado.")
        if (
            row["state"] == "SUBMITTED"
            and row["provider_id"]
            and row["checked_at"] < time.time() - 10
        ):
            panel.store.update_status(token, await panel.api.status(row["provider_id"]))
        return {"ok": True}

    @app.post("/api/orders/{token}/actions/{kind}")
    async def prepare_action(
        token: str, kind: Literal["refill", "cancel"], init_data: Auth
    ):
        row = await panel.prepare_action(token, user_id(init_data), kind)
        return {"id": row["id"]}

    @app.post("/api/actions/{token}/confirm")
    async def confirm_action(token: str, init_data: Auth):
        row = await panel.submit_action(token, user_id(init_data))
        return {"state": row["state"]}

    @app.get("/api/actions/{token}")
    async def refill_status(token: str, init_data: Auth):
        row = panel.store.action(token, user_id(init_data))
        if not row:
            raise HTTPException(404, "Solicitação não encontrada.")
        refill = json.loads(row["result_json"]).get("refill")
        if not refill:
            return {"status": row["state"]}
        result = await panel.api.refill_status(refill)
        return {"status": str(result.get("status", "Em análise"))[:100]}

    @app.get("/api/admin")
    async def admin_overview(init_data: Auth):
        admin(init_data)
        stats = panel.store.admin_stats()
        try:
            balance = await panel.api.balance()
            stats["operationalLabel"] = money_brl(balance["balance"])
        except ProviderError:
            stats["operationalLabel"] = "Indisponível"
        unknown = panel.store.db.execute(
            "SELECT id,user_id,service_name,cost FROM orders WHERE state='UNKNOWN' ORDER BY created_at LIMIT 30"
        )
        credits = panel.store.db.execute(
            "SELECT * FROM admin_credits ORDER BY created_at DESC,rowid DESC LIMIT 20"
        )
        return {
            "stats": stats,
            "unknownOrders": [dict(r) for r in unknown],
            "credits": [dict(r) for r in credits],
        }

    @app.get("/api/admin/users")
    async def admin_users(
        init_data: Auth, search: str = Query(default="", max_length=80)
    ):
        admin(init_data)
        term = search.strip().lstrip("@").replace("%", "").replace("_", "")
        rows = panel.store.db.execute(
            """SELECT u.user_id,u.username,u.display_name,w.balance_cents FROM users u
            JOIN wallets w ON u.user_id=w.user_id WHERE CAST(u.user_id AS TEXT)=? OR u.username LIKE ?
            OR u.display_name LIKE ? ORDER BY u.updated_at DESC LIMIT 20""",
            (term, f"%{term}%", f"%{term}%"),
        )
        return {"users": [dict(r) for r in rows]}

    @app.get("/api/admin/fulfillment")
    async def fulfillment_queue(init_data: Auth):
        admin(init_data)
        rows = panel.store.db.execute("""SELECT id,user_id,service_id,service_name,cost,provider_cost,payload,
            target,state,queue_reason,manual_admin_id,created_at FROM orders WHERE state IN ('QUEUED','MANUAL')
            ORDER BY created_at LIMIT 100""")
        audit = panel.store.db.execute(
            "SELECT * FROM fulfillment_audit ORDER BY id DESC LIMIT 30"
        )
        return {"orders": [dict(r) for r in rows], "audit": [dict(r) for r in audit]}

    @app.get("/api/admin/prices")
    async def prices(init_data: Auth):
        import pricing
        from catalog_copy import presentation

        admin(init_data)
        services = await panel.catalog()
        policy = panel.store.db.execute(
            "SELECT * FROM pricing_policy WHERE id=1"
        ).fetchone()
        items = []
        for service in services:
            price, _, custom = pricing.rate(panel, service)
            divisor = 1 if service.kind.casefold() == "package" else 1000
            items.append(
                {
                    "id": service.id,
                    "name": presentation(service)["displayName"],
                    "platform": service.platform,
                    "kind": service.kind.casefold(),
                    "unitPrice": format(price / divisor, "f"),
                    "unitLabel": pricing.unit_label(price / divisor),
                    "costUnit": format(service.rate / divisor, "f"),
                    "custom": custom,
                }
            )
        return {
            "revision": policy["revision"],
            "multiplier": policy["multiplier"] or str(panel.settings.price_multiplier),
            "services": items,
            "audit": [
                dict(row)
                for row in panel.store.db.execute(
                    "SELECT * FROM pricing_audit ORDER BY id DESC LIMIT 30"
                )
            ],
        }

    @app.post("/api/admin/prices")
    async def edit_price(payload: PriceInput, init_data: Auth):
        import pricing

        actor = admin(init_data)
        if payload.operation == "multiplier" and payload.service_id is not None:
            raise ValueError("A regra geral não aceita ID de serviço.")
        service = (
            await panel.service(payload.service_id, force=True)
            if payload.service_id
            else None
        )
        return pricing.change(
            panel,
            actor,
            payload.operation,
            payload.value,
            payload.reason,
            payload.revision,
            service,
        )

    @app.post("/api/admin/fulfillment/{token}")
    async def manual_fulfillment(
        token: str, payload: FulfillmentInput, init_data: Auth
    ):
        from fulfillment import manual_transition

        row = manual_transition(
            panel, admin(init_data), token, payload.operation, payload.note
        )
        return {"id": row["id"], "state": row["state"]}

    @app.post("/api/admin/credits")
    async def admin_credit(payload: CreditInput, init_data: Auth):
        return panel.grant_credit(
            admin(init_data),
            payload.user_id,
            payload.amount,
            payload.reason,
            str(payload.request_id),
        )

    @app.post("/api/admin/orders/{token}/resolve")
    async def resolve(token: str, payload: ResolveInput, init_data: Auth):
        admin_id = admin(init_data)
        async with panel.mutation_lock:
            row = panel.store.order(token)
            if not row or row["state"] != "UNKNOWN":
                raise ValueError("Este pedido não está pendente de verificação.")
            if payload.decision == "naocriado":
                panel.store.reject_order_and_refund(
                    token,
                    f"Verificação administrativa por {admin_id}",
                    "Pedido não criado; saldo devolvido.",
                )
            else:
                status = await panel.api.status(payload.decision)
                panel.store.mark_order(token, "SUBMITTED", provider_id=payload.decision)
                panel.store.update_status(token, status)
        return {"ok": True}
