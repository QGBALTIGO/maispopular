"""Diagnóstico SOMENTE LEITURA. Nunca envia pedidos, reposições ou cancelamentos."""
import asyncio
import sys

from config import Settings
from domain import money
from payments import Cakto, PaymentError
from provider import ProviderError, ServiceProvider


async def main() -> None:
    settings = Settings.load()
    api = ServiceProvider(settings.api_key)
    payments = Cakto(settings.cakto_client_id, settings.cakto_client_secret)
    try:
        balance = await api.balance()
        services = await api.services(force=True)
        for amount, offer_id in settings.cakto_offers.items():
            await payments.validate_offer(offer_id, amount)
        print('Autenticação: OK')
        print('Saldo:',money(balance['balance'],balance['currency']))
        print('Serviços interpretados:',len(services))
        print('Tipos encontrados:',', '.join(sorted({s.kind for s in services})))
        print('Ofertas Cakto validadas:', ', '.join(f'R$ {x}' for x in sorted(settings.cakto_offers)))
        print('Nenhum pedido, reposição ou cancelamento foi enviado.')
    finally:
        await api.close()
        await payments.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (ValueError, ProviderError, PaymentError) as exc:
        print(f'Falha no diagnóstico: {exc}',file=sys.stderr)
        sys.exit(1)
