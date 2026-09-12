"""Carteira e recarga Pix pela Cakto."""
import re
import time
from io import BytesIO

import qrcode
from telegram import InlineKeyboardButton as Button
from telegram import InlineKeyboardMarkup as Keyboard
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from domain import money_brl
from payments import validate_customer
from ui_common import btn, e, panel, say, uid

PAYMENT_LABELS = {
    "CREATED": "📝 Preparando", "CREATING": "⚙️ Gerando Pix",
    "PENDING": "⏳ Aguardando pagamento", "PAID": "✅ Pago e creditado",
    "FAILED": "❌ Não concluído", "UNKNOWN": "⚠️ Confirmação pendente",
    "REVERSED": "↩️ Estornado",
}


async def deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    minimum = int(p.settings.min_deposit_brl)
    maximum = int(p.settings.max_deposit_brl)
    context.user_data.pop("flow", None)
    presets = sorted({minimum, 50, 100, 200})
    presets = [x for x in presets if minimum <= x <= maximum]
    rows = [[btn(money_brl(value), f"deposit_amount:{value}") for value in presets[i:i + 2]]
            for i in range(0, len(presets), 2)]
    rows += [[btn("✍️ Outro valor", "deposit_custom")],
             [btn("👛 Minha carteira", "balance"), btn("🏠 Início", "home")]]
    await say(update,
        f"💳 <b>Adicionar saldo via Pix</b>\n\n"
        f"Escolha um valor entre <b>{money_brl(minimum)}</b> e <b>{money_brl(maximum)}</b>, "
        f"em múltiplos de {money_brl(p.settings.cakto_unit_price_brl)}.\n\n"
        "Após a aprovação do Pix, o saldo entra automaticamente na sua carteira.", rows)


async def choose_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         amount: int | None = None) -> None:
    p = panel(context)
    if amount is None:
        context.user_data["flow"] = {"step": "deposit_amount", "expires": time.time() + 900}
        await say(update, "✍️ <b>Valor da recarga</b>\n\nEnvie somente o valor inteiro em reais. Exemplo: <code>30</code>.",
                  [[btn("🚫 Cancelar", "deposit")]])
        return
    minimum, maximum = int(p.settings.min_deposit_brl), int(p.settings.max_deposit_brl)
    if not minimum <= amount <= maximum:
        raise ValueError(f"A recarga deve ficar entre R$ {minimum} e R$ {maximum}.")
    if amount % p.settings.cakto_unit_price_brl:
        raise ValueError(f"Escolha um valor múltiplo de R$ {p.settings.cakto_unit_price_brl}.")
    context.user_data["flow"] = {"step": "deposit_name", "amount": amount,
                                 "expires": time.time() + 900}
    await say(update,
        f"💳 Recarga de <b>{money_brl(amount)}</b>\n\n"
        "👤 Envie seu <b>nome completo</b>, igual ao cadastro do CPF.\n\n"
        "Seus dados serão usados somente para gerar e conciliar esta cobrança Pix.",
        [[btn("🚫 Cancelar", "deposit")]])


async def deposit_input(update: Update, context: ContextTypes.DEFAULT_TYPE, value: str) -> None:
    flow = context.user_data["flow"]
    step = flow["step"]
    try:
        await update.effective_message.delete()
    except TelegramError:
        # A cobrança continua segura mesmo se o Telegram não permitir apagar a mensagem.
        pass
    if step == "deposit_amount":
        raw = re.sub(r"\s+", "", value).replace("R$", "")
        if not raw.isdigit():
            raise ValueError("Envie um valor inteiro em reais, sem centavos. Exemplo: 30.")
        await choose_deposit(update, context, int(raw))
    elif step == "deposit_name":
        if len(value.strip()) < 5 or " " not in value.strip():
            raise ValueError("Informe seu nome completo.")
        flow["name"] = value.strip()[:120]
        flow["step"] = "deposit_email"
        await say(update, "📧 Agora envie seu <b>e-mail</b>.")
    elif step == "deposit_email":
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()):
            raise ValueError("Informe um e-mail válido.")
        flow["email"] = value.strip().lower()[:160]
        flow["step"] = "deposit_phone"
        await say(update, "📱 Envie seu <b>telefone com DDD</b>. Exemplo: <code>67999999999</code>.")
    elif step == "deposit_phone":
        phone = re.sub(r"\D", "", value)
        if not 10 <= len(phone) <= 13:
            raise ValueError("Informe um telefone válido com DDD.")
        flow["phone"] = phone
        flow["step"] = "deposit_cpf"
        await say(update, "🪪 Envie seu <b>CPF</b> (somente números).\n\n"
                  "O CPF é exigido pelo processador para gerar a cobrança.")
    elif step == "deposit_cpf":
        customer = validate_customer(flow["name"], flow["email"], flow["phone"], value)
        amount = int(flow["amount"])
        context.user_data.pop("flow", None)
        await say(update, "⚙️ <b>Gerando seu Pix…</b>\n\nIsso pode levar alguns segundos.")
        payment = await panel(context).create_payment(uid(update), amount, customer)
        await payment_page(update, context, payment["id"], send_qr=True)


async def payment_page(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str,
                       *, refresh: bool = False, retry: bool = False, send_qr: bool = False) -> None:
    p = panel(context)
    row = p.store.payment(token, uid(update))
    if not row:
        raise ValueError("Recarga não encontrada.")
    if retry:
        row = await p.retry_payment(token, uid(update))
    elif refresh and row["cakto_order_id"]:
        row, _ = await p.reconcile_payment(token)
    status = PAYMENT_LABELS.get(row["status"], row["status"])
    text = (f"💳 <b>Recarga {token[:8].upper()}</b>\n\n"
            f"💰 Valor: <b>{money_brl(row['amount_cents'] / 100)}</b>\n"
            f"📌 Situação: {e(status)}")
    if row["expires_at"] and row["status"] == "PENDING":
        text += f"\n⌛ Validade do Pix: {e(row['expires_at'])}"
    if row["error"]:
        text += f"\n\n⚠️ {e(row['error'])}"
    rows = []
    if row["status"] == "UNKNOWN":
        rows.append([btn("🔄 Tentar gerar novamente", f"payment_retry:{token}")])
    if row["status"] == "PENDING":
        rows.append([btn("🔄 Já paguei · verificar", f"payment_refresh:{token}")])
        if row["checkout_url"].startswith("https://pay.cakto.com.br/"):
            rows.append([Button("🔗 Abrir página do Pix", url=row["checkout_url"])])
    rows.append([btn("👛 Minha carteira", "balance"), btn("🏠 Início", "home")])
    await say(update, text, rows)
    if refresh and row["status"] in {"PAID", "REVERSED", "FAILED"}:
        p.store.payment_notified(row["id"], row["provider_status"])
    if send_qr and row["status"] == "PENDING" and row["qr_code"]:
        image = qrcode.make(row["qr_code"])
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        caption = (f"📲 <b>Pix copia e cola</b>\n\n<code>{e(row['qr_code'])}</code>\n\n"
                   f"Valor da recarga: <b>{money_brl(row['amount_cents'] / 100)}</b>")
        await update.effective_message.reply_photo(
            photo=buffer, caption=caption, parse_mode="HTML",
            reply_markup=Keyboard([[btn("✅ Já paguei · verificar", f"payment_refresh:{token}")]]))
