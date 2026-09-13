"""Independent product artwork, bound to the supplier service identity."""

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from banners import MAX_BODY
from pricing import identity


class ProductBannerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(strict=True, ge=0)
    fit: Literal["contain", "cover"] = "contain"
    position: Literal["center", "top", "bottom"] = "center"
    image: str = Field(default="", max_length=MAX_BODY)
    reset: bool = False


def metadata(store):
    return {
        row["service_id"]: dict(row)
        for row in store.db.execute(
            "SELECT service_id,identity,fit,position,revision,image IS NOT NULL AS custom FROM product_banners"
        )
    }


def artwork(service, rows):
    fingerprint = identity(service)
    row = rows.get(service.id)
    custom = bool(row and row["identity"] == fingerprint and row["custom"])
    revision = row["revision"] if row else 0
    return {
        "identity": fingerprint,
        "revision": revision,
        "custom": custom,
        "fit": row["fit"] if custom else "contain",
        "position": row["position"] if custom else "center",
        "url": f"/media/product-banners/{service.id}?v={revision}&key={fingerprint}"
        if custom
        else "",
    }


def save(store, actor, service, payload, data, mime):
    fingerprint = identity(service)
    if payload.identity != fingerprint:
        raise ValueError("Este produto mudou. Atualize o painel antes de salvar.")
    store.db.execute("BEGIN IMMEDIATE")
    try:
        row = store.db.execute(
            "SELECT * FROM product_banners WHERE service_id=?", (service.id,)
        ).fetchone()
        revision = row["revision"] if row else 0
        if revision != payload.revision:
            raise ValueError(
                "Este banner mudou em outra sessão. Atualize o painel antes de salvar."
            )
        if payload.reset:
            data, mime, fit, position = None, "", "contain", "center"
        else:
            fit, position = payload.fit, payload.position
            if data is None and row and row["identity"] == fingerprint:
                data, mime = row["image"], row["mime"]
            if data is None:
                raise ValueError("Escolha uma imagem para este produto.")
        store.db.execute(
            """INSERT INTO product_banners
            (service_id,identity,fit,position,image,mime,revision,admin_id,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(service_id) DO UPDATE SET
            identity=excluded.identity,fit=excluded.fit,position=excluded.position,
            image=excluded.image,mime=excluded.mime,revision=excluded.revision,
            admin_id=excluded.admin_id,updated_at=excluded.updated_at""",
            (
                service.id,
                fingerprint,
                fit,
                position,
                data,
                mime,
                revision + 1,
                actor,
                int(time.time()),
            ),
        )
        store.db.commit()
    except BaseException:
        store.db.rollback()
        raise
    return artwork(service, metadata(store))
