"""Persistent retail pricing. Supplier costs and already paid orders are never rewritten."""

import hashlib
import re
import time
from dataclasses import replace
from decimal import Decimal

from domain import check_quote, retail_price


def identity(service):
    return hashlib.sha256(
        f"{service.id}|{service.name}|{service.kind}|{service.platform}".encode()
    ).hexdigest()


def rate(panel, service):
    row = panel.store.db.execute(
        """SELECT p.multiplier,p.revision,o.identity,o.unit_price
        FROM pricing_policy p LEFT JOIN price_overrides o ON o.service_id=? WHERE p.id=1""",
        (service.id,),
    ).fetchone()
    custom = row["identity"] == identity(service)
    retail = (
        Decimal(row["unit_price"])
        * (1 if service.kind.casefold() == "package" else 1000)
        if custom
        else service.rate
        * Decimal(row["multiplier"] or str(panel.settings.price_multiplier))
    )
    return retail, row["revision"], custom


def total(service, payload, retail_rate):
    return retail_price(
        check_quote(replace(service, rate=retail_rate), payload), Decimal(1)
    )


def unit_label(value):
    raw = format(value, "f")
    whole, _, fraction = raw.partition(".")
    return (
        "R$ "
        + f"{int(whole):,}".replace(",", ".")
        + ","
        + fraction.rstrip("0").ljust(2, "0")
    )


def change(panel, actor, operation, value, reason, expected_revision, service=None):
    panel.require_admin(actor)
    if (
        operation not in {"unit", "reset", "multiplier"}
        or not 5 <= len(reason.strip()) <= 200
    ):
        raise ValueError("Operação ou motivo inválido.")
    if operation != "multiplier" and service is None:
        raise ValueError("Selecione um serviço.")
    parsed = None
    if operation != "reset":
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{1,5}([.,]\d{1,6})?", value
        ):
            raise ValueError("Informe um valor positivo com até 6 casas decimais.")
        parsed = Decimal(value.replace(",", "."))
        low, high = (
            (Decimal("0.1"), Decimal(100))
            if operation == "multiplier"
            else (Decimal("0.000001"), Decimal(5000))
        )
        if not low <= parsed <= high:
            raise ValueError(f"O valor deve ficar entre {low} e {high}.")
        if (
            service
            and service.kind.casefold() == "package"
            and parsed != parsed.quantize(Decimal("0.01"))
        ):
            raise ValueError("Preços de pacotes devem ter no máximo 2 casas decimais.")
    db = panel.store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        policy = db.execute("SELECT * FROM pricing_policy WHERE id=1").fetchone()
        if policy["revision"] != expected_revision:
            raise ValueError(
                "Outro preço foi alterado. Atualize a tabela e revise novamente."
            )
        if operation == "multiplier":
            old = policy["multiplier"] or str(panel.settings.price_multiplier)
            db.execute(
                "UPDATE pricing_policy SET multiplier=? WHERE id=1", (str(parsed),)
            )
        else:
            old_row = db.execute(
                "SELECT unit_price FROM price_overrides WHERE service_id=?",
                (service.id,),
            ).fetchone()
            old = old_row[0] if old_row else "automático"
            if operation == "reset":
                db.execute(
                    "DELETE FROM price_overrides WHERE service_id=?", (service.id,)
                )
            else:
                db.execute(
                    "INSERT INTO price_overrides VALUES(?,?,?) ON CONFLICT(service_id) DO UPDATE SET identity=excluded.identity,unit_price=excluded.unit_price",
                    (service.id, identity(service), str(parsed)),
                )
        db.execute("UPDATE pricing_policy SET revision=revision+1 WHERE id=1")
        db.execute(
            "INSERT INTO pricing_audit(admin_id,service_id,operation,old_value,new_value,reason,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                actor,
                service.id if service else None,
                operation,
                old,
                str(parsed) if parsed is not None else "automático",
                reason.strip(),
                int(time.time()),
            ),
        )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"revision": expected_revision + 1}
