"""Mais Popular: loja pública de serviços digitais no Telegram."""
import asyncio
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from telegram import (
    BotCommand,
    LinkPreviewOptions,
    MenuButtonWebApp,
    Update,
    WebAppInfo,
)
from telegram import InlineKeyboardMarkup as Keyboard
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

import ui_entry
from config import Settings
from domain import decimal_value, money_brl
from engine import Panel
from payments import Cakto, PaymentError
from provider import ProviderError, ServiceProvider
from storage import Store
from ui_catalog import (
    balance_page,
    catalog_page,
    family_page,
    help_page,
    home,
    identity,
    platform_page,
    search_page,
    search_prompt,
    service_description_page,
    service_page,
)
from ui_checkout import begin_order
from ui_common import LOG, SecretFilter, btn, e, guard, panel, say, uid, web_btn
from ui_orders import action_preview, action_result, order_page, order_text, orders_page
from ui_payments import choose_deposit, deposit_menu, payment_page
from broadcasts import poll_broadcasts


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args and context.args[0].casefold() == "deposit":
        await deposit_menu(update, context)
        return
    if context.args and context.args[0].casefold() == "help":
        await help_page(update, context)
        return
    if context.args and context.args[0].startswith("order_"):
        token = context.args[0][6:]
        if len(token) == 16 and all(c in "0123456789abcdef" for c in token):
            await order_page(update, context, token)
            return
    await home(update, context)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    raw = update.callback_query.data or ""
    parts = raw.split(":")
    action = parts[0]
    if action == "noop":
        return
    if action == "home":
        await home(update, context)
    elif action == "identity":
        await identity(update, context)
    elif action == "help":
        await help_page(update, context)
    elif action == "balance":
        await balance_page(update, context)
    elif action == "catalog":
        await catalog_page(update, context, int(parts[1]))
    elif action == "platform":
        await platform_page(update, context, parts[1], int(parts[2]))
    elif action == "family":
        await family_page(update, context, parts[1], parts[2], int(parts[3]))
    elif action == "search_prompt":
        await search_prompt(update, context)
    elif action == "search":
        await search_page(update, context, int(parts[1]))
    elif action == "service":
        await service_page(update, context, int(parts[1]))
    elif action == "buy":
        await begin_order(update, context, int(parts[1]))
    elif action == "description":
        await service_description_page(update, context, int(parts[1]), int(parts[2]))
    elif action == "confirm":
        row = await panel(context).submit(parts[1], uid(update))
        await order_page(update, context, row["id"])
        if row["state"] == "UNKNOWN":
            await notify_admins(context, f"⚠️ Pedido incerto <code>{row['id']}</code>. Verifique antes de resolver.")
    elif action == "orders":
        await orders_page(update, context, int(parts[1]))
    elif action in {"order", "update"}:
        await order_page(update, context, parts[1], refresh=action == "update")
    elif action == "action":
        await action_preview(update, context, parts[2], parts[1])
    elif action == "action_confirm":
        await action_result(update, context, parts[1])
    elif action == "refill_status":
        item = panel(context).store.action(parts[1], uid(update))
        if not item:
            raise ValueError("Reposição não encontrada.")
        refill = json.loads(item["result_json"]).get("refill")
        if not refill:
            raise ValueError("Esta solicitação ainda não tem atualização.")
        result = await panel(context).api.refill_status(refill)
        await say(update, f"♻️ <b>Reposição</b>\n\nStatus: {e(result['status'])}",
                  [[btn("🔄 Atualizar", raw), btn("📦 Pedido", f"order:{item['order_id']}")]])
    elif action == "deposit":
        await deposit_menu(update, context)
    elif action == "deposit_amount":
        await choose_deposit(update, context, int(parts[1]))
    elif action == "payment_refresh":
        await payment_page(update, context, parts[1], refresh=True)
    elif action == "payment_retry":
        await payment_page(update, context, parts[1], retry=True, send_qr=True)
    elif action == "admin":
        await admin_page(update, context)
    else:
        raise ValueError("Botão expirado. Use /start.")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await search_prompt(update, context)
    else:
        context.user_data.pop("flow", None)
        context.user_data["search"] = " ".join(context.args)[:100]
        await search_page(update, context)


async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        raise ValueError("Use /pedido CODIGO. O código aparece em Meus pedidos.")
    token = context.args[0].lower()
    row = panel(context).store.order(token, uid(update))
    if not row:
        raise ValueError("Pedido não encontrado para seu usuário.")
    await order_page(update, context, token, refresh=True)


async def admin_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    p.require_admin(uid(update))
    stats = p.store.admin_stats()
    try:
        operational = await p.api.balance()
        operational_text = money_brl(operational["balance"])
    except ProviderError:
        operational_text = "consulta indisponível"
    await say(update,
        "⚙️ <b>Administração</b>\n\n"
        f"👥 Usuários: <b>{stats['users']}</b>\n"
        f"📦 Pedidos: <b>{stats['orders']}</b>\n"
        f"⚠️ Pedidos a verificar: <b>{stats['unknown_orders']}</b>\n"
        f"⏳ Recargas abertas: <b>{stats['pending_payments']}</b>\n"
        f"💳 Recargas aprovadas: <b>{money_brl(stats['paid_cents'] / 100)}</b>\n"
        f"💳 Saldo total de clientes: <b>{money_brl(stats['wallet_cents'] / 100)}</b>\n"
        f"🏭 Capacidade operacional: <b>{e(operational_text)}</b>",
        [[btn("🔄 Atualizar", "admin"), btn("🏠 Início", "home")]])


async def resolve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    p.require_admin(uid(update))
    if len(context.args) != 3 or context.args[2] != "CONFIRMO":
        raise ValueError("Use /resolver ID_LOCAL ID_EXTERNO CONFIRMO ou /resolver ID_LOCAL naocriado CONFIRMO.")
    token, decision, _ = context.args
    async with p.mutation_lock:
        row = p.store.order(token)
        if not row or row["state"] != "UNKNOWN":
            raise ValueError("Pedido incerto não encontrado.")
        if decision == "naocriado":
            p.store.reject_order_and_refund(
                token, "Pedido não criado; saldo devolvido",
                "Verificação concluída: pedido não criado.")
        elif decision.isdigit() and int(decision) > 0:
            status = await p.api.status(decision)
            p.store.mark_order(token, "SUBMITTED", provider_id=decision)
            p.store.update_status(token, status)
        else:
            raise ValueError("Informe um ID externo positivo ou naocriado.")
    await update.effective_message.reply_text("✅ Pedido reconciliado e carteira ajustada quando necessário.")


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    for admin_id in panel(context).settings.admin_ids:
        try:
            await context.bot.send_message(admin_id, text, parse_mode="HTML")
        except TelegramError:
            LOG.warning("Não foi possível notificar um administrador.")


async def poll_orders(context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    watched = p.store.watched(100)
    if not watched:
        return
    try:
        statuses = await p.api.multi_status([r["provider_id"] for r in watched])
    except ProviderError:
        LOG.warning("Consulta periódica de pedidos indisponível.")
        return
    for row in watched:
        p.store.touched(row["id"])
        data = statuses.get(row["provider_id"])
        if not isinstance(data, dict) or data.get("error") or not isinstance(data.get("status"), str):
            continue
        p.store.update_status(row["id"], data)
        row = p.store.order(row["id"])
        if row["provider_status"] == row["notified_status"]:
            continue
        try:
            await context.bot.send_message(row["user_id"], "🔔 <b>Atualização do pedido</b>\n\n" + order_text(row),
                parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True),
                reply_markup=Keyboard([[web_btn("📦 Meus pedidos", p.settings.webapp_url() + "?view=orders")]]) if p.settings.webapp_url() else None)
        except TelegramError:
            LOG.warning("Atualização de pedido não entregue.")
        else:
            p.store.notified(row["id"], row["provider_status"])
        await asyncio.sleep(0.05)


async def poll_payments(context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    for row in p.store.pending_payments(100):
        try:
            updated, balance_changed = await p.reconcile_payment(row["id"])
        except (PaymentError, ValueError):
            LOG.warning("Consulta periódica de uma recarga indisponível.")
            continue
        if updated["provider_status"] == updated["notified_status"] and not balance_changed:
            continue
        if updated["status"] in {"PAID", "REVERSED", "FAILED"}:
            status = {"PAID": "✅ Pix aprovado e saldo creditado!",
                      "REVERSED": "↩️ O pagamento foi estornado e a carteira foi ajustada.",
                      "FAILED": "❌ A recarga não foi concluída."}[updated["status"]]
            try:
                await context.bot.send_message(updated["user_id"],
                    f"{status}\n\nConsulte sua carteira no Web App.",
                    parse_mode="HTML", reply_markup=Keyboard([[web_btn("💳 Abrir carteira", p.settings.webapp_url() + "?view=wallet")]]) if p.settings.webapp_url() else None)
            except TelegramError:
                LOG.warning("Atualização de pagamento não entregue.")
            else:
                p.store.payment_notified(updated["id"], updated["provider_status"])
        else:
            p.store.payment_notified(updated["id"], updated["provider_status"])
        await asyncio.sleep(0.05)


async def poll_fulfillment(context: ContextTypes.DEFAULT_TYPE) -> None:
    from fulfillment import dispatch
    p = panel(context)
    rows = p.store.db.execute("SELECT id FROM orders WHERE state='QUEUED' AND retry_at<=? ORDER BY created_at LIMIT 20",
                              (int(time.time()),)).fetchall()
    for row in rows:
        try:
            await dispatch(p,row["id"])
        except (ProviderError,ValueError):
            LOG.warning("Não foi possível processar um pedido da fila.")
    notices = p.store.db.execute("SELECT * FROM orders WHERE state IN ('QUEUED','UNKNOWN') AND queue_notice_sent=0 LIMIT 30").fetchall()
    for row in notices:
        delivered = True
        for admin_id in p.settings.admin_ids:
            try:
                await context.bot.send_message(admin_id,
                    "📋 <b>Pedido aguardando atendimento</b>\n\n"
                    f"Código: <code>{row['id']}</code>\nCliente: <code>{row['user_id']}</code>\n"
                    f"Serviço: {e(row['service_name'])}\nMotivo interno: {e(row['queue_reason'] or row['error'] or 'Verificação necessária')}\n\n"
                    + ("Verifique se o fornecedor recebeu o pedido antes de qualquer novo envio." if row["state"] == "UNKNOWN"
                       else "Abra o painel para assumir a entrega manual. Assumir bloqueia o envio automático."),parse_mode="HTML",
                    reply_markup=Keyboard([[web_btn("⚙️ Administração",p.settings.webapp_url()+"?view=admin")]]) if p.settings.webapp_url() else None)
            except TelegramError:
                delivered = False
        if delivered and p.settings.admin_ids:
            with p.store.db:
                p.store.db.execute("UPDATE orders SET queue_notice_sent=1 WHERE id=?",(row["id"],))
    finished = p.store.db.execute("SELECT * FROM orders WHERE state IN ('COMPLETED','REJECTED') AND provider_status<>notified_status LIMIT 30").fetchall()
    for row in finished:
        try:
            await context.bot.send_message(row["user_id"],
                f"📦 Pedido {row['id'][:8].upper()}: " + ("concluído." if row["state"]=="COMPLETED" else "cancelado, com saldo devolvido à carteira."),
                reply_markup=Keyboard([[web_btn("📦 Meus pedidos",p.settings.webapp_url()+"?view=orders")]]) if p.settings.webapp_url() else None)
            p.store.notified(row["id"],row["provider_status"])
        except TelegramError:
            LOG.warning("Não foi possível notificar a conclusão do pedido.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    LOG.warning("Falha tratada (%s).", type(error).__name__)
    if not isinstance(update, Update) or not update.effective_message:
        return
    visible = str(error) if isinstance(error, (ProviderError, PaymentError, ValueError, PermissionError)) else \
              "Não consegui concluir esta etapa. Tente novamente em alguns instantes."
    settings = panel(context).settings
    for secret in (settings.api_key, settings.bot_token, settings.cakto_client_id,
                   settings.cakto_client_secret, settings.fingerprint_secret):
        visible = visible.replace(secret, "[segredo ocultado]")
    try:
        await update.effective_message.reply_text(f"⚠️ {visible[:800]}")
    except TelegramError:
        LOG.warning("Não foi possível exibir a mensagem de erro.")


async def post_init(app: Application) -> None:
    p = app.bot_data["panel"]
    await asyncio.gather(*(p.payments.validate_offer(offer_id, amount)
                           for amount, offer_id in p.settings.cakto_offers.items()))
    await app.bot.set_my_commands([
        BotCommand("start", "Abrir a loja"), BotCommand("pedidos", "Meus pedidos"),
        BotCommand("afiliados", "Indique e ganhe"), BotCommand("ajuda", "Suporte"),
    ])
    await sync_webapp_button(app)
    try:
        operational = await p.api.balance()
        if (operational["currency"] == "BRL"
                and decimal_value(operational["balance"]) < p.settings.min_deposit_brl):
            warning = ("⚠️ <b>Capacidade operacional baixa</b>\n\n"
                       f"Disponível para executar pedidos: <b>{money_brl(operational['balance'])}</b>. "
                       "Reforce o saldo operacional para evitar indisponibilidade aos clientes.")
            for admin_id in p.settings.admin_ids:
                await app.bot.send_message(admin_id, warning, parse_mode="HTML")
    except (ProviderError, TelegramError):
        LOG.warning("Não foi possível verificar ou avisar a capacidade operacional na inicialização.")


async def post_shutdown(app: Application) -> None:
    p = app.bot_data["panel"]
    await p.api.close()
    await p.payments.close()


async def sync_webapp_button(app: Application) -> None:
    url = app.bot_data["panel"].settings.webapp_url()
    if not url or app.bot_data.get("webapp_menu_url") == url:
        return
    try:
        await app.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Abrir loja", web_app=WebAppInfo(url=url)))
    except TelegramError:
        LOG.warning("Não foi possível sincronizar o botão do Mini App.")
    else:
        app.bot_data["webapp_menu_url"] = url
        LOG.info("Botão do Mini App sincronizado.")


async def poll_webapp_button(context: ContextTypes.DEFAULT_TYPE) -> None:
    await sync_webapp_button(context.application)


def build_app(p: Panel) -> Application:
    app = (Application.builder().token(p.settings.bot_token).concurrent_updates(False)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    app.bot_data["panel"] = p
    app.add_handler(TypeHandler(Update, guard), group=-1)
    for command, handler in [
        ("start", ui_entry.start), ("catalogo", ui_entry.command), ("buscar", ui_entry.command),
        ("saldo", ui_entry.command), ("recarga", ui_entry.command), ("pedidos", ui_entry.command),
        ("pedido", ui_entry.command), ("cancelar", home), ("meuid", identity),
        ("ajuda", ui_entry.command), ("admin", ui_entry.command), ("resolver", ui_entry.command),
        ("afiliados", ui_entry.command), ("darsaldo", ui_entry.grant_credit),
    ]:
        app.add_handler(CommandHandler(command, handler))
    app.add_handler(CallbackQueryHandler(ui_entry.callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, home))
    app.add_error_handler(error_handler)
    if app.job_queue is None:
        raise RuntimeError("Dependência de agendamento ausente.")
    app.job_queue.run_repeating(poll_orders, interval=p.settings.poll_seconds, first=15,
                                job_kwargs={"max_instances": 1, "coalesce": True})
    app.job_queue.run_repeating(poll_payments, interval=p.settings.poll_seconds, first=10,
                                job_kwargs={"max_instances": 1, "coalesce": True})
    app.job_queue.run_repeating(poll_webapp_button, interval=15, first=5,
                                job_kwargs={"max_instances": 1, "coalesce": True})
    app.job_queue.run_repeating(poll_fulfillment, interval=30, first=12,
                                job_kwargs={"max_instances": 1, "coalesce": True})
    app.job_queue.run_repeating(poll_broadcasts, interval=2, first=3,
                                job_kwargs={"max_instances": 1, "coalesce": True})
    return app


@contextmanager
def instance_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as file:
        try:
            if os.name == "nt":
                import msvcrt
                file.seek(0); file.write(b"0"); file.flush(); file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Já existe uma instância usando este banco.") from None
        yield


def main() -> None:
    os.umask(0o077)
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    for name in ("httpx", "httpcore", "telegram", "apscheduler"):
        logging.getLogger(name).setLevel(logging.WARNING)
    settings = Settings.load()
    secrets = (settings.bot_token, settings.api_key, settings.cakto_client_id,
               settings.cakto_client_secret, settings.fingerprint_secret)
    for handler in logging.getLogger().handlers:
        handler.addFilter(SecretFilter(secrets))
    LOG.info("Inicializando loja em produção.")
    with instance_lock(settings.db_path.with_suffix(".lock")):
        store = Store(settings.db_path)
        try:
            store.recover()
            p = Panel(settings, ServiceProvider(settings.api_key),
                      Cakto(settings.cakto_client_id, settings.cakto_client_secret), store)
            build_app(p).run_polling(allowed_updates=["message", "callback_query"],
                                     drop_pending_updates=False, bootstrap_retries=3)
        finally:
            store.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, PaymentError) as exc:
        print(f"Erro de configuração: {exc}", file=sys.stderr)
        sys.exit(1)
    except TelegramError as exc:
        print(f"Falha ao iniciar o Telegram ({type(exc).__name__}).", file=sys.stderr)
        sys.exit(1)
