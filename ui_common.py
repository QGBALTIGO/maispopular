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

LOG = logging.getLogger('soupopular_bot')
PAGE = 8
LOCAL_STATES = {
    'DRAFT': '📝 Aguardando confirmação', 'SENDING': '📤 Envio em processamento',
    'SIMULATED': '🧪 Simulação — nenhum pedido enviado', 'SUBMITTED': '📦 Enviado ao fornecedor',
    'UNKNOWN': '⚠️ Envio incerto — verificar no painel', 'REJECTED': '❌ Rejeitado',
    'EXPIRED': '⌛ Orçamento expirado', 'ABORTED': '🚫 Rascunho descartado',
}


class SecretFilter(logging.Filter):
    """Remove credenciais conhecidas até de mensagens/tracebacks de dependências."""
    def __init__(self, secrets: tuple[str, ...]):
        super().__init__()
        self.secrets = tuple(x for x in secrets if x)

    def redact(self, text: str) -> str:
        for value in self.secrets:
            text = text.replace(value, '[segredo ocultado]')
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        return True


def e(value: object) -> str:
    return escape(str(value), quote=True)


def btn(label: str, callback: str) -> Button:
    return Button(label, callback_data=callback)


def panel(context: ContextTypes.DEFAULT_TYPE) -> Panel:
    return context.application.bot_data['panel']


def uid(update: Update) -> int:
    return update.effective_user.id


def category_key(category: str) -> str:
    return hashlib.sha256(category.encode()).hexdigest()[:12]


def pager(prefix: str, page: int, total: int) -> list[Button]:
    pages = max(1, math.ceil(total/PAGE))
    row = []
    if page > 0:
        row.append(btn('⬅️ Anterior', f'{prefix}:{page-1}'))
    row.append(btn(f'{page+1}/{pages}', 'noop'))
    if page+1 < pages:
        row.append(btn('Próxima ➡️', f'{prefix}:{page+1}'))
    return row


async def say(update: Update, text: str, rows: list[list[Button]] | None = None) -> None:
    kwargs = dict(parse_mode='HTML', reply_markup=Keyboard(rows) if rows else None,
                  link_preview_options=LinkPreviewOptions(is_disabled=True))
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, **kwargs)
            return
        except BadRequest as exc:
            if 'message is not modified' in str(exc).lower():
                return
            # Mensagem antiga não editável: envia uma nova, sem reenviar operação da API.
    await update.effective_message.reply_text(text, **kwargs)


def home_rows() -> list[list[Button]]:
    return [[btn('🛍 Catálogo', 'catalog:0'), btn('🔎 Buscar serviço', 'search_prompt')],
            [btn('📦 Meus pedidos', 'orders:0'), btn('💰 Saldo fornecedor', 'balance')],
            [btn('🆔 Meu ID', 'identity'), btn('❓ Como funciona', 'help')]]


async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        raise ApplicationHandlerStop
    if update.effective_chat.type != 'private':
        if update.callback_query:
            await update.callback_query.answer('Abra o bot no privado.', show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text('🔒 Use este bot no chat privado.')
        raise ApplicationHandlerStop
    text = update.effective_message.text or '' if update.effective_message else ''
    command = text.split(maxsplit=1)[0].split('@')[0].lower() if text.startswith('/') else ''
    if uid(update) not in panel(context).settings.admin_ids and command not in {'/meuid', '/start'}:
        message = '🔒 Acesso restrito. Use /meuid para consultar seu ID.'
        if update.callback_query:
            await update.callback_query.answer(message, show_alert=True)
        else:
            await update.effective_message.reply_text(message)
        raise ApplicationHandlerStop


