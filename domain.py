"""Validações e cálculo de orçamento, sem chamadas externas."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_UP
import html
import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit

SUPPORTED_TYPES = {"default", "custom comments", "package", "poll"}
TERMINAL = ("completed", "partial", "canceled", "cancelled", "refunded", "failed")
STATUS_PT = {
    "pending": "⏳ Pendente", "processing": "⚙️ Processando",
    "in progress": "🚀 Em andamento", "completed": "✅ Concluído",
    "partial": "🟡 Parcial", "canceled": "🚫 Cancelado",
    "cancelled": "🚫 Cancelado", "refunded": "↩️ Reembolsado",
    "failed": "❌ Falhou", "awaiting": "⏳ Aguardando atualização",
}


def normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def decimal_value(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal("1000000000000"):
            raise ValueError
        return number
    except (InvalidOperation, ValueError):
        raise ValueError("O fornecedor retornou um valor monetário inválido.") from None


def money(amount: object, currency: str) -> str:
    # Cinco casas preservam custos pequenos, sem exibir R$ 0,00 indevidamente.
    number = decimal_value(amount).quantize(Decimal("0.00001"), rounding=ROUND_UP)
    digits = f"{number:,.5f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{currency} {digits}"


def capability(value: object) -> bool | None:
    if value is None:
        return None
    if value is True or str(value).lower() in {"1", "true", "yes"}:
        return True
    if value is False or str(value).lower() in {"0", "false", "no"}:
        return False
    return None


def plain(text: object, limit: int = 1000) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", str(text)))[:limit]


@dataclass(frozen=True)
class Service:
    id: int
    name: str
    category: str
    kind: str
    rate: Decimal
    minimum: int
    maximum: int
    description: str
    refill: bool | None
    cancel: bool | None

    @classmethod
    def parse(cls, data: dict) -> "Service":
        service_id = int(data["service"])
        minimum, maximum = int(data["min"]), int(data["max"])
        if service_id < 1 or minimum < 0 or maximum < minimum or maximum > 10**12:
            raise ValueError("Serviço com limites inválidos.")
        return cls(service_id, plain(data["name"], 220),
                   plain(data.get("category", "Outros"), 160), str(data["type"]).strip(),
                   decimal_value(data["rate"]), minimum, maximum,
                   plain(data.get("description") or "", 1200),
                   capability(data.get("refill")), capability(data.get("cancel")))

    @property
    def supported(self) -> bool:
        return self.kind.casefold() in SUPPORTED_TYPES


def validate_target(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 1500 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Envie um link ou nome de usuário válido, sem espaços.")
    if re.fullmatch(r"@?[A-Za-z0-9_.-]{2,120}", value) and ":" not in value:
        return value
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
            raise ValueError
        if host == "localhost" or host.endswith((".local", ".internal")) or parts.port not in {None, 80, 443}:
            raise ValueError
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or any(c in host for c in "\\<>\"'"):
                raise ValueError
        else:
            if not ip.is_global:
                raise ValueError
    except ValueError:
        raise ValueError("Envie uma URL pública http/https ou um @usuário, conforme o serviço.") from None
    # O bot não visita o destino: apenas transmite o campo ao fornecedor.
    return value


def build_payload(service: Service, target: str, value: str | None = None,
                  answer: str | None = None) -> tuple[dict, Decimal]:
    if not service.supported:
        raise ValueError("Esse tipo de serviço ainda não tem formulário nesta versão.")
    kind = service.kind.casefold()
    payload = {"service": service.id, "link": validate_target(target)}
    if kind == "package":
        return payload, service.rate  # Preço do pacote, não dividido por mil.
    if kind == "custom comments":
        comments = [line.strip() for line in (value or "").splitlines() if line.strip()]
        if not comments or len("\n".join(comments)) > 3500:
            raise ValueError("Envie um comentário por linha, em uma mensagem de até 3.500 caracteres.")
        quantity = len(comments)
        payload["comments"] = "\n".join(comments)
    else:
        raw = (value or "").strip()
        if not re.fullmatch(r"[0-9]{1,13}", raw):
            raise ValueError("Envie a quantidade inteira, sem pontos ou vírgulas. Exemplo: 1000.")
        quantity = int(raw)
        payload["quantity"] = quantity
    if quantity <= 0 or not service.minimum <= quantity <= service.maximum:
        raise ValueError(f"A quantidade precisa estar entre {service.minimum} e {service.maximum}.")
    if kind == "poll":
        if not re.fullmatch(r"[0-9]{1,6}", (answer or "").strip()) or int(answer) < 1:
            raise ValueError("Envie o número positivo da alternativa da enquete.")
        payload["answer_number"] = int(answer)
    return payload, service.rate * Decimal(quantity) / Decimal(1000)


def check_quote(service: Service, payload: dict) -> Decimal:
    """Recalcula o mesmo formulário usando preços e limites recém-consultados."""
    value = payload.get("comments", str(payload.get("quantity", "")))
    current, cost = build_payload(service, payload["link"], value, str(payload.get("answer_number", "")))
    if current != payload:
        raise ValueError("O formato do serviço mudou. Monte um novo pedido.")
    return cost
