"""Configuração de produção carregada exclusivamente por variáveis de ambiente."""
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROVIDER_API_URL = "https://soupopular.net/api/v2"
CAKTO_API_URL = "https://api.cakto.com.br/public_api"


def boolean(value: str) -> bool:
    value = value.strip().lower()
    if value in {"true", "1", "yes", "sim"}:
        return True
    if value in {"false", "0", "no", "nao", "não"}:
        return False
    raise ValueError("Use true ou false nas opções booleanas.")


def ids(value: str) -> frozenset[int]:
    values = frozenset(int(x.strip()) for x in value.split(",") if x.strip())
    if any(x <= 0 for x in values):
        raise ValueError("Os IDs devem ser inteiros positivos.")
    return values


def decimal_env(name: str, default: str, *, minimum: str = "0.01") -> Decimal:
    try:
        value = Decimal(os.getenv(name, default))
        if not value.is_finite() or value < Decimal(minimum):
            raise ValueError
        return value
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} deve ser um valor válido, com ponto decimal.") from None


@dataclass(frozen=True)
class Settings:
    bot_token: str
    api_key: str
    admin_ids: frozenset[int]
    allowed_services: frozenset[int]
    db_path: Path
    max_order_cost: Decimal
    poll_seconds: int
    bot_name: str
    price_multiplier: Decimal
    min_deposit_brl: Decimal
    max_deposit_brl: Decimal
    cakto_client_id: str
    cakto_client_secret: str
    cakto_offers: dict[int, str]
    cakto_pix_expires: int
    fingerprint_secret: str
    webapp_url_file: Path = Path("data/webapp_url.txt")
    bot_username: str = "MaisPopularBot"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(override=False)
        token = os.getenv("BOT_TOKEN", "").strip()
        key = os.getenv("PROVIDER_API_KEY", "").strip()
        client_id = os.getenv("CAKTO_CLIENT_ID", "").strip()
        client_secret = os.getenv("CAKTO_CLIENT_SECRET", "").strip()
        offers_raw = os.getenv("CAKTO_OFFERS_JSON", "").strip()
        fingerprint_secret = os.getenv("PAYMENT_FINGERPRINT_SECRET", "").strip()
        missing = [name for name, value in (
            ("BOT_TOKEN", token), ("PROVIDER_API_KEY", key),
            ("CAKTO_CLIENT_ID", client_id), ("CAKTO_CLIENT_SECRET", client_secret),
            ("CAKTO_OFFERS_JSON", offers_raw), ("PAYMENT_FINGERPRINT_SECRET", fingerprint_secret),
        ) if not value or value.startswith("COLE_")]
        if missing:
            raise ValueError("Configure no .env: " + ", ".join(missing))

        multiplier = decimal_env("PRICE_MULTIPLIER", "2")
        if multiplier != Decimal(2):
            raise ValueError("PRICE_MULTIPLIER deve permanecer em 2 para cumprir a regra comercial.")
        min_deposit = decimal_env("MIN_DEPOSIT_BRL", "20")
        max_deposit = decimal_env("MAX_DEPOSIT_BRL", "5000")
        if min_deposit != min_deposit.to_integral_value() or max_deposit != max_deposit.to_integral_value():
            raise ValueError("As recargas devem usar valores inteiros em reais.")
        if max_deposit < min_deposit:
            raise ValueError("MAX_DEPOSIT_BRL deve ser maior ou igual ao mínimo.")
        try:
            raw_map = json.loads(offers_raw)
            offers = {int(amount): str(offer).strip() for amount, offer in raw_map.items()}
        except (ValueError, TypeError, AttributeError):
            raise ValueError("CAKTO_OFFERS_JSON deve mapear valores inteiros para IDs de oferta.") from None
        if (not offers or any(amount < 1 or not offer for amount, offer in offers.items())
                or min(offers) != int(min_deposit) or max(offers) != int(max_deposit)):
            raise ValueError("As ofertas Cakto devem cobrir exatamente os limites mínimo e máximo.")
        interval = int(os.getenv("POLL_SECONDS", "60"))
        if interval < 30:
            raise ValueError("POLL_SECONDS deve ser pelo menos 30.")
        pix_expires = int(os.getenv("CAKTO_PIX_EXPIRES_SECONDS", "3600"))
        if not 60 <= pix_expires <= 86400:
            raise ValueError("CAKTO_PIX_EXPIRES_SECONDS deve ficar entre 60 e 86400.")
        return cls(
            bot_token=token,
            api_key=key,
            admin_ids=ids(os.getenv("ADMIN_IDS", "")),
            allowed_services=ids(os.getenv("ALLOWED_SERVICE_IDS", "")),
            db_path=Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3")),
            max_order_cost=decimal_env("MAX_ORDER_COST", "5000"),
            poll_seconds=interval,
            bot_name=os.getenv("BOT_NAME", "Mais Popular").strip()[:80] or "Mais Popular",
            price_multiplier=multiplier,
            min_deposit_brl=min_deposit,
            max_deposit_brl=max_deposit,
            cakto_client_id=client_id,
            cakto_client_secret=client_secret,
            cakto_offers=offers,
            cakto_pix_expires=pix_expires,
            fingerprint_secret=fingerprint_secret,
            webapp_url_file=Path(os.getenv("WEBAPP_URL_FILE", "data/webapp_url.txt")),
            bot_username=os.getenv("BOT_USERNAME", "MaisPopularBot").strip().lstrip("@")[:32] or "MaisPopularBot",
        )

    def webapp_url(self) -> str:
        """Retorna somente uma URL HTTPS pública gravada pelo serviço do túnel."""
        try:
            value = self.webapp_url_file.read_text(encoding="utf-8").strip()
            parts = urlsplit(value)
        except (OSError, ValueError):
            return ""
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment):
            return ""
        return value.rstrip("/")
