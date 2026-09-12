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

def order_text(row: dict) -> str:
    payload = json.loads(row['payload'])
    status = json.loads(row['status_json'])
    text = (f'📦 <b>Detalhes do pedido</b>\n\n{e(row["service_name"])}\n'
            f'🆔 ID local: <code>{row["id"]}</code>\n'
            f'🧾 ID no fornecedor: <code>{e(row["provider_id"] or "não disponível")}</code>\n'
            f'📋 Situação local: {e(LOCAL_STATES.get(row["state"],row["state"]))}\n'
            f'🔗 Destino: <code>{e(payload["link"])}</code>\n'
            f'💵 Custo estimado: {e(money(row["cost"],row["currency"]))}\n')
    if row['state'] == 'SUBMITTED':
        text += f'📡 Status fornecedor: {e(STATUS_PT.get(row["provider_status"].lower(),row["provider_status"]))}\n'
    if 'charge' in status:
        try:
            text += f'💳 Cobrança informada: {e(money(status["charge"],status.get("currency",row["currency"])))}\n'
        except ValueError:
            text += '💳 Cobrança: formato não reconhecido na resposta.\n'
    if 'start_count' in status:
        text += f'🏁 Contagem inicial: {e(str(status["start_count"])[:100])}\n'
    if 'remains' in status:
        text += f'📊 Quantidade restante: {e(str(status["remains"])[:100])}\n'
    date = datetime.fromtimestamp(row['created_at'],timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
    text += f'🗓 Criado em: {date}'
    if row['state'] == 'SIMULATED':
        text += '\n\n🧪 Nenhum pedido foi enviado e nenhum saldo foi consumido por esta simulação.'
    if row['error']:
        text += f'\n\n⚠️ {e(row["error"])}'
    if row['state'] == 'UNKNOWN':
        text += '\n\n<b>Não repita o pedido.</b> Verifique no painel e consulte o procedimento /resolver no README.'
    return text


async def orders_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    store = panel(context).store
    rows_data,total = store.list_orders(uid(update),max(page,0))
    pages = max(1,math.ceil(total/PAGE))
    if page >= pages:
        page = pages-1
        rows_data,total = store.list_orders(uid(update),page)
    rows = [[btn(f'{r["provider_id"] or r["id"][:8]} · {r["service_name"][:38]}',f'order:{r["id"]}')] for r in rows_data]
    if total:
        rows.append(pager('orders',page,total))
    rows.append([btn('🏠 Início','home')])
    await say(update,'📦 <b>Meus pedidos</b>\n\n'+(f'{total} registros criados neste bot. Escolha um para acompanhar.' if total else 'Você ainda não concluiu nenhum pedido ou simulação.'),rows)


async def order_page(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str, *, refresh: bool = False) -> None:
    p = panel(context)
    row = p.store.order(token,uid(update))
    if not row:
        raise ValueError('Pedido não encontrado para seu usuário.')
    warning = ''
    if refresh and row['state'] == 'SUBMITTED' and row['provider_id']:
        try:
            result = await p.api.status(row['provider_id'])
            p.store.update_status(token,result)
            row = p.store.order(token,uid(update))
        except ProviderError as exc:
            warning = f'\n\n⚠️ Consulta indisponível: {e(exc)}\nMostrando o último estado salvo.'
    rows = []
    if row['state'] == 'SUBMITTED':
        rows.append([btn('🔄 Atualizar status',f'update:{token}')])
        rows.append([btn('♻️ Solicitar reposição',f'action:refill:{token}'),btn('🚫 Pedir cancelamento',f'action:cancel:{token}')])
    for action in p.store.actions_for(token,uid(update)):
        data = json.loads(action['result_json'])
        if data.get('refill'):
            rows.append([btn(f'♻️ Status reposição #{data["refill"]}',f'refill_status:{action["id"]}')])
        if action['state'] == 'UNKNOWN':
            warning += f'\n\n⚠️ Ação {e(action["kind"])} incerta: <code>{action["id"]}</code>. Confira o painel.'
    rows.append([btn('📦 Meus pedidos','orders:0'),btn('🏠 Início','home')])
    await say(update,order_text(row)+warning,rows)


async def action_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str, kind: str) -> None:
    p = panel(context)
    action = await p.prepare_action(token,uid(update),kind)
    order = p.store.order(token,uid(update))
    name = 'reposição' if kind == 'refill' else 'cancelamento'
    mode = '🧪 Modo de teste: a solicitação não será enviada.' if action['dry_run'] else '🟢 Modo real: a solicitação será enviada ao fornecedor.'
    await say(update,f'⚠️ <b>Solicitar {name}</b>\n\nPedido: <code>{order["provider_id"]}</code>\n\n'
              f'A solicitação depende das regras e da aceitação do fornecedor. Solicitar {name} não garante sua execução nem reembolso.\n\n{mode}',
              [[btn('✅ Confirmar solicitação',f'action_confirm:{action["id"]}')],[btn('↩️ Voltar ao pedido',f'order:{token}')]])


async def action_result(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str) -> None:
    p = panel(context)
    result = await p.submit_action(token,uid(update))
    text = f'📨 <b>Solicitação</b>\n\nID local: <code>{result["id"]}</code>\n'
    if result['state'] == 'SIMULATED':
        text += '🧪 Simulação concluída. Nada foi enviado ao fornecedor.'
    elif result['state'] == 'SUBMITTED':
        text += '✅ Solicitação recebida pelo fornecedor. Isso não significa que a execução já terminou.'
    else:
        text += f'{e(LOCAL_STATES.get(result["state"],result["state"]))}\n{e(result["error"])}'
    await say(update,text,[[btn('📦 Ver pedido',f'order:{result["order_id"]}')]])


