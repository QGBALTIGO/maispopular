"""Componentes compartilhados da interface Telegram."""
import hashlib
import logging
import math
from html import escape

from telegram import InlineKeyboardButton as Button
from telegram import InlineKeyboardMarkup as Keyboard
from telegram import LinkPreviewOptions, Update
from telegram.error import BadRequest
from telegram.ext import ApplicationHandlerStop, ContextTypes

from engine import Panel

LOG = logging.getLogger("maispopular_bot")
PAGE = 8
LOCAL_STATES = {
    "DRAFT": "📝 Aguardando confirmação", "SENDING": "📤 Enviando",
    "SUBMITTED": "📦 Pedido recebido", "UNKNOWN": "⚠️ Em verificação",
    "REJECTED": "❌ Não realizado", "EXPIRED": "⌛ Orçamento expirado",
    "ABORTED": "🚫 Rascunho descartado",
}


class SecretFilter(logging.Filter):
    def __init__(self, secrets: tuple[str, ...]):
        super().__init__()
        self.secrets = tuple(x for x in secrets if x)

    def redact(self, text: str) -> str:
        for value in self.secrets:
            text = text.replace(value, "[segredo ocultado]")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def e(value: object) -> str:
    return escape(str(value), quote=True)


def btn(label: str, callback: str) -> Button:
    return Button(label, callback_data=callback)


def panel(context: ContextTypes.DEFAULT_TYPE) -> Panel:
    return context.application.bot_data["panel"]


def uid(update: Update) -> int:
    return update.effective_user.id


def category_key(category: str) -> str:
    return hashlib.sha256(category.encode()).hexdigest()[:12]


def pager(prefix: str, page: int, total: int) -> list[Button]:
    pages = max(1, math.ceil(total / PAGE))
    row = []
    if page > 0:
        row.append(btn("⬅️ Anterior", f"{prefix}:{page - 1}"))
    row.append(btn(f"{page + 1}/{pages}", "noop"))
    if page + 1 < pages:
        row.append(btn("Próxima ➡️", f"{prefix}:{page + 1}"))
    return row


async def say(update: Update, text: str, rows: list[list[Button]] | None = None) -> None:
    kwargs = {
        "parse_mode": "HTML",
        "reply_markup": Keyboard(rows) if rows else None,
        "link_preview_options": LinkPreviewOptions(is_disabled=True),
    }
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, **kwargs)
            return
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
    await update.effective_message.reply_text(text, **kwargs)


def home_rows(is_admin: bool = False) -> list[list[Button]]:
    rows = [
        [btn("🛍️ Catálogo", "catalog:0"), btn("🔎 Buscar", "search_prompt")],
        [btn("💳 Adicionar saldo", "deposit"), btn("👛 Minha carteira", "balance")],
        [btn("📦 Meus pedidos", "orders:0"), btn("❓ Ajuda", "help")],
    ]
    if is_admin:
        rows.append([btn("⚙️ Administração", "admin")])
    return rows


async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        raise ApplicationHandlerStop
    if update.effective_chat.type != "private":
        if update.callback_query:
            await update.callback_query.answer("Abra o bot no privado.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("🔒 Use este bot no chat privado.")
        raise ApplicationHandlerStop
    user = update.effective_user
    panel(context).store.register_user(user.id, user.username or "", user.full_name or "")
