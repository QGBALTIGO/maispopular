"""Diagnóstico SOMENTE LEITURA. Nunca envia pedidos, reposições ou cancelamentos."""
import asyncio
import os
import sys

from dotenv import load_dotenv

from domain import money
from provider import ProviderError, ServiceProvider


async def main() -> None:
    load_dotenv(override=False)
    key = os.getenv('PROVIDER_API_KEY','').strip()
    if not key or key.startswith('COLE_'):
        raise ValueError('Configure PROVIDER_API_KEY no .env.')
    api = ServiceProvider(key)
    try:
        balance = await api.balance()
        services = await api.services(force=True)
        print('Autenticação: OK')
        print('Saldo:',money(balance['balance'],balance['currency']))
        print('Serviços interpretados:',len(services))
        print('Tipos encontrados:',', '.join(sorted({s.kind for s in services})))
        print('Nenhum pedido, reposição ou cancelamento foi enviado.')
    finally:
        await api.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (ValueError,ProviderError) as exc:
        print(f'Falha no diagnóstico: {exc}',file=sys.stderr)
        sys.exit(1)
