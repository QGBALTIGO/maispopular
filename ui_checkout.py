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

from ui_catalog import search_page

async def begin_order(update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int) -> None:
    p = panel(context)
    s = await p.service(service_id, force=True)
    if not s.supported:
        raise ValueError('Este tipo ainda não tem formulário de pedido.')
    p.store.abort_drafts(uid(update))
    context.user_data['flow'] = {'step':'target','service_id':service_id,'expires':time.time()+900}
    await say(update,f'🛒 <b>Novo pedido</b>\n\n{e(s.name)}\n\n'
              '🔗 Envie o link ou @usuário exigido pelo serviço. Para publicações, use o link da publicação, não o do perfil.\n\n'
              'Ao confirmar, esse destino será transmitido ao fornecedor.\nUse /cancelar para descartar.',
              [[btn('🚫 Descartar','home')]])


async def quote_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flow = context.user_data['flow']
    row = await panel(context).quote(uid(update),flow['service_id'],flow['target'],flow.get('value'),flow.get('answer'))
    payload = json.loads(row['payload'])
    quantity = payload.get('quantity')
    if 'comments' in payload:
        quantity = len(payload['comments'].splitlines())
    mode = '🧪 <b>SIMULAÇÃO: nada será enviado.</b>' if row['dry_run'] else '⚠️ <b>REAL: a confirmação utiliza seu saldo SouPopular.</b>'
    text = (f'🧾 <b>Confira seu pedido</b>\n\n{e(row["service_name"])}\n'
            f'🆔 Serviço: {row["service_id"]}\n🔗 Destino: <code>{e(payload["link"])}</code>\n'
            f'📦 Quantidade: {quantity if quantity is not None else "1 pacote"}\n'
            f'💵 Custo estimado: <b>{e(money(row["cost"],row["currency"]))}</b>\n')
    if 'answer_number' in payload:
        text += f'🗳 Alternativa: {payload["answer_number"]}\n'
    if 'comments' in payload:
        preview = payload['comments'][:300]
        text += f'💬 Comentários (prévia):\n<pre>{e(preview)}</pre>\n'
    text += ('\nO preço será conferido novamente antes do envio. Orçamento válido por 5 minutos. '
             'O bot não garante entrega, reposição, cancelamento ou reembolso.\n\n'+mode)
    context.user_data.pop('flow',None)
    await say(update,text,[[btn('🧪 Confirmar simulação' if row['dry_run'] else '✅ Confirmar pedido REAL',f'confirm:{row["id"]}')],
                           [btn('🚫 Descartar','home')]])


async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flow = context.user_data.get('flow')
    if not flow or flow.get('expires',0) < time.time():
        context.user_data.pop('flow',None)
        await say(update,'Use /start para abrir o menu ou /buscar seguido do nome de um serviço.',home_rows())
        return
    value = update.effective_message.text.strip()
    if flow['step'] == 'search':
        context.user_data['search'] = value[:100]
        context.user_data.pop('flow',None)
        await search_page(update,context)
        return
    service = await panel(context).service(flow['service_id'])
    if flow['step'] == 'target':
        flow['target'] = validate_target(value)
        if service.kind.casefold() == 'package':
            await quote_page(update,context)
            return
        flow['step'] = 'value'
        prompt = '💬 Envie os comentários, um por linha, em uma única mensagem (até 3.500 caracteres).' \
            if service.kind.casefold() == 'custom comments' else '📦 Envie a quantidade inteira, sem pontos ou vírgulas. Exemplo: 1000.'
        await say(update,f'{prompt}\n\nMínimo: <b>{service.minimum}</b> · Máximo: <b>{service.maximum}</b>\n\n/cancelar — descartar.')
    elif flow['step'] == 'value':
        flow['value'] = value
        if service.kind.casefold() == 'poll':
            # Valida a quantidade antes de pedir a alternativa.
            from domain import build_payload
            build_payload(service,flow['target'],value,'1')
            flow['step'] = 'answer'
            await say(update,'🗳 Envie o número positivo da alternativa da enquete.')
        else:
            await quote_page(update,context)
    elif flow['step'] == 'answer':
        flow['answer'] = value
        await quote_page(update,context)


