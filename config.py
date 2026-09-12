"""Configuração: nunca grave tokens no código ou no Git."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os

from dotenv import load_dotenv

API_URL = "https://soupopular.net/api/v2"


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


@dataclass(frozen=True)
class Settings:
    bot_token: str
    api_key: str
    admin_ids: frozenset[int]
    allowed_services: frozenset[int]
    db_path: Path
    dry_run: bool
    max_order_cost: Decimal
    poll_seconds: int
    bot_name: str

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(override=False)
        token = os.getenv("BOT_TOKEN", "").strip()
        key = os.getenv("SOUPOPULAR_API_KEY", "").strip()
        if not token or token == "COLE_O_TOKEN_DO_BOTFATHER":
            raise ValueError("Configure BOT_TOKEN no arquivo .env.")
        if not key or key == "COLE_SUA_CHAVE_DA_SOPOPULAR":
            raise ValueError("Configure SOUPOPULAR_API_KEY no arquivo .env.")
        try:
            cap = Decimal(os.getenv("MAX_ORDER_COST", "20.00"))
            if not cap.is_finite() or cap <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError("MAX_ORDER_COST deve ser um valor positivo, com ponto decimal.") from None
        interval = int(os.getenv("POLL_SECONDS", "120"))
        if interval < 30:
            raise ValueError("POLL_SECONDS deve ser pelo menos 30.")
        name = os.getenv("BOT_NAME", "Mais Popular").strip()[:80]
        return cls(
            bot_token=token, api_key=key,
            admin_ids=ids(os.getenv("ADMIN_IDS", "")),
            allowed_services=ids(os.getenv("ALLOWED_SERVICE_IDS", "")),
            db_path=Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3")),
            dry_run=boolean(os.getenv("DRY_RUN", "true")),
            max_order_cost=cap, poll_seconds=interval, bot_name=name,
        )
