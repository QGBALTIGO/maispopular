"""Sorteio promocional com cartelas 1–6 e dados oficiais do Telegram."""

import asyncio
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
    WebAppInfo,
)
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from ui_common import panel, uid

LOG = logging.getLogger("maispopular_bot")
CAMPAIGN_ID = "set26"
REQUIRED_CHANNELS = (
    ("Central de Animes", "@centraldeanimes_baltigo"),
    ("Mangás Brasil", "@mangasbrasil"),
    ("Baltigo World", "@BaltigoWorld"),
    ("Mais Popular", "@MaisPopular"),
)
RESULT_CHAT = "@MaisPopular"


def format_numbers(raw) -> str:
    values = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    return " • ".join(f"{int(value):02d}" for value in values)


def schedule_label(timestamp: int) -> str:
    value = datetime.fromtimestamp(timestamp, ZoneInfo("America/Cuiaba"))
    return value.strftime("%d/%m/%Y às %H:%M")


def _join_keyboard(include_verify: bool = True) -> InlineKeyboardMarkup:
    rows = []
    for index in range(0, len(REQUIRED_CHANNELS), 2):
        rows.append([
            InlineKeyboardButton(name, url=f"https://t.me/{username[1:]}")
            for name, username in REQUIRED_CHANNELS[index:index + 2]
        ])
    if include_verify:
        rows.append([
            InlineKeyboardButton(
                "✅ Confirmar participação", callback_data="raffle:verify"
            )
        ])
    return InlineKeyboardMarkup(rows)


async def membership(bot, user_id: int) -> tuple[bool, list[str]]:
    missing = []
    for name, username in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(username, user_id)
            joined = member.status in {"creator", "administrator", "member"} or (
                member.status == "restricted" and bool(getattr(member, "is_member", False))
            )
        except TelegramError:
            joined = False
        if not joined:
            missing.append(name)
    return not missing, missing


def _share_link(settings, user_id: int) -> str:
    return f"https://t.me/{settings.bot_username}?start=sorteio_{user_id}"


def _cards_text(cards: list[dict]) -> str:
    return "\n".join(
        f"<b>Cartela {index}</b>  <code>{format_numbers(card['numbers'])}</code>"
        for index, card in enumerate(cards, 1)
    )


def _missing_channels_text(missing: list[str]) -> str:
    usernames = {name: username for name, username in REQUIRED_CHANNELS}
    return "\n".join(
        f"▫️ <a href=\"https://t.me/{usernames[name][1:]}\">{html.escape(name)}</a>"
        for name in missing
    )


async def _show_status(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       *, verify: bool = False) -> None:
    store = panel(context).store
    user_id = uid(update)
    data = store.raffle_summary(user_id, CAMPAIGN_ID)
    campaign = data["campaign"]
    if campaign["status"] == "COMPLETED":
        text = "🏆 <b>Sorteio encerrado</b>\n\nConfira o resultado publicado no @MaisPopular."
        await update.effective_message.reply_text(text, parse_mode="HTML")
        return
    if verify:
        complete, missing = await membership(context.bot, user_id)
        if complete:
            data = store.verify_raffle_participant(user_id, CAMPAIGN_ID)
            if data.get("bonusReferrer"):
                try:
                    await context.bot.send_message(
                        data["bonusReferrer"],
                        "🎟 <b>Nova cartela liberada!</b>\n\nSua indicação entrou nos quatro canais e confirmou a participação. Você ganhou mais seis números para o sorteio.",
                        parse_mode="HTML",
                    )
                except TelegramError:
                    LOG.info("Bônus de indicação registrado; aviso privado indisponível.")
        else:
            await update.effective_message.reply_text(
                "🎲 <b>SUA CARTELA ESTÁ QUASE PRONTA</b>\n\n"
                "Para validar sua participação, falta entrar nos canais abaixo:\n\n"
                f"{_missing_channels_text(missing)}\n\n"
                "Depois de entrar, toque em <b>Confirmar participação</b>. "
                "Se estiver tudo certo, seus seis números aparecem na hora.",
                parse_mode="HTML",
                reply_markup=_join_keyboard(),
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            return
    data = store.raffle_summary(user_id, CAMPAIGN_ID)
    participant = data["participant"]
    if not participant or participant["status"] != "ELIGIBLE":
        await update.effective_message.reply_text(
            "🎲 <b>SORTEIO MAIS POPULAR</b>\n\n"
            "Cinco pessoas vão ganhar <b>1 acesso por 30 dias</b> e poderão escolher entre Crunchyroll Premium ou Netflix 4K.\n\n"
            "Você recebe uma cartela com seis números de 1 a 6. Cada amigo válido libera outra cartela inteira para você.\n\n"
            f"🗓 <b>Resultado:</b> {schedule_label(campaign['scheduled_at'])}\n"
            "📣 <b>Ao vivo:</b> @MaisPopular\n\n"
            "Entre nos quatro canais e confirme sua participação:",
            parse_mode="HTML",
            reply_markup=_join_keyboard(),
        )
        return
    share = _share_link(panel(context).settings, user_id)
    share_url = (
        "https://t.me/share/url?url=" + share
        + "&text=Participe%20do%20Sorteio%20Mais%20Popular%20comigo!"
    )
    action_row = [InlineKeyboardButton("📨 Convidar amigos", url=share_url)]
    webapp_url = panel(context).settings.webapp_url()
    if webapp_url:
        action_row.append(
            InlineKeyboardButton(
                "🛒 Abrir catálogo", web_app=WebAppInfo(url=webapp_url)
            )
        )
    await update.effective_message.reply_text(
        "🎟 <b>SUAS CARTELAS ESTÃO CONFIRMADAS</b>\n\n"
        f"{_cards_text(data['cards'])}\n\n"
        f"👥 <b>Indicações válidas:</b> {data['referrals']}\n"
        f"🎯 <b>Chances atuais:</b> {len(data['cards']) * 6} números\n\n"
        "A cada amigo que entrar pelo seu link, participar e permanecer nos quatro canais, você recebe outra cartela com seis números.\n\n"
        f"<code>{html.escape(share)}</code>\n\n"
        f"🗓 {schedule_label(campaign['scheduled_at'])} · resultado no @MaisPopular",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            action_row,
            [InlineKeyboardButton("🔄 Atualizar participação", callback_data="raffle:verify")],
        ]),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def open_raffle(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      referrer_id: int = 0) -> None:
    panel(context).store.join_raffle(uid(update), referrer_id, CAMPAIGN_ID)
    await _show_status(update, context, verify=True)


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await open_raffle(update, context)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = (query.data or "").split(":")
    if len(action) >= 3 and action[1] == "prize":
        row = panel(context).store.choose_raffle_prize(CAMPAIGN_ID, uid(update), action[2])
        label = "Crunchyroll Premium" if row["prize_choice"] == "crunchyroll" else "Netflix 4K"
        await query.edit_message_text(
            f"✅ <b>Prêmio escolhido: {label}</b>\n\nO suporte recebeu sua escolha e fará a entrega do acesso de 30 dias.",
            parse_mode="HTML",
        )
        for admin_id in panel(context).settings.admin_ids:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"🏆 Vencedor <code>{uid(update)}</code> escolheu <b>{label}</b>. Confira a entrega no painel.",
                    parse_mode="HTML",
                )
            except TelegramError:
                pass
        return
    await _show_status(update, context, verify=action[1] == "verify")


async def _eligible_candidate(context, campaign_id: str, values: list[int], position: int):
    store = panel(context).store
    for candidate in store.raffle_candidates(campaign_id, values, position):
        complete, _ = await membership(context.bot, int(candidate["user_id"]))
        if complete:
            return candidate
        store.disqualify_raffle_user(campaign_id, int(candidate["user_id"]), "Saiu de um canal obrigatório")
    return None


async def _run_draw(context: ContextTypes.DEFAULT_TYPE, campaign: dict) -> None:
    store = panel(context).store
    campaign_id = campaign["id"]
    existing_winners = store.raffle_admin_summary(campaign_id)["winners"]
    if not existing_winners and not store.raffle_rolls(campaign_id, 1):
        await context.bot.send_message(
            RESULT_CHAT,
            "🎲 <b>O SORTEIO COMEÇOU!</b>\n\nSerão cinco rodadas. Em cada uma, o Telegram lançará seis dados. A cartela exata vence; se não houver, ganha a cartela com a menor distância entre as seis posições.\n\nBoa sorte!",
            parse_mode="HTML",
        )
    for position in range(1, int(campaign["draw_count"]) + 1):
        if any(int(row["position"]) == position for row in store.raffle_admin_summary(campaign_id)["winners"]):
            continue
        rolls = store.raffle_rolls(campaign_id, position)
        if not rolls:
            await context.bot.send_message(
                RESULT_CHAT,
                f"<b>{position}ª RODADA</b> · preparando os seis dados…",
                parse_mode="HTML",
            )
        for roll_position in range(len(rolls) + 1, 7):
            message = await context.bot.send_dice(RESULT_CHAT, emoji="🎲")
            value = int(message.dice.value)
            store.save_raffle_roll(campaign_id, position, roll_position, value, message.message_id)
            await asyncio.sleep(3.6)
        rolls = store.raffle_rolls(campaign_id, position)
        values = [int(row["value"]) for row in rolls]
        message_ids = [int(row["message_id"]) for row in rolls]
        candidate = await _eligible_candidate(context, campaign_id, values, position)
        if not candidate:
            raise RuntimeError("Nenhuma cartela elegível permaneceu após a validação.")
        store.save_raffle_winner(campaign_id, position, candidate, values, message_ids)
        exact = candidate["distance"] == 0
        mention = (
            f"@{html.escape(candidate['username'])}" if candidate["username"]
            else html.escape(candidate["display_name"] or f"ID {candidate['user_id']}")
        )
        await context.bot.send_message(
            RESULT_CHAT,
            f"🏆 <b>{position}º VENCEDOR</b>\n\n"
            f"🎲 Dados: <code>{format_numbers(values)}</code>\n"
            f"🎟 Cartela: <code>{format_numbers(candidate['numbers'])}</code>\n"
            f"👤 {mention}\n"
            + ("✨ <b>Cartela exata!</b>" if exact else f"📏 Menor distância da rodada: <b>{candidate['distance']}</b>"),
            parse_mode="HTML",
        )
        try:
            await context.bot.send_message(
                int(candidate["user_id"]),
                f"🎉 <b>Você ganhou o {position}º prêmio!</b>\n\nEscolha seu acesso de 30 dias:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Crunchyroll Premium", callback_data="raffle:prize:crunchyroll"),
                    InlineKeyboardButton("Netflix 4K", callback_data="raffle:prize:netflix"),
                ]]),
            )
        except TelegramError:
            LOG.warning("Não foi possível avisar um vencedor no privado.")
        await asyncio.sleep(2)
    store.finish_raffle(campaign_id)
    await context.bot.send_message(
        RESULT_CHAT,
        "🎉 <b>SORTEIO ENCERRADO</b>\n\nOs cinco vencedores foram definidos e receberam no privado a opção de escolher entre Crunchyroll Premium e Netflix 4K por 30 dias.\n\nObrigado a todos que participaram!",
        parse_mode="HTML",
    )


async def poll_raffle(context: ContextTypes.DEFAULT_TYPE) -> None:
    app = context.application
    if app.bot_data.get("raffle_running"):
        return
    campaign = panel(context).store.due_raffle()
    if not campaign:
        return
    app.bot_data["raffle_running"] = True
    try:
        if not panel(context).store.begin_raffle(campaign["id"]):
            if not app.bot_data.get("raffle_insufficient_notified"):
                app.bot_data["raffle_insufficient_notified"] = True
                for admin_id in panel(context).settings.admin_ids:
                    try:
                        await context.bot.send_message(
                            admin_id,
                            "⚠️ O sorteio chegou ao horário, mas ainda não há cinco participantes elegíveis. A apuração permanecerá aguardando.",
                        )
                    except TelegramError:
                        pass
            return
        await _run_draw(context, panel(context).store.raffle_campaign(campaign["id"]))
    except RetryAfter as exc:
        delay = getattr(exc, "retry_after", 5)
        if hasattr(delay, "total_seconds"):
            delay = delay.total_seconds()
        await asyncio.sleep(min(float(delay), 30))
    except TelegramError as exc:
        LOG.warning("Sorteio aguardando Telegram: %s", type(exc).__name__)
    except Exception:
        LOG.exception("Falha controlada durante a apuração do sorteio.")
    finally:
        app.bot_data["raffle_running"] = False
