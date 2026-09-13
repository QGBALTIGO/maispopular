"""Telegram entry points. All shopping operations live in the Mini App."""
from ui_catalog import home
from ui_common import panel, say, uid, web_btn


async def open_view(update, context, view="platforms"):
    context.user_data.pop("flow", None)
    p = panel(context)
    if view == "admin":
        p.require_admin(uid(update))
    url = p.settings.webapp_url()
    if not url:
        raise ValueError("A loja está reconectando. Tente novamente em alguns instantes.")
    labels = {"wallet": "💳 Abrir carteira", "deposit": "💠 Adicionar saldo", "orders": "📦 Meus pedidos",
              "help": "💬 Ajuda e suporte", "admin": "⚙️ Abrir administração", "platforms": "🛒 Abrir catálogo"}
    await say(update, "<b>Mais Popular</b>\n\nContinue pelo Web App. Tudo é feito dentro da sua loja.",
              [[web_btn(labels.get(view, "🛒 Abrir loja"), f"{url}?view={view}")]])


async def start(update, context):
    start_arg = context.args[0] if context.args else ""
    if start_arg in {"deposit", "help", "admin", "wallet", "orders"}:
        return await open_view(update, context, start_arg)
    if start_arg.startswith("order_"):
        return await open_view(update, context, "orders")
    await home(update, context)


async def command(update, context):
    name = update.effective_message.text.split()[0].split("@")[0].lower()
    view = {"/saldo": "wallet", "/recarga": "deposit", "/pedidos": "orders", "/pedido": "orders",
            "/ajuda": "help", "/admin": "admin", "/resolver": "admin"}.get(name, "platforms")
    await open_view(update, context, view)


async def callback(update, context):
    await update.callback_query.answer()
    action = (update.callback_query.data or "").split(":")[0]
    if action == "home":
        return await home(update, context)
    if action == "noop":
        return
    if action in {"deposit", "deposit_amount", "payment_refresh", "payment_retry", "balance"}:
        view = "wallet"
    elif action in {"orders", "order", "update", "action", "action_confirm", "refill_status", "confirm"}:
        view = "orders"
    else:
        view = {"help": "help", "admin": "admin"}.get(action, "platforms")
    await open_view(update, context, view)


async def grant_credit(update, context):
    p = panel(context)
    p.require_admin(uid(update))
    if len(context.args) < 3 or not context.args[0].isdigit():
        raise ValueError("Use /darsaldo ID VALOR MOTIVO. Exemplo: /darsaldo 123456789 25,00 Bonificação")
    result = p.grant_credit(uid(update), int(context.args[0]), context.args[1], " ".join(context.args[2:]),
                            f"telegram-{update.update_id}")
    from domain import money_brl
    await say(update, f"✅ <b>Crédito registrado</b>\n\nUsuário: <code>{result['userId']}</code>\n"
              f"Valor: <b>{money_brl(result['amountCents'] / 100)}</b>\n"
              f"Saldo atual: <b>{money_brl(result['balanceCents'] / 100)}</b>\n\n"
              "O lançamento está no extrato e na auditoria administrativa.")
