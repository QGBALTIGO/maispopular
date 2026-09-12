"""Cliente Cakto OAuth2 para Pix transacional e conciliação de pedidos."""
import asyncio
import re
import time
from typing import Any

import httpx

from config import CAKTO_API_URL
from domain import decimal_value


class PaymentError(Exception):
    """Falha segura e apresentável ao usuário."""


class PaymentUnavailable(PaymentError):
    """Falha transitória; a mesma idempotency key pode ser reutilizada."""


def validate_customer(name: str, email: str, phone: str, document: str) -> dict:
    name = re.sub(r"\s+", " ", name.strip())
    if len(name) < 5 or " " not in name or len(name) > 120:
        raise ValueError("Informe seu nome completo.")
    email = email.strip().lower()
    if len(email) > 160 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Informe um e-mail válido.")
    phone = re.sub(r"\D", "", phone)
    if not 10 <= len(phone) <= 15:
        raise ValueError("Informe o telefone com DDD. Exemplo: 67999999999.")
    if len(phone) in {10, 11}:
        phone = "55" + phone
    document = re.sub(r"\D", "", document)
    if not _valid_cpf(document):
        raise ValueError("Informe um CPF válido.")
    return {"name": name, "email": email, "phone": phone,
            "docType": "cpf", "docNumber": document}


def _valid_cpf(value: str) -> bool:
    if len(value) != 11 or value == value[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(value[i]) * (size + 1 - i) for i in range(size))
        digit = (total * 10 % 11) % 10
        if digit != int(value[size]):
            return False
    return True


class Cakto:
    def __init__(self, client_id: str, client_secret: str,
                 *, transport: httpx.AsyncBaseTransport | None = None):
        self._client_id = client_id
        self._client_secret = client_secret
        self.client = httpx.AsyncClient(
            base_url=CAKTO_API_URL + "/", timeout=httpx.Timeout(30, connect=8),
            verify=True, follow_redirects=False, transport=transport,
            headers={"User-Agent": "MaisPopularBot/2.0"},
        )
        self._access_token = ""
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.client.aclose()

    def _safe_error(self, value: Any) -> str:
        text = str(value)
        for secret in (self._client_id, self._client_secret, self._access_token):
            if secret:
                text = text.replace(secret, "[segredo ocultado]")
        return re.sub(r"[\x00-\x1f]", " ", text)[:350]

    async def _token(self, *, force: bool = False) -> str:
        async with self._token_lock:
            if not force and self._access_token and time.monotonic() < self._token_expires:
                return self._access_token
            try:
                response = await self.client.post("token/", data={
                    "client_id": self._client_id, "client_secret": self._client_secret,
                }, headers={"Content-Type": "application/x-www-form-urlencoded"})
            except httpx.RequestError:
                raise PaymentUnavailable("A conexão com o pagamento está indisponível. Tente novamente.") from None
            if response.status_code != 200:
                raise PaymentError("Não foi possível autenticar o meio de pagamento.")
            try:
                data = response.json()
                token = str(data["access_token"])
                expires = int(data.get("expires_in", 3600))
            except (ValueError, KeyError, TypeError):
                raise PaymentError("O meio de pagamento retornou uma autenticação inválida.") from None
            self._access_token = token
            self._token_expires = time.monotonic() + max(60, expires - 120)
            return token

    async def _request(self, method: str, path: str, *, json: dict | None = None,
                       idempotency_key: str | None = None) -> dict:
        for attempt in range(3):
            token = await self._token(force=attempt > 0)
            headers = {"Authorization": f"Bearer {token}"}
            if idempotency_key:
                headers["X-Idempotency-Key"] = idempotency_key
            try:
                response = await self.client.request(method, path, json=json, headers=headers)
            except httpx.RequestError:
                if attempt < 2:
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                raise PaymentUnavailable("Não foi possível confirmar a operação com o pagamento.") from None
            if response.status_code == 401 and attempt < 2:
                self._access_token = ""
                continue
            if response.status_code == 409:
                if attempt < 2:
                    await asyncio.sleep(0.8 * 2**attempt)
                    continue
                raise PaymentUnavailable("A cobrança ainda está sendo processada. Tente consultar novamente.")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                raise PaymentUnavailable("O meio de pagamento está temporariamente ocupado.")
            try:
                data = response.json()
            except ValueError:
                raise PaymentUnavailable("O meio de pagamento retornou uma resposta inválida.") from None
            if not response.is_success:
                detail = data.get("detail") if isinstance(data, dict) else None
                raise PaymentError(self._safe_error(detail or "Cobrança recusada pela Cakto."))
            if not isinstance(data, dict):
                raise PaymentUnavailable("O meio de pagamento retornou um formato inválido.")
            return data
        raise PaymentUnavailable("Operação de pagamento não concluída.")

    async def validate_offer(self, offer_id: str, unit_price: int) -> dict:
        data = await self._request("GET", f"offers/{offer_id}/")
        if data.get("status") != "active" or data.get("type") != "unique":
            raise PaymentError("A oferta de recarga precisa estar ativa e ser de pagamento único.")
        if decimal_value(data.get("price")) != unit_price:
            raise PaymentError("A oferta de recarga da Cakto está com valor unitário incorreto.")
        return data

    async def create_pix(self, offer_id: str, amount_reais: int, unit_price: int, customer: dict,
                         fingerprint: str, idempotency_key: str, pix_expires: int) -> dict:
        payload = {
            "paymentMethod": "pix",
            "customer": {**customer, "fingerprint": fingerprint},
            "items": [{"offerId": offer_id, "quantity": amount_reais // unit_price, "offerType": "main"}],
            "metadata": {"utm_source": "telegram", "utm_medium": "bot",
                         "utm_campaign": "recarga_carteira"},
            "pixExpiresIn": pix_expires,
        }
        data = await self._request("POST", "payments/", json=payload,
                                   idempotency_key=idempotency_key)
        if not data.get("id") or not isinstance(data.get("pix"), dict) or not data["pix"].get("qrCode"):
            raise PaymentUnavailable("A cobrança foi criada sem os dados completos do Pix.")
        if decimal_value(data.get("baseAmount")) != amount_reais:
            raise PaymentUnavailable("A Cakto retornou um valor diferente da recarga solicitada.")
        return data

    async def order(self, order_id: str) -> dict:
        data = await self._request("GET", f"orders/{order_id}/")
        if not isinstance(data.get("status"), str):
            raise PaymentUnavailable("O status do Pix não pôde ser interpretado.")
        return data
