"""Cliente privado do fornecedor de serviços."""
import asyncio
import re
import time
from typing import Any

import httpx

from config import PROVIDER_API_URL
from domain import Service, decimal_value


class ProviderError(Exception):
    """Rejeição explícita ou falha de consulta (mensagem sem chave)."""


class UncertainWrite(ProviderError):
    """A escrita pode ter sido aceita. É proibido reenviar automaticamente."""


class ServiceProvider:
    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self._key = api_key
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=8), verify=True, follow_redirects=False,
            transport=transport, headers={"User-Agent": "MaisPopularBot/2.0"},
        )
        self._services: list[Service] = []
        self._expires = 0.0
        self._catalog_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.client.aclose()

    def safe_error(self, value: Any) -> str:
        text = str(value).replace(self._key, "[chave ocultada]") if self._key else str(value)
        return re.sub(r"[\x00-\x1f]", " ", text)[:350]

    async def _call(self, action: str, *, write: bool = False, **params: Any) -> Any:
        if {"key", "action"} & params.keys():
            raise ValueError("Não é permitido sobrescrever autenticação ou ação.")
        body = {"key": self._key, "action": action,
                **{k: str(v) for k, v in params.items() if v is not None}}
        tries = 1 if write else 3
        for attempt in range(tries):
            try:
                response = await self.client.post(PROVIDER_API_URL, data=body)
            except httpx.RequestError:
                if write:
                    raise UncertainWrite("Conexão interrompida. Confira no painel antes de qualquer novo envio.") from None
                if attempt + 1 < tries:
                    await asyncio.sleep(0.4 * 2**attempt)
                    continue
                raise ProviderError("Não foi possível consultar o fornecedor. Tente novamente mais tarde.") from None
            if not response.is_success:
                if write:
                    raise UncertainWrite(f"HTTP {response.status_code} após o envio. Confira o pedido no painel.")
                if (response.status_code == 429 or response.status_code >= 500) and attempt + 1 < tries:
                    await asyncio.sleep(0.4 * 2**attempt)
                    continue
                raise ProviderError(f"O fornecedor retornou HTTP {response.status_code}.")
            try:
                data = response.json()
            except ValueError:
                error_cls = UncertainWrite if write else ProviderError
                raise error_cls("O fornecedor não retornou JSON válido.") from None
            if isinstance(data, dict) and data.get("error"):
                raise ProviderError(self.safe_error(data["error"]))
            return data
        raise ProviderError("Consulta não concluída.")

    async def services(self, *, force: bool = False) -> list[Service]:
        async with self._catalog_lock:
            if not force and self._services and time.monotonic() < self._expires:
                return list(self._services)
            data = await self._call("services")
            if not isinstance(data, list):
                raise ProviderError("Formato inválido na lista de serviços.")
            parsed = []
            for raw in data:
                try:
                    parsed.append(Service.parse(raw))
                except (KeyError, TypeError, ValueError):
                    # Um serviço inválido não deve derrubar todo o catálogo.
                    continue
            if data and not parsed:
                raise ProviderError("Não foi possível interpretar os serviços retornados.")
            self._services = sorted(parsed, key=lambda x: (x.category.casefold(), x.name.casefold(), x.id))
            self._expires = time.monotonic() + 300
            return list(self._services)

    async def balance(self) -> dict:
        data = await self._call("balance")
        try:
            decimal_value(data["balance"])
            if not re.fullmatch(r"[A-Z]{3,8}", data["currency"]):
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise ProviderError("Saldo ou moeda inválidos na resposta da API.") from None
        return data

    @staticmethod
    def order_ids(values: list[int | str]) -> str:
        if not 1 <= len(values) <= 100 or any(not str(x).isdigit() or int(x) < 1 for x in values):
            raise ValueError("Informe de 1 a 100 IDs positivos.")
        return ",".join(str(x) for x in values)

    async def add(self, payload: dict) -> str:
        if {"key", "action"} & payload.keys():
            raise ValueError("Payload inválido.")
        data = await self._call("add", write=True, **payload)
        order = data.get("order") if isinstance(data, dict) else None
        if isinstance(order, bool) or not str(order).isdigit() or int(order) < 1:
            raise UncertainWrite("Resposta sem ID de pedido. Confira se o fornecedor criou o pedido.")
        return str(order)

    async def status(self, order_id: int | str) -> dict:
        self.order_ids([order_id])
        data = await self._call("status", order=order_id)
        if not isinstance(data, dict) or not isinstance(data.get("status"), str):
            raise ProviderError("Resposta de status inválida.")
        return data

    async def multi_status(self, order_ids: list[int | str]) -> dict:
        data = await self._call("status", orders=self.order_ids(order_ids))
        if not isinstance(data, dict):
            raise ProviderError("Resposta de status em lote inválida.")
        return data

    async def refill(self, order_id: int | str) -> str:
        self.order_ids([order_id])
        data = await self._call("refill", write=True, order=order_id)
        refill = data.get("refill") if isinstance(data, dict) else None
        if isinstance(refill, bool) or not str(refill).isdigit() or int(refill) < 1:
            raise UncertainWrite("Resposta de reposição sem ID. Confira no painel antes de repetir.")
        return str(refill)

    async def multi_refill(self, order_ids: list[int | str]) -> Any:
        return await self._call("refill", write=True, orders=self.order_ids(order_ids))

    async def refill_status(self, refill_id: int | str) -> dict:
        self.order_ids([refill_id])
        data = await self._call("refill_status", refill=refill_id)
        if not isinstance(data, dict) or not isinstance(data.get("status"), str):
            raise ProviderError("Resposta de reposição inválida.")
        return data

    async def multi_refill_status(self, refill_ids: list[int | str]) -> Any:
        return await self._call("refill_status", refills=self.order_ids(refill_ids))

    async def cancel(self, order_ids: list[int | str]) -> Any:
        return await self._call("cancel", write=True, orders=self.order_ids(order_ids))
