"""Persistent, restart-safe Telegram broadcast worker."""

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, WebAppInfo
from telegram.error import Forbidden, RetryAfter, TelegramError

LOG = logging.getLogger("maispopular_bot")


def _markup(panel, job):
    label, target = job["button_text"], job["button_target"]
    if not label or target == "none":
        return None
    if target == "support":
        button = InlineKeyboardButton(label, url="https://t.me/suportemaispopular")
    elif target == "baltigoflix":
        button = InlineKeyboardButton(label, url="https://baltigoflix.com.br")
    else:
        base = panel.settings.webapp_url()
        if not base:
            return None
        view = {"catalog": "platforms", "orders": "orders", "wallet": "wallet"}[target]
        button = InlineKeyboardButton(label, web_app=WebAppInfo(url=f"{base}?view={view}"))
    return InlineKeyboardMarkup([[button]])


async def poll_broadcasts(context) -> None:
    """Sends bounded batches; all progress remains in SQLite for the WebApp."""
    panel = context.application.bot_data["panel"]
    for _ in range(20):
        claimed = panel.store.claim_broadcast_delivery()
        if not claimed:
            return
        job, user_id = claimed
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=job["message"],
                reply_markup=_markup(panel, job),
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except RetryAfter as exc:
            panel.store.finish_broadcast_delivery(job["id"], user_id, "PENDING")
            delay = getattr(exc, "retry_after", 1)
            if hasattr(delay, "total_seconds"):
                delay = delay.total_seconds()
            await asyncio.sleep(min(max(float(delay), 1), 30))
            return
        except Forbidden:
            panel.store.finish_broadcast_delivery(job["id"], user_id, "FAILED", "Bot bloqueado pelo usuário")
        except TelegramError as exc:
            panel.store.finish_broadcast_delivery(job["id"], user_id, "FAILED", type(exc).__name__)
        else:
            panel.store.finish_broadcast_delivery(job["id"], user_id, "SENT")
        await asyncio.sleep(0.06)
