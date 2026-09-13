"""Abandoned-interest reminders with frequency caps and opt-out."""

import asyncio
import html
import logging
from urllib.parse import urlencode

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.error import Forbidden, RetryAfter, TelegramError

LOG = logging.getLogger("maispopular_bot")


def _markup(panel, row):
    params = {"platform": row["platform"]}
    if int(row["service_id"]):
        params["service"] = str(row["service_id"])
    url = panel.settings.webapp_url()
    rows = []
    if url:
        rows.append([
            InlineKeyboardButton(
                "🛒 Retomar no catálogo",
                web_app=WebAppInfo(url=f"{url}?{urlencode(params)}"),
            )
        ])
    rows.append([
        InlineKeyboardButton("💬 Falar com o suporte", url="https://t.me/suportemaispopular")
    ])
    rows.append([
        InlineKeyboardButton("Não quero receber lembretes", callback_data="recovery:optout")
    ])
    return InlineKeyboardMarkup(rows)


def _message(row, stage: int) -> str:
    first_name = (row.get("display_name") or row.get("username") or "cliente").split()[0]
    name = html.escape(first_name[:60])
    label = html.escape(row["label"])
    if stage == 1:
        return (
            f"Olá, <b>{name}</b>! 👋\n\n"
            f"Você estava conferindo <b>{label}</b>, mas não concluiu o pedido. "
            "Ele continua disponível no catálogo.\n\n"
            "Confira o valor atual e, se precisar de ajuda antes de comprar, fale com nosso suporte."
        )
    return (
        f"Oi, <b>{name}</b>! Passando para lembrar de <b>{label}</b>.\n\n"
        "Se ainda tiver interesse, você pode continuar de onde parou. A disponibilidade e o valor "
        "atual aparecem antes da confirmação.\n\n"
        "Ficou com alguma dúvida ou quer entender qual opção combina melhor com você? Nosso suporte ajuda."
    )


async def callback(update, context) -> None:
    query = update.callback_query
    await query.answer("Lembretes desativados")
    panel = context.application.bot_data["panel"]
    panel.store.recovery_opt_out(int(update.effective_user.id))
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    await query.message.reply_text(
        "✅ Você não receberá novos lembretes de produtos visualizados."
    )


async def poll_recovery(context) -> None:
    panel = context.application.bot_data["panel"]
    for _ in range(12):
        claimed = panel.store.claim_interest_notification()
        if not claimed:
            return
        row, stage = claimed
        try:
            await context.bot.send_message(
                int(row["user_id"]),
                _message(row, stage),
                parse_mode="HTML",
                reply_markup=_markup(panel, row),
            )
        except RetryAfter as exc:
            panel.store.finish_interest_notification(row["id"], stage, False)
            delay = getattr(exc, "retry_after", 1)
            if hasattr(delay, "total_seconds"):
                delay = delay.total_seconds()
            await asyncio.sleep(min(max(float(delay), 1), 30))
            return
        except Forbidden:
            panel.store.finish_interest_notification(
                row["id"], stage, False, terminal=True
            )
        except TelegramError as exc:
            LOG.warning("Lembrete não entregue: %s", type(exc).__name__)
            panel.store.finish_interest_notification(row["id"], stage, False)
            return
        else:
            panel.store.finish_interest_notification(row["id"], stage, True)
        await asyncio.sleep(0.06)
