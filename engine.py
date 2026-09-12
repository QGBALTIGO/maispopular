"""Orquestração de catálogo, carteira, pagamentos e pedidos."""
import asyncio
import hashlib
import hmac
import json
import time
from decimal import Decimal

from config import Settings
from domain import build_payload, check_quote, decimal_value, retail_price
from payments import Cakto, PaymentError, PaymentUnavailable
from provider import ProviderError, ServiceProvider, UncertainWrite
from storage import Store


class Panel:
    def __init__(self, settings: Settings, api: ServiceProvider, payments: Cakto, store: Store):
        self.settings, self.api, self.payments, self.store = settings, api, payments, store
        self.mutation_lock = asyncio.Lock()

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.settings.admin_ids

    def require_admin(self, user_id: int) -> None:
        if not self.is_admin(user_id):
            raise PermissionError("Ação disponível somente para administradores.")

    async def catalog(self, *, force: bool = False):
        services = await self.api.services(force=force)
        allowed = self.settings.allowed_services
        return [s for s in services if s.sellable and (not allowed or s.id in allowed)]

    async def service(self, service_id: int, *, force: bool = False):
        service = next((s for s in await self.catalog(force=force) if s.id == service_id), None)
        if not service:
            raise ValueError("Serviço removido ou indisponível.")
        return service

    def retail_rate(self, service) -> Decimal:
        return retail_price(service.rate, self.settings.price_multiplier)

    async def quote(self, user_id: int, service_id: int, target: str,
                    value: str | None = None, answer: str | None = None) -> dict:
        service = await self.service(service_id, force=True)
        payload, provider_cost = build_payload(service, target, value, answer)
        provider_balance = await self.api.balance()
        if provider_balance["currency"] != "BRL":
            raise ValueError("O catálogo está temporariamente indisponível para compras em reais.")
        sell_price = retail_price(provider_cost, self.settings.price_multiplier)
        if sell_price > self.settings.max_order_cost:
            raise ValueError("Este pedido ultrapassa o limite por compra. Reduza a quantidade.")
        return self.store.create_order(user_id, service, payload, provider_cost, sell_price)

    async def submit(self, token: str, user_id: int) -> dict:
        async with self.mutation_lock:
            row = self.store.order(token, user_id)
            if not row:
                raise ValueError("Pedido não encontrado para seu usuário.")
            if row["state"] != "DRAFT":
                return row
            if row["expires_at"] < int(time.time()):
                self.store.mark_order(token, "EXPIRED")
                raise ValueError("O orçamento expirou. Monte um novo pedido.")
            service = await self.service(row["service_id"], force=True)
            if service.kind != row["kind"] or service.rate != decimal_value(row["rate"]):
                self.store.mark_order(token, "EXPIRED")
                raise ValueError("O serviço foi atualizado. Monte um novo pedido para ver o valor atual.")
            provider_cost = check_quote(service, json.loads(row["payload"]))
            sell_price = retail_price(provider_cost, self.settings.price_multiplier)
            if provider_cost != decimal_value(row["provider_cost"]) or sell_price != decimal_value(row["cost"]):
                self.store.mark_order(token, "EXPIRED")
                raise ValueError("O preço mudou. Monte um novo pedido para confirmar o valor atualizado.")
            balance = await self.api.balance()
            if balance["currency"] != "BRL" or decimal_value(balance["balance"]) < provider_cost:
                raise ValueError("Este serviço está temporariamente indisponível. Tente novamente mais tarde.")
            if not self.store.claim_order(token, user_id):
                raise ValueError("Confirmação já utilizada, cancelada ou expirada.")
            try:
                provider_id = await self.api.add(json.loads(row["payload"]))
                self.store.mark_order(token, "SUBMITTED", provider_id=provider_id)
            except UncertainWrite as exc:
                self.store.mark_order(token, "UNKNOWN", error=str(exc))
            except ProviderError as exc:
                self.store.reject_order_and_refund(
                    token, "Pedido recusado; saldo devolvido", str(exc))
            except BaseException:
                self.store.mark_order(token, "UNKNOWN", error="Falha inesperada durante o envio. O suporte verificará o pedido.")
                raise
            return self.store.order(token, user_id)

    async def create_payment(self, user_id: int, amount_reais: int, customer: dict) -> dict:
        minimum, maximum = int(self.settings.min_deposit_brl), int(self.settings.max_deposit_brl)
        if not minimum <= amount_reais <= maximum:
            raise ValueError(f"Escolha um valor inteiro entre R$ {minimum} e R$ {maximum}.")
        if amount_reais % self.settings.cakto_unit_price_brl:
            raise ValueError(f"Escolha um valor múltiplo de R$ {self.settings.cakto_unit_price_brl}.")
        row = self.store.create_payment(user_id, amount_reais * 100, customer)
        return await self.retry_payment(row["id"], user_id)

    async def retry_payment(self, token: str, user_id: int) -> dict:
        async with self.mutation_lock:
            row = self.store.payment(token, user_id)
            if not row:
                raise ValueError("Recarga não encontrada.")
            if row["status"] not in {"CREATED", "UNKNOWN"}:
                return row
            if not self.store.claim_payment(token, user_id):
                return self.store.payment(token, user_id)
            customer = json.loads(row["customer_json"])
            fingerprint = hmac.new(self.settings.fingerprint_secret.encode(),
                                   f"{user_id}:{token}".encode(), hashlib.sha256).hexdigest()
            try:
                data = await self.payments.create_pix(
                    self.settings.cakto_offer_id, row["amount_cents"] // 100,
                    self.settings.cakto_unit_price_brl, customer,
                    fingerprint, row["idempotency_key"], self.settings.cakto_pix_expires,
                )
                self.store.payment_created(token, data)
            except PaymentUnavailable as exc:
                self.store.payment_failed(token, "UNKNOWN", str(exc))
            except PaymentError as exc:
                self.store.payment_failed(token, "FAILED", str(exc))
            return self.store.payment(token, user_id)

    async def reconcile_payment(self, token: str) -> tuple[dict, bool]:
        row = self.store.payment(token)
        if not row or not row["cakto_order_id"]:
            raise ValueError("Recarga não disponível para consulta.")
        data = await self.payments.order(row["cakto_order_id"])
        expected = Decimal(row["amount_cents"]) / 100
        if decimal_value(data.get("baseAmount")) != expected:
            raise PaymentError("O valor retornado pela Cakto não corresponde à recarga.")
        return self.store.update_payment_status(token, data["status"])

    async def prepare_action(self, token: str, user_id: int, kind: str) -> dict:
        row = self.store.order(token, user_id)
        if not row or row["state"] != "SUBMITTED" or not row["provider_id"]:
            raise ValueError("Esta ação exige um pedido enviado por seu usuário.")
        service = await self.service(row["service_id"], force=True)
        if kind not in {"refill", "cancel"} or getattr(service, kind) is False:
            raise ValueError("Esse serviço não disponibiliza a ação solicitada.")
        return self.store.create_action(row, kind)

    async def submit_action(self, token: str, user_id: int) -> dict:
        async with self.mutation_lock:
            action = self.store.action(token, user_id)
            if not action or action["state"] != "DRAFT":
                if action:
                    return action
                raise ValueError("Solicitação não encontrada.")
            row = self.store.order(action["order_id"], user_id)
            if not row or row["state"] != "SUBMITTED" or not row["provider_id"]:
                raise ValueError("Pedido indisponível para esta ação.")
            service = await self.service(row["service_id"], force=True)
            if getattr(service, action["kind"]) is False:
                raise ValueError("Esta ação não está disponível para o serviço.")
            if not self.store.claim_action(token, user_id):
                raise ValueError("Confirmação já usada ou expirada.")
            try:
                if action["kind"] == "refill":
                    result = {"refill": await self.api.refill(row["provider_id"])}
                else:
                    raw = await self.api.cancel([row["provider_id"]])
                    entries = raw if isinstance(raw, list) else [raw]
                    item = next((x for x in entries if isinstance(x, dict) and str(x.get("order")) == row["provider_id"]), None)
                    value = item.get("cancel") if item else None
                    if isinstance(value, dict) and value.get("error"):
                        raise ProviderError(self.api.safe_error(value["error"]))
                    if value not in (1, "1", True):
                        raise UncertainWrite("Não foi possível confirmar o cancelamento.")
                    result = {"cancel": 1}
                self.store.mark_action(token, "SUBMITTED", result=result)
            except UncertainWrite as exc:
                self.store.mark_action(token, "UNKNOWN", error=str(exc))
            except ProviderError as exc:
                self.store.mark_action(token, "REJECTED", error=str(exc))
            return self.store.action(token, user_id)
