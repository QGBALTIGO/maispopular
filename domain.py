"""Regras de catálogo, validação e dinheiro, sem chamadas externas."""
import html
import ipaddress
import re
import unicodedata
from dataclasses import dataclass, replace
from decimal import ROUND_UP, Decimal, InvalidOperation
from urllib.parse import urlsplit

from catalog_copy import clean_description, imported_description, subscription

SUPPORTED_TYPES = {"default", "custom comments", "package", "poll"}
TERMINAL = ("completed", "partial", "canceled", "cancelled", "refunded", "failed")
STATUS_PT = {
    "pending": "⏳ Pendente", "processing": "⚙️ Processando",
    "in progress": "🚀 Em andamento", "completed": "✅ Concluído",
    "partial": "🟡 Parcial", "canceled": "🚫 Cancelado",
    "cancelled": "🚫 Cancelado", "refunded": "↩️ Reembolsado",
    "failed": "❌ Falhou", "awaiting": "⏳ Aguardando atualização",
}

PLATFORMS = (
    ("Instagram", "📸", ("instagram", "insta ", " ig ", "reels")),
    ("TikTok", "🎵", ("tiktok", "tik tok")),
    ("YouTube", "▶️", ("youtube", "youtu.be", "shorts", " yt ")),
    ("Telegram", "✈️", ("telegram", "canal tg", "grupo tg")),
    ("Facebook", "📘", ("facebook", "facebook.com", "fb ")),
    ("Kwai", "🟠", ("kwai",)),
    ("X / Twitter", "🐦", ("twitter", "tweet", " x.com")),
    ("Threads", "🧵", ("threads",)),
    ("WhatsApp", "💬", ("whatsapp", "whats app", "whsp")),
    ("Spotify", "🎧", ("spotify",)),
    ("Twitch", "🟣", ("twitch",)),
    ("Discord", "🎮", ("discord",)),
    ("LinkedIn", "💼", ("linkedin",)),
    ("Pinterest", "📌", ("pinterest",)),
    ("SoundCloud", "☁️", ("soundcloud",)),
    ("SnackVideo", "⚫", ("snackvideo",)),
    ("Roblox", "🎲", ("roblox",)),
    ("Bluesky", "🦋", ("bluesky", "blue sky")),
    ("Kick", "🟢", (" kick ",)),
    ("Google", "🔎", ("google",)),
    ("Streaming e Apps", "🔥", ("servicos streaming", "serviços streaming")),
    ("Sites e SEO", "🌐", ("website", "site ", "seo", "trafego", "tráfego")),
)

PLATFORM_PRIORITY = (
    "Instagram", "TikTok", "YouTube", "Facebook", "Telegram", "WhatsApp",
    "Kwai", "SnackVideo", "X / Twitter", "Threads", "Spotify", "Twitch", "Discord",
    "LinkedIn", "Pinterest", "SoundCloud", "Kick", "Bluesky", "Google",
    "Sites e SEO", "Streaming e Apps", "Roblox",
)

SERVICE_FAMILIES = (
    ("Seguidores", ("seguidor", "seguidores", "follower")),
    ("Curtidas/Reações", ("curtida", "curtidas", " like", "likes", "reacao", "reaction")),
    ("Visualizações", ("visualizacao", "visualizacoes", " view", "views")),
    ("Comentários", ("comentario", "comentarios", "comment")),
    ("Membros/Inscritos", ("membro", "members", "inscrito", "subscriber")),
    ("Compartilhamentos", ("compartilh", " share", "repost", "retweet")),
    ("Alcance/Impressões", ("alcance", "reach", "impress")),
    ("Salvamentos", ("salvamento", "salvar", " save", "favorito", "favorite")),
    ("Stories/Lives", (" story", "stories", " live", "ao vivo")),
    ("Plays/Ouvintes", (" play", "plays", "ouvinte", "listener", "stream")),
    ("Cliques/Tráfego", ("clique", " click", "trafego", "visita", "visit")),
    ("Engajamento", ("engajamento", "engagement")),
)

BLOCKED_CATALOG_WORDS = (
    "nao comprar", "não comprar", "desativado", "disabled", "servico teste",
    "serviço teste", "test service", "nao usar", "não usar", "indisponivel",
    "indisponível", "saldo", "recarga", "painel smm", "api key",
    "uso interno", "interno",
)


def normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def decimal_value(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal(1000000000000):
            raise ValueError
        return number
    except (InvalidOperation, ValueError):
        raise ValueError("Foi recebido um valor monetário inválido.") from None


def retail_price(provider_cost: object, multiplier: Decimal = Decimal(2)) -> Decimal:
    return (decimal_value(provider_cost) * multiplier).quantize(Decimal("0.01"), rounding=ROUND_UP)


def money_brl(amount: object) -> str:
    number = decimal_value(amount).quantize(Decimal("0.01"), rounding=ROUND_UP)
    digits = f"{number:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {digits}"


def money(amount: object, currency: str = "BRL") -> str:
    if currency.upper() == "BRL":
        return money_brl(amount)
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
    value = html.unescape(re.sub(r"<[^>]*>", "", str(text)))
    value = re.sub(r"https?://\S+|(?:www\.)?soupopular\.net\S*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\bSou\s*Popular\b", "nossa plataforma", value, flags=re.IGNORECASE)
    return re.sub(r"[ \t]+", " ", value).strip()[:limit]


def platform_for(name: str, category: str) -> tuple[str, str]:
    haystack = f" {normalize(category)} {normalize(name)} "
    for label, emoji, needles in PLATFORMS:
        if any(normalize(needle) in haystack for needle in needles):
            return label, emoji
    return "Outros serviços", "✨"


def platform_sort_key(name: str) -> tuple[int, str]:
    try:
        return PLATFORM_PRIORITY.index(name), normalize(name)
    except ValueError:
        return len(PLATFORM_PRIORITY), normalize(name)


def family_for(name: str, category: str) -> str:
    for text in (name, category):
        haystack = f" {normalize(text)} "
        for label, needles in SERVICE_FAMILIES:
            if any(normalize(needle) in haystack for needle in needles):
                return label
    return "Outros serviços"


def family_sort_key(name: str) -> tuple[int, str]:
    labels = tuple(label for label, _ in SERVICE_FAMILIES) + (
        "Filmes e séries", "Vídeos e música", "Criação e produtividade",
        "Esportes", "Games", "Estudos e idiomas", "Combos", "Outros serviços")
    try:
        return labels.index(name), normalize(name)
    except ValueError:
        return len(labels), normalize(name)


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
    platform: str = "Outros serviços"
    platform_emoji: str = "✨"
    family: str = "Outros serviços"

    @classmethod
    def parse(cls, data: dict) -> "Service":
        service_id = int(data["service"])
        minimum, maximum = int(data["min"]), int(data["max"])
        rate = decimal_value(data["rate"])
        if service_id < 1 or minimum < 1 or maximum < minimum or maximum > 10**12 or rate <= 0:
            raise ValueError("Serviço com valores inválidos.")
        name = plain(re.sub(r"\([^)]*\d+:\d+.*", "", str(data["name"])), 350)
        category = plain(data.get("category", "Outros"), 160) or "Outros"
        app = subscription(service_id, name, category)
        platform, emoji = ("Streaming e Apps", "▶️") if app else platform_for(name, category)
        family = app[3] if app else family_for(name, category)
        source_description = data.get("description") or imported_description(service_id, str(data["name"]))
        description = plain(clean_description(source_description), 8000)
        if app:
            # Full brand identity; plan conditions stay in the detail copy.
            original_name = name
            duration = re.search(r"(\d+)\s*dias", original_name + " " + description, re.IGNORECASE)
            name = app[1] + (f" · {duration[1]} dias" if duration else "")
            if "compartilhad" in original_name.casefold():
                name += " · compartilhado"
            elif "convite" in original_name.casefold():
                name += " · por convite"
        if not description:
            description = (f"{name}. {plain(original_name.split('|', 1)[-1], 350)}. As condições detalhadas de entrega não foram informadas. "
                           "Consulte o atendimento antes de contratar." if app else
                           f"{name}. Confira o destino, os limites e as condições antes de confirmar.")
        return cls(service_id, name, category, str(data["type"]).strip(), rate,
                   minimum, maximum, description, capability(data.get("refill")),
                   capability(data.get("cancel")), platform, emoji, family)

    @property
    def supported(self) -> bool:
        return self.kind.casefold() in SUPPORTED_TYPES

    @property
    def sellable(self) -> bool:
        haystack = normalize(f"{self.name} {self.category}")
        return (self.supported and self.platform != "Outros serviços"
                and bool(re.search(r"[A-Za-zÀ-ÿ0-9]", self.name))
                and not any(normalize(x) in haystack for x in BLOCKED_CATALOG_WORDS))

    def with_retail_rate(self, multiplier: Decimal) -> "Service":
        return replace(self, rate=retail_price(self.rate, multiplier))


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
    return value


def build_payload(service: Service, target: str, value: str | None = None,
                  answer: str | None = None) -> tuple[dict, Decimal]:
    if not service.supported:
        raise ValueError("Esse tipo de serviço não está disponível para compra.")
    kind = service.kind.casefold()
    payload = {"service": service.id, "link": validate_target(target)}
    if kind == "package":
        return payload, service.rate
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
    value = payload.get("comments", str(payload.get("quantity", "")))
    current, cost = build_payload(service, payload["link"], value, str(payload.get("answer_number", "")))
    if current != payload:
        raise ValueError("O formato do serviço mudou. Monte um novo pedido.")
    return cost
