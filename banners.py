"""Administrator-managed, bounded local raster banners. No remote URL fetching."""

import base64
import binascii
import time
from io import BytesIO
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

MAX_IMAGE = 4 * 1024 * 1024
MAX_BODY = 6 * 1024 * 1024
MAX_RENDER_DIMENSION = 1600
TARGETS = {
    "social": "#socialSection",
    "streaming": "#streamingSection",
    "tools": "#toolsSection",
    "support": "https://t.me/suportemaispopular",
    "wallet": "wallet",
}
DEFAULTS = (
    ("Impulsione suas redes sociais", "social", "social-blue-v2.png"),
    ("Streaming e aplicativos", "streaming", "streaming-blue-v2.png"),
    ("Conte com nosso atendimento", "support", "support.png"),
)


class BannerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=100)
    target: Literal["social", "streaming", "tools", "support", "wallet"]
    fit: Literal["contain", "cover"] = "contain"
    position: Literal["center", "top", "bottom"] = "center"
    revision: int = Field(strict=True, ge=0)
    image: str = Field(default="", max_length=MAX_BODY)
    reset: bool = False


def listing(store):
    items = []
    for slot, (title, target, file) in enumerate(DEFAULTS, 1):
        row = store.db.execute(
            "SELECT slot,title,target,fit,position,revision,image IS NOT NULL AS custom FROM shop_banners WHERE slot=?",
            (slot,),
        ).fetchone()
        item = (
            dict(row)
            if row
            else {
                "slot": slot,
                "title": title,
                "target": target,
                "fit": "contain",
                "position": "center",
                "revision": 0,
                "custom": False,
            }
        )
        item["custom"] = bool(item["custom"])
        item["url"] = (
            f"/media/banners/{slot}?v={item['revision']}"
            if item["custom"]
            else f"/assets/banners/{file}"
        )
        item["destination"] = TARGETS[item["target"]]
        items.append(item)
    return items


def optimize_raster(data: bytes) -> tuple[bytes, str]:
    if len(data) > MAX_IMAGE:
        raise ValueError("Use uma imagem de até 4 MB.")
    try:
        with Image.open(BytesIO(data)) as image:
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(
                image.format
            )
            if not mime or getattr(image, "is_animated", False):
                raise ValueError("Use PNG, JPG ou WebP sem animação.")
            w, h = image.size
            if min(w, h) < 64 or max(w, h) > 6000 or w * h > 16_000_000:
                raise ValueError(
                    "Use uma imagem de 64 a 6000 pixels, com até 16 megapixels."
                )
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            image.thumbnail(
                (MAX_RENDER_DIMENSION, MAX_RENDER_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output = BytesIO()
            image.save(output, format="WEBP", quality=84, method=6)
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ValueError(
            "A imagem está corrompida ou excede o tamanho permitido."
        ) from None
    return output.getvalue(), "image/webp"


def validate_image(encoded):
    if not encoded:
        return None, ""
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Arquivo de imagem inválido.") from None
    return optimize_raster(data)


def optimize_stored_images(store) -> dict:
    """Cria rendições leves dos banners existentes; execute após backup do SQLite."""
    changed = before = after = 0
    store.db.execute("BEGIN IMMEDIATE")
    try:
        for table, key in (
            ("shop_banners", "slot"),
            ("product_banners", "service_id"),
            ("platform_banners", "platform"),
        ):
            rows = store.db.execute(
                f"SELECT {key},image,mime FROM {table} WHERE image IS NOT NULL"
            ).fetchall()
            for row in rows:
                source = bytes(row["image"])
                before += len(source)
                try:
                    with Image.open(BytesIO(source)) as current:
                        oversized = max(current.size) > MAX_RENDER_DIMENSION
                except (UnidentifiedImageError, OSError):
                    oversized = True
                if row["mime"] == "image/webp" and not oversized and len(source) <= 700_000:
                    rendered = source
                else:
                    rendered, _ = optimize_raster(source)
                    store.db.execute(
                        f"UPDATE {table} SET image=?,mime='image/webp',revision=revision+1 WHERE {key}=?",
                        (rendered, row[key]),
                    )
                    changed += 1
                after += len(rendered)
        store.db.commit()
    except BaseException:
        store.db.rollback()
        raise
    return {"changed": changed, "before": before, "after": after}


def save(store, actor, slot, payload, data, mime):
    if slot not in (1, 2, 3):
        raise ValueError("Banner não encontrado.")
    store.db.execute("BEGIN IMMEDIATE")
    try:
        row = store.db.execute(
            "SELECT * FROM shop_banners WHERE slot=?", (slot,)
        ).fetchone()
        revision = row["revision"] if row else 0
        if revision != payload.revision:
            raise ValueError(
                "Este banner mudou em outra sessão. Atualize o painel antes de salvar."
            )
        if payload.reset:
            title, target, _ = DEFAULTS[slot - 1]
            fit = "contain"
            position = "center"
            data = None
            mime = ""
        else:
            title, target, fit, position = (
                payload.title,
                payload.target,
                payload.fit,
                payload.position,
            )
            if data is None and row:
                data, mime = row["image"], row["mime"]
        store.db.execute(
            """INSERT INTO shop_banners(slot,title,target,fit,position,image,mime,revision,admin_id,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(slot) DO UPDATE SET title=excluded.title,target=excluded.target,
            fit=excluded.fit,position=excluded.position,image=excluded.image,mime=excluded.mime,revision=excluded.revision,
            admin_id=excluded.admin_id,updated_at=excluded.updated_at""",
            (
                slot,
                title,
                target,
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
    return listing(store)[slot - 1]
