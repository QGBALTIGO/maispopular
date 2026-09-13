"""Administrator-managed artwork for one catalog card per social platform."""

import hashlib
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from banners import MAX_BODY


def identity(platform: str) -> str:
    return hashlib.sha256(f"catalog-platform|{platform}".encode()).hexdigest()


class PlatformBannerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    platform: str = Field(min_length=2, max_length=80)
    identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(strict=True, ge=0)
    fit: Literal["contain", "cover"] = "contain"
    position: Literal["center", "top", "bottom"] = "center"
    image: str = Field(default="", max_length=MAX_BODY)
    reset: bool = False


def metadata(store):
    return {
        row["platform"]: dict(row)
        for row in store.db.execute(
            "SELECT platform,identity,fit,position,revision,image IS NOT NULL AS custom FROM platform_banners"
        )
    }


def artwork(platform: str, rows):
    fingerprint = identity(platform)
    row = rows.get(platform)
    custom = bool(row and row["identity"] == fingerprint and row["custom"])
    revision = row["revision"] if row else 0
    return {
        "identity": fingerprint,
        "revision": revision,
        "custom": custom,
        # Catalog artwork always fills the 16:9 card. This keeps mixed source
        # dimensions from producing letterboxing in the social grid.
        "fit": "cover" if custom else "contain",
        "position": row["position"] if custom else "center",
        "url": f"/media/platform-banners/{fingerprint}?v={revision}" if custom else "",
    }


def save(store, actor, platform, payload, data, mime):
    fingerprint = identity(platform)
    if payload.platform != platform or payload.identity != fingerprint:
        raise ValueError("Esta rede mudou. Atualize o painel antes de salvar.")
    store.db.execute("BEGIN IMMEDIATE")
    try:
        row = store.db.execute(
            "SELECT * FROM platform_banners WHERE platform=?", (platform,)
        ).fetchone()
        revision = row["revision"] if row else 0
        if revision != payload.revision:
            raise ValueError(
                "Este banner mudou em outra sessão. Atualize o painel antes de salvar."
            )
        if payload.reset:
            data, mime, fit, position = None, "", "contain", "center"
        else:
            fit, position = "cover", payload.position
            if data is None and row and row["identity"] == fingerprint:
                data, mime = row["image"], row["mime"]
            if data is None:
                raise ValueError("Escolha uma imagem para esta rede social.")
        store.db.execute(
            """INSERT INTO platform_banners
            (platform,identity,fit,position,image,mime,revision,admin_id,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(platform) DO UPDATE SET
            identity=excluded.identity,fit=excluded.fit,position=excluded.position,
            image=excluded.image,mime=excluded.mime,revision=excluded.revision,
            admin_id=excluded.admin_id,updated_at=excluded.updated_at""",
            (
                platform,
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
    return artwork(platform, metadata(store))
