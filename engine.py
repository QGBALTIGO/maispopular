"""Orquestração de pedidos. Sem dependência do Telegram, para testes isolados."""
import asyncio
import json
import time

from config import Settings
from domain import build_payload, check_quote, decimal_value
from provider import SouPopular, ProviderError, UncertainWrite
from storage import Store


class Panel:
    def __init__(self, settings: Settings, api: SouPopular, store: Store):
        self.settings, self.api, self.store = settings, api, store
        self.mutation_lock = asyncio.Lock()

    def authorize(self, user_id: int) -> None:
        if user_id not in self.settings.admin_ids:
            raise PermissionError("Acesso restrito aos administradores configurados.")

    async def catalog(self, *, force: bool = False):
        services = await self.api.services(force=force)
        allowed = self.settings.allowed_services
        return [s for s in services if not allowed or s.id in allowed]

    async def service(self, service_id: int, *, force: bool = False):
        service = next((s for s in await self.catalog(force=force) if s.id == service_id), None)
        if not service:
            raise ValueError("Serviço removido, indisponível ou não autorizado.")
        return service

    async def quote(self, user_id: int, service_id: int, target: str, value: str | None = None,
                    answer: str | None = None) -> dict:
        self.authorize(user_id)
        service = await self.service(service_id, force=True)
        payload, cost = build_payload(service, target, value, answer)
        balance = await self.api.balance()
        if cost > self.settings.max_order_cost:
            raise ValueError(f"Orçamento acima do teto de segurança: {self.settings.max_order_cost} {balance['currency']} por pedido.")
        return self.store.create_order(user_id, service, payload, cost, balance['currency'], self.settings.dry_run)

    async def submit(self, token: str, user_id: int) -> dict:
        self.authorize(user_id)
        async with self.mutation_lock:
            row = self.store.order(token, user_id)
            if not row:
                raise ValueError("Pedido não encontrado para seu usuário.")
            if row['state'] != 'DRAFT':
                return row  # Segundo clique nunca envia de novo.
            if row['expires_at'] < int(time.time()):
                self.store.mark_order(token, 'EXPIRED')
                raise ValueError("Orçamento expirado. Monte um novo pedido.")
            if bool(row['dry_run']) != self.settings.dry_run:
                self.store.mark_order(token, 'EXPIRED')
                raise ValueError("O modo do bot mudou. Monte um novo orçamento.")
            service = await self.service(row['service_id'], force=True)
            if service.kind != row['kind']:
                self.store.mark_order(token, 'EXPIRED')
                raise ValueError("O tipo do serviço mudou. Monte outro pedido.")
            cost = check_quote(service, json.loads(row['payload']))
            balance = await self.api.balance()
            if cost != decimal_value(row['cost']) or balance['currency'] != row['currency'] or service.rate != decimal_value(row['rate']):
                self.store.mark_order(token, 'EXPIRED')
                raise ValueError("Preço ou moeda mudou. Monte um novo orçamento para confirmar o valor atualizado.")
            if cost > self.settings.max_order_cost:
                raise ValueError("Este pedido ultrapassa o teto de segurança atual.")
            if not self.settings.dry_run and decimal_value(balance['balance']) < cost:
                raise ValueError("Saldo insuficiente na conta SouPopular. Recarregue pelo painel do fornecedor.")
            if not self.store.claim_order(token, user_id):
                raise ValueError("Confirmação já utilizada, cancelada ou expirada.")
            if self.settings.dry_run:
                self.store.mark_order(token, 'SIMULATED')
                return self.store.order(token, user_id)
            try:
                provider_id = await self.api.add(json.loads(row['payload']))
                self.store.mark_order(token, 'SUBMITTED', provider_id=provider_id)
            except UncertainWrite as exc:
                self.store.mark_order(token, 'UNKNOWN', error=str(exc))
            except ProviderError as exc:
                self.store.mark_order(token, 'REJECTED', error=str(exc))
            except BaseException:
                self.store.mark_order(token, 'UNKNOWN', error='Falha inesperada durante envio. Confira manualmente o painel.')
                raise
            return self.store.order(token, user_id)

    async def prepare_action(self, token: str, user_id: int, kind: str) -> dict:
        self.authorize(user_id)
        row = self.store.order(token, user_id)
        if not row or row['state'] != 'SUBMITTED' or not row['provider_id']:
            raise ValueError("Esta ação exige um pedido real enviado por seu usuário neste bot.")
        service = await self.service(row['service_id'], force=True)
        if kind not in {'refill','cancel'} or getattr(service, kind) is False:
            raise ValueError("Esse serviço não disponibiliza a ação solicitada.")
        return self.store.create_action(row, kind, self.settings.dry_run)

    async def submit_action(self, token: str, user_id: int) -> dict:
        self.authorize(user_id)
        async with self.mutation_lock:
            action = self.store.action(token, user_id)
            if not action:
                raise ValueError("Solicitação não encontrada.")
            if action['state'] != 'DRAFT':
                return action
            if bool(action['dry_run']) != self.settings.dry_run:
                raise ValueError("O modo mudou. Crie uma nova solicitação.")
            row = self.store.order(action['order_id'], user_id)
            if not row or row['state'] != 'SUBMITTED' or not row['provider_id']:
                raise ValueError("Pedido indisponível para esta ação.")
            service = await self.service(row['service_id'], force=True)
            if getattr(service, action['kind']) is False:
                raise ValueError("O fornecedor não disponibiliza essa ação para o serviço.")
            if not self.store.claim_action(token, user_id):
                raise ValueError("Confirmação já usada, cancelada ou expirada.")
            if self.settings.dry_run:
                self.store.mark_action(token, 'SIMULATED')
                return self.store.action(token,user_id)
            try:
                if action['kind'] == 'refill':
                    result = {'refill': await self.api.refill(row['provider_id'])}
                else:
                    raw = await self.api.cancel([row['provider_id']])
                    entries = raw if isinstance(raw,list) else [raw]
                    item = next((x for x in entries if isinstance(x,dict) and str(x.get('order')) == row['provider_id']), None)
                    value = item.get('cancel') if item else None
                    if isinstance(value, dict) and value.get('error'):
                        raise ProviderError(self.api.safe_error(value['error']))
                    if value not in (1, '1', True):
                        raise UncertainWrite("Cancelamento retornou formato não confirmado. Confira o painel antes de repetir.")
                    result = {'cancel': 1}
                self.store.mark_action(token, 'SUBMITTED', result=result)
            except UncertainWrite as exc:
                self.store.mark_action(token, 'UNKNOWN', error=str(exc))
            except ProviderError as exc:
                self.store.mark_action(token, 'REJECTED', error=str(exc))
            except BaseException:
                self.store.mark_action(token, 'UNKNOWN', error='Falha inesperada no envio. Confira o painel.')
                raise
            return self.store.action(token,user_id)
