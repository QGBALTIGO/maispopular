"""Fluxo guiado de compra."""
import json
import time

from telegram import Update
from telegram.ext import ContextTypes

from domain import build_payload, money_brl, validate_target
from ui_catalog import search_page
from ui_common import btn, e, home_rows, panel, say, uid


async def begin_order(update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int) -> None:
    p = panel(context)
    service = await p.service(service_id, force=True)
    p.store.abort_drafts(uid(update))
    context.user_data["flow"] = {"step": "target", "service_id": service_id,
                                 "expires": time.time() + 900}
    await say(update,
        f"🛒 <b>Novo pedido</b>\n\n{e(service.name)}\n\n"
        "🔗 Envie o link ou @usuário solicitado pelo serviço.\n"
        "Para curtidas e visualizações, normalmente é o link da publicação — não o perfil.\n\n"
        "🔐 Nunca envie senha ou código de acesso.",
        [[btn("🚫 Cancelar", "home")]])


async def quote_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flow = context.user_data["flow"]
    row = await panel(context).quote(uid(update), flow["service_id"], flow["target"],
                                     flow.get("value"), flow.get("answer"))
    payload = json.loads(row["payload"])
    quantity = payload.get("quantity")
    if "comments" in payload:
        quantity = len(payload["comments"].splitlines())
    balance = panel(context).store.balance_cents(uid(update)) / 100
    text = (
        f"🧾 <b>Confira seu pedido</b>\n\n"
        f"<b>{e(row['service_name'])}</b>\n"
        f"🏷️ Código: <code>{row['service_id']}</code>\n"
        f"🔗 Destino: <code>{e(payload['link'])}</code>\n"
        f"📦 Quantidade: <b>{quantity if quantity is not None else '1 pacote'}</b>\n"
        f"💵 Total: <b>{money_brl(row['cost'])}</b>\n"
        f"👛 Saldo atual: {money_brl(balance)}\n"
    )
    if "answer_number" in payload:
        text += f"🗳️ Alternativa: {payload['answer_number']}\n"
    if "comments" in payload:
        text += f"💬 Prévia:\n<pre>{e(payload['comments'][:300])}</pre>\n"
    text += "\nO valor e a disponibilidade serão conferidos novamente ao confirmar."
    context.user_data.pop("flow", None)
    rows = [[btn("✅ Confirmar e pagar", f"confirm:{row['id']}")],
            [btn("💳 Adicionar saldo", "deposit"), btn("🚫 Cancelar", "home")]]
    await say(update, text, rows)


async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flow = context.user_data.get("flow")
    if not flow or flow.get("expires", 0) < time.time():
        context.user_data.pop("flow", None)
        await say(update, "Use /start para abrir o menu.", home_rows(panel(context).is_admin(uid(update))))
        return
    value = update.effective_message.text.strip()
    if flow["step"] == "search":
        context.user_data["search"] = value[:100]
        context.user_data.pop("flow", None)
        await search_page(update, context)
        return
    if flow["step"].startswith("deposit_"):
        from ui_payments import deposit_input
        await deposit_input(update, context, value)
        return
    service = await panel(context).service(flow["service_id"])
    if flow["step"] == "target":
        flow["target"] = validate_target(value)
        if service.kind.casefold() == "package":
            await quote_page(update, context)
            return
        flow["step"] = "value"
        prompt = ("💬 Envie os comentários, um por linha, em uma única mensagem."
                  if service.kind.casefold() == "custom comments" else
                  "📦 Envie a quantidade inteira, sem pontos ou vírgulas. Exemplo: 1000.")
        await say(update, f"{prompt}\n\nMínimo: <b>{service.minimum}</b> · Máximo: <b>{service.maximum}</b>")
    elif flow["step"] == "value":
        flow["value"] = value
        if service.kind.casefold() == "poll":
            build_payload(service, flow["target"], value, "1")
            flow["step"] = "answer"
            await say(update, "🗳️ Envie o número da alternativa da enquete.")
        else:
            await quote_page(update, context)
    elif flow["step"] == "answer":
        flow["answer"] = value
        await quote_page(update, context)
