"""Persistent fulfillment: automatic dispatch and exclusive manual ownership."""

import json
import time

from domain import check_quote, decimal_value, normalize
from provider import ProviderError, UncertainWrite


def queue_later(store, token, reason, *, seconds=60, from_sending=False):
    with store.db:
        store.db.execute(
            """UPDATE orders SET state='QUEUED',queue_reason=?,retry_at=?,updated_at=?,
            queue_notice_sent=CASE WHEN queue_reason<>? THEN 0 ELSE queue_notice_sent END
            WHERE id=? AND state=?""",
            (
                reason,
                int(time.time()) + seconds,
                int(time.time()),
                reason,
                token,
                "SENDING" if from_sending else "QUEUED",
            ),
        )


async def dispatch(panel, token):
    row = panel.store.order(token)
    if not row or row["state"] != "QUEUED":
        return row
    try:
        service = await panel.service(row["service_id"], force=True)
        if service.kind != row["kind"] or check_quote(
            service, json.loads(row["payload"])
        ) != decimal_value(row["provider_cost"]):
            queue_later(
                panel.store,
                token,
                "O catálogo ou custo mudou; conferir manualmente.",
                seconds=3600,
            )
            return panel.store.order(token)
        balance = await panel.api.balance()
        if balance["currency"] != "BRL" or decimal_value(
            balance["balance"]
        ) < decimal_value(row["provider_cost"]):
            queue_later(panel.store, token, "Saldo operacional insuficiente.")
            return panel.store.order(token)
    except (ProviderError, ValueError):
        queue_later(panel.store, token, "Catálogo ou saldo operacional indisponível.")
        return panel.store.order(token)
    # Shared-database compare-and-set arbitrates bot worker versus admin API.
    with panel.store.db:
        claimed = panel.store.db.execute(
            "UPDATE orders SET state='SENDING',updated_at=? WHERE id=? AND state='QUEUED'",
            (int(time.time()), token),
        ).rowcount
    if not claimed:
        return panel.store.order(token)
    try:
        provider_id = await panel.api.add(json.loads(row["payload"]))
        panel.store.mark_order(token, "SUBMITTED", provider_id=provider_id)
    except UncertainWrite as exc:
        panel.store.mark_order(token, "UNKNOWN", error=str(exc))
    except ProviderError as exc:
        error = normalize(str(exc))
        if any(
            term in error
            for term in (
                "not enough funds",
                "insufficient balance",
                "insufficient funds",
                "saldo insuficiente",
            )
        ):
            queue_later(
                panel.store,
                token,
                "Saldo operacional insuficiente no envio.",
                from_sending=True,
            )
        else:
            panel.store.reject_order_and_refund(
                token, "Pedido não realizado; saldo devolvido", str(exc)
            )
    except BaseException:
        panel.store.mark_order(
            token,
            "UNKNOWN",
            error="Confirmação de envio pendente. Verificação necessária.",
        )
        raise
    return panel.store.order(token)


def manual_transition(panel, actor, token, operation, note):
    panel.require_admin(actor)
    if operation not in {"claim", "release", "complete", "refund"}:
        raise ValueError("Operação inválida.")
    if not 5 <= len(note.strip()) <= 300:
        raise ValueError("Registre uma observação de 5 a 300 caracteres.")
    db = panel.store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        row = panel.store.order(token)
        expected = {
            "claim": {"QUEUED"},
            "release": {"MANUAL"},
            "complete": {"MANUAL"},
            "refund": {"QUEUED", "MANUAL"},
        }[operation]
        if not row or row["state"] not in expected:
            raise ValueError(
                "O pedido mudou de estado. Atualize o painel antes de agir."
            )
        if row["state"] == "MANUAL" and row["manual_admin_id"] != actor:
            raise ValueError(
                "Este atendimento pertence a outro administrador. Somente ele pode concluir ou devolver à fila."
            )
        state = {
            "claim": "MANUAL",
            "release": "QUEUED",
            "complete": "COMPLETED",
            "refund": "REJECTED",
        }[operation]
        if operation == "refund":
            cents = int(decimal_value(row["cost"]) * 100)
            panel.store._adjust_wallet(
                row["user_id"],
                cents,
                "ORDER_REFUND",
                f"refund:{token}",
                "Pedido cancelado; saldo devolvido",
            )
        db.execute(
            """UPDATE orders SET state=?,manual_admin_id=?,retry_at=0,updated_at=?,
            provider_status=?,queue_notice_sent=0,error='' WHERE id=?""",
            (
                state,
                actor if state == "MANUAL" else 0,
                int(time.time()),
                "completed"
                if state == "COMPLETED"
                else "canceled"
                if state == "REJECTED"
                else "awaiting",
                token,
            ),
        )
        db.execute(
            "INSERT INTO fulfillment_audit(order_id,actor_id,event,note,created_at) VALUES(?,?,?,?,?)",
            (token, actor, operation, note.strip(), int(time.time())),
        )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return panel.store.order(token)
