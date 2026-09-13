"""Genuine, opt-in customer reviews backed by a completed, charged order."""

import time
from decimal import ROUND_HALF_UP, Decimal

ELIGIBLE = """o.dry_run=0 AND (o.state='COMPLETED' OR
    (o.state='SUBMITTED' AND lower(trim(o.provider_status))='completed'))
    AND EXISTS(SELECT 1 FROM wallet_ledger l WHERE l.reference='order:'||o.id
        AND l.user_id=o.user_id AND l.kind='ORDER' AND l.amount_cents<0)"""


def eligibility(store, token, uid):
    row = store.db.execute(
        f"SELECT o.id FROM orders o WHERE o.id=? AND o.user_id=? AND {ELIGIBLE}",
        (token, uid),
    ).fetchone()
    existing = store.db.execute(
        "SELECT rating,comment,display_name FROM reviews WHERE order_id=? AND user_id=?",
        (token, uid),
    ).fetchone()
    return {"canReview": bool(row) and not existing, "reviewed": bool(existing)}


def create(store, token, uid, name, rating, comment):
    # All decisions and insert share a lock across bot/webapp processes.
    store.db.execute("BEGIN IMMEDIATE")
    try:
        if not store.order(token, uid):
            raise ValueError("Pedido não encontrado.")
        existing = store.db.execute(
            "SELECT * FROM reviews WHERE order_id=? AND user_id=?", (token, uid)
        ).fetchone()
        if existing:
            if (existing["display_name"], existing["rating"], existing["comment"]) != (
                name,
                rating,
                comment,
            ):
                raise ValueError("Este pedido já foi avaliado.")
            store.db.commit()
            return {"ok": True}
        if not eligibility(store, token, uid)["canReview"]:
            raise ValueError(
                "Você pode avaliar depois que a entrega do seu pedido for concluída."
            )
        store.db.execute(
            "INSERT INTO reviews(order_id,user_id,display_name,rating,comment,created_at) VALUES(?,?,?,?,?,?)",
            (token, uid, name, rating, comment, int(time.time())),
        )
        store.db.commit()
        return {"ok": True}
    except BaseException:
        store.db.rollback()
        raise


def listing(store, page=0):
    # Never expose Telegram IDs, usernames, destinations or order IDs publicly.
    source = f"FROM reviews r JOIN orders o ON o.id=r.order_id AND o.user_id=r.user_id WHERE {ELIGIBLE}"
    aggregate = store.db.execute(
        f"SELECT count(*),coalesce(sum(r.rating),0) {source}"
    ).fetchone()
    count, total = aggregate
    average = (
        str((Decimal(total) / count).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        if count
        else None
    )
    rows = store.db.execute(
        f"SELECT r.display_name,r.rating,r.comment,r.created_at {source} ORDER BY r.created_at DESC,r.id DESC LIMIT 10 OFFSET ?",
        (page * 10,),
    )
    return {
        "count": count,
        "average": average,
        "hasMore": (page + 1) * 10 < count,
        "reviews": [
            {
                "name": r["display_name"],
                "rating": r["rating"],
                "comment": r["comment"],
                "createdAt": r["created_at"],
                "verified": True,
            }
            for r in rows
        ],
    }
