"""Histórico e acompanhamento dos pedidos do cliente."""
import json
import math
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from domain import STATUS_PT, money_brl
from provider import ProviderError
from ui_common import LOCAL_STATES, PAGE, btn, e, pager, panel, say, uid


def order_text(row: dict) -> str:
    payload = json.loads(row["payload"])
    status = json.loads(row["status_json"])
    text = (
        f"📦 <b>Pedido {row['id'][:8].upper()}</b>\n\n"
        f"<b>{e(row['service_name'])}</b>\n"
        f"📋 Situação: {e(LOCAL_STATES.get(row['state'], row['state']))}\n"
        f"🔗 Destino: <code>{e(payload['link'])}</code>\n"
        f"💵 Total pago: <b>{money_brl(row['cost'])}</b>\n"
    )
    if row["state"] == "SUBMITTED":
        text += f"📡 Andamento: {e(STATUS_PT.get(row['provider_status'].lower(), row['provider_status']))}\n"
    if "start_count" in status:
        text += f"🏁 Contagem inicial: {e(str(status['start_count'])[:100])}\n"
    if "remains" in status:
        text += f"📊 Quantidade restante: {e(str(status['remains'])[:100])}\n"
    date = datetime.fromtimestamp(row["created_at"], timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    text += f"🗓️ Criado em: {date}"
    if row["error"]:
        text += f"\n\n⚠️ {e(row['error'])}"
    if row["state"] == "UNKNOWN":
        text += "\n\nNossa equipe precisa conferir esta solicitação. Não faça o mesmo pedido novamente."
    return text


async def orders_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    store = panel(context).store
    rows_data, total = store.list_orders(uid(update), max(page, 0))
    pages = max(1, math.ceil(total / PAGE))
    if page >= pages:
        page = pages - 1
        rows_data, total = store.list_orders(uid(update), page)
    rows = [[btn(f"{r['id'][:8].upper()} · {r['service_name'][:38]}", f"order:{r['id']}")]
            for r in rows_data]
    if total:
        rows.append(pager("orders", page, total))
    rows.append([btn("📋 Novo pedido", "catalog:0"), btn("🏠 Início", "home")])
    await say(update, "📦 <b>Meus pedidos</b>\n\n" +
              (f"{total} pedido(s). Escolha um para acompanhar." if total else
               "Você ainda não fez nenhum pedido."), rows)


async def order_page(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str,
                     *, refresh: bool = False) -> None:
    p = panel(context)
    row = p.store.order(token, uid(update))
    if not row:
        raise ValueError("Pedido não encontrado.")
    warning = ""
    if refresh and row["state"] == "SUBMITTED" and row["provider_id"]:
        try:
            result = await p.api.status(row["provider_id"])
            p.store.update_status(token, result)
            row = p.store.order(token, uid(update))
        except ProviderError:
            warning = "\n\n⚠️ A atualização está temporariamente indisponível."
    rows = []
    if row["state"] == "SUBMITTED":
        rows.append([btn("🔄 Atualizar andamento", f"update:{token}")])
        rows.append([btn("♻️ Pedir reposição", f"action:refill:{token}"),
                     btn("🚫 Pedir cancelamento", f"action:cancel:{token}")])
    for action in p.store.actions_for(token, uid(update)):
        data = json.loads(action["result_json"])
        if data.get("refill"):
            rows.append([btn("♻️ Consultar reposição", f"refill_status:{action['id']}")])
    rows.append([btn("📦 Meus pedidos", "orders:0"), btn("🏠 Início", "home")])
    await say(update, order_text(row) + warning, rows)


async def action_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str, kind: str) -> None:
    p = panel(context)
    action = await p.prepare_action(token, uid(update), kind)
    name = "reposição" if kind == "refill" else "cancelamento"
    await say(update,
        f"⚠️ <b>Solicitar {name}</b>\n\n"
        "A solicitação será analisada conforme as condições do serviço. Ela não garante conclusão ou reembolso.",
        [[btn("✅ Confirmar solicitação", f"action_confirm:{action['id']}")],
         [btn("↩️ Voltar", f"order:{token}")]])


async def action_result(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str) -> None:
    result = await panel(context).submit_action(token, uid(update))
    if result["state"] == "SUBMITTED":
        message = "✅ Solicitação registrada. Acompanhe o pedido para novas atualizações."
    elif result["state"] == "UNKNOWN":
        message = "⚠️ A confirmação está pendente. Nossa equipe fará a verificação."
    else:
        message = f"❌ Não foi possível registrar: {e(result['error'])}"
    await say(update, f"📨 <b>Solicitação</b>\n\n{message}",
              [[btn("📦 Ver pedido", f"order:{result['order_id']}")]])
