"""Bot administrativo Telegram / SouPopular. Execute: python bot.py"""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import logging
import math
import os
from pathlib import Path
import sys
import time

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard
from telegram import BotCommand, LinkPreviewOptions, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import (Application, ApplicationHandlerStop, CallbackQueryHandler,
                          CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters)

from config import Settings
from domain import STATUS_PT, money, normalize, validate_target
from engine import Panel
from provider import ProviderError, SouPopular
from storage import Store

from ui_common import (LOG, PAGE, LOCAL_STATES, SecretFilter, e, btn, panel, uid,
                       category_key, pager, say, home_rows, guard)

async def home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    if uid(update) not in p.settings.admin_ids:
        await say(update, f'🔒 <b>Bot administrativo</b>\n\nSeu ID é <code>{uid(update)}</code>.\n'
                  'O responsável precisa incluir esse número em ADMIN_IDS para liberar o acesso.')
        return
    context.user_data.pop('flow', None)
    p.store.abort_drafts(uid(update))
    mode = '🧪 <b>Modo de teste:</b> pedidos, reposições e cancelamentos não são enviados.' if p.settings.dry_run else \
           '🟢 <b>Modo real:</b> confirmar um pedido utiliza o saldo da sua conta SouPopular.'
    await say(update, f'🚀 <b>{e(p.settings.bot_name)}</b>\n\n'
              'Catálogo, pedidos e acompanhamento em um só lugar.\n\n'
              f'{mode}\n\n🔐 Acesso administrativo · Sem cobrança de clientes nesta versão.', home_rows())


async def identity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await say(update, f'🆔 <b>Seu ID do Telegram</b>\n\n<code>{uid(update)}</code>\n\n'
              'Use esse número em ADMIN_IDS. Nunca envie tokens ou chaves pelo chat.')


async def help_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await say(update, '❓ <b>Como funciona</b>\n\n'
              'Abra o catálogo, escolha o serviço e informe o destino e a quantidade. '
              'O bot apresenta um orçamento antes de pedir sua confirmação.\n\n'
              '<b>Antes de confirmar</b>\nConfira as regras do serviço, o destino, a moeda e o modo de operação. '
              'O valor é estimado; a cobrança final é informada pelo fornecedor no status.\n\n'
              '<b>Modo de teste</b>\nConsulta catálogo e saldo reais, mas não envia pedidos, reposições ou cancelamentos.\n\n'
              '<b>Envio incerto</b>\nUma falha de conexão pode acontecer depois que o fornecedor aceitou a solicitação. '
              'Confira no painel antes de criar outro pedido. O bot não repete esse envio automaticamente.\n\n'
              '/buscar termo — procurar serviços\n/pedidos — histórico deste bot\n'
              '/pedido ID — consultar seu pedido pelo ID do fornecedor\n/saldo — saldo da conta SouPopular\n'
              '/cancelar — descartar formulário, sem cancelar pedidos enviados\n/meuid — seu ID\n\n'
              'Assinaturas e envios recorrentes não têm formulário nesta versão. '
              'Reposição e cancelamento dependem da aceitação do fornecedor.', [[btn('🏠 Início','home')]])


async def balance_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = await panel(context).api.balance()
    await say(update, f'💰 <b>Saldo da conta SouPopular</b>\n\n'
              f'<b>{e(money(result["balance"], result["currency"]))}</b>\n\n'
              'Este é o saldo do fornecedor, não uma carteira de clientes. A recarga é feita no próprio painel.',
              [[btn('🔄 Atualizar','balance'), btn('🏠 Início','home')]])


async def catalog_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    services = await panel(context).catalog()
    categories = sorted({s.category for s in services}, key=normalize)
    page = min(max(page,0), max(0,(len(categories)-1)//PAGE))
    rows = [[btn(f'📂 {category[:53]}',f'category:{category_key(category)}:0')]
            for category in categories[page*PAGE:(page+1)*PAGE]]
    if categories:
        rows.append(pager('catalog',page,len(categories)))
    rows += [[btn('🔎 Buscar','search_prompt'),btn('🏠 Início','home')]]
    await say(update, f'🛍 <b>Catálogo de serviços</b>\n\n'
              f'{len(services)} serviços · {len(categories)} categorias\n'
              'Os nomes e as condições são informados pelo fornecedor.\n\n'
              + ('Escolha uma categoria:' if categories else 'Nenhum serviço disponível para a configuração atual.'), rows)


async def category_page(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, page: int) -> None:
    services = [s for s in await panel(context).catalog() if category_key(s.category) == key]
    if not services:
        raise ValueError('Categoria indisponível. Reabra o catálogo.')
    page = min(max(page,0), (len(services)-1)//PAGE)
    rows = [[btn(f'#{s.id} · {s.name[:47]}',f'service:{s.id}')] for s in services[page*PAGE:(page+1)*PAGE]]
    rows += [pager(f'category:{key}',page,len(services)),[btn('📂 Categorias','catalog:0'),btn('🏠 Início','home')]]
    await say(update,f'📂 <b>{e(services[0].category)}</b>\n\n{len(services)} serviços. Escolha um para conferir os detalhes.',rows)


async def search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    panel(context).store.abort_drafts(uid(update))
    context.user_data['flow'] = {'step':'search','expires':time.time()+900}
    await say(update,'🔎 <b>Buscar serviço</b>\n\nEnvie um nome, categoria ou ID.\nExemplo: <code>Telegram</code>.',
              [[btn('🏠 Voltar','home')]])


async def search_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    term = context.user_data.get('search','')
    words = normalize(term).split()
    services = [s for s in await panel(context).catalog()
                if all(word in normalize(f'{s.id} {s.name} {s.category}') for word in words)]
    page = min(max(page,0), max(0,(len(services)-1)//PAGE))
    rows = [[btn(f'#{s.id} · {s.name[:47]}',f'service:{s.id}')] for s in services[page*PAGE:(page+1)*PAGE]]
    if services:
        rows.append(pager('search',page,len(services)))
    rows += [[btn('🔎 Nova busca','search_prompt'),btn('🏠 Início','home')]]
    await say(update,f'🔎 <b>Resultados para “{e(term)}”</b>\n\n{len(services)} serviços encontrados.',rows)


async def service_page(update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int) -> None:
    p = panel(context)
    s = await p.service(service_id)
    balance = await p.api.balance()
    unit = ('por pacote (confirmar a convenção no painel)' if s.kind.casefold() == 'package'
            else ('por 1.000 unidades' if s.supported else '(unidade não homologada neste bot)'))
    flags = lambda value: 'Sim' if value is True else ('Não' if value is False else 'Não informado pela API')
    text = (f'🛍 <b>{e(s.name)}</b>\n\n'
            f'🆔 Serviço: <code>{s.id}</code>\n📂 Categoria: {e(s.category)}\n'
            f'🧩 Tipo: {e(s.kind)}\n💵 Tarifa: <b>{e(money(s.rate,balance["currency"]))}</b> {unit}\n'
            f'📏 Mínimo: {s.minimum} · Máximo: {s.maximum}\n'
            f'♻️ Reposição: {flags(s.refill)}\n🚫 Cancelamento: {flags(s.cancel)}\n\n'
            f'<b>Descrição do fornecedor</b>\n{e(s.description) if s.description else "A API não forneceu uma descrição. Consulte as regras no painel antes de pedir."}')
    rows = []
    if s.supported:
        rows.append([btn('🛒 Montar pedido',f'buy:{s.id}')])
    else:
        text += '\n\n⚠️ Este tipo está disponível apenas para consulta; ainda não tem formulário de compra.'
    rows += [[Button('📑 Conferir regras no painel',url='https://soupopular.net/services')],
             [btn('📂 Categoria',f'category:{category_key(s.category)}:0'),btn('🏠 Início','home')]]
    await say(update,text,rows)


