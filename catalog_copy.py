"""Apresentação editorial; não altera IDs, preço, limites ou payloads."""
import json
import re
from functools import lru_cache
from pathlib import Path

# Nomes por ID e prefixo: um ID reutilizado não herda a identidade antiga.
SUBSCRIPTIONS = {
    721: ("Ntx", "Netflix", "netflix", "Filmes e séries"),
    910: ("DN plus", "Disney+", "disneyplus", "Filmes e séries"),
    700: ("PV", "Prime Video", "primevideo", "Filmes e séries"),
    729: ("HMX", "HBO Max", "hbo", "Filmes e séries"),
    911: ("HMX", "HBO Max + Champions League", "hbo", "Filmes e séries"),
    703: ("Chat GPT", "ChatGPT Plus", "openai", "Criação e produtividade"),
    728: ("Cv PRO", "Canva Pro", "canva", "Criação e produtividade"),
    707: ("YT Premium", "YouTube Premium + Canva Pro", "youtube", "Combos"),
    706: ("YT", "YouTube Premium", "youtube", "Vídeos e música"),
    708: ("CCut", "CapCut Premium", "capcut", "Criação e produtividade"),
    912: ("GPLAY", "Globoplay + canais", "globoplay", "Filmes e séries"),
    913: ("Premiere", "Premiere Futebol", "premiere", "Esportes"),
    701: ("Crunchyroll", "Crunchyroll Premium", "crunchyroll", "Filmes e séries"),
    756: ("Paramount", "Paramount+", "paramountplus", "Filmes e séries"),
    914: ("Viki", "Rakuten Viki", "rakutenviki", "Filmes e séries"),
    702: ("Nord VPN", "NordVPN Premium", "nordvpn", "Criação e produtividade"),
    705: ("Brainly", "Brainly Plus", "brainly", "Estudos e idiomas"),
    704: ("QConcurso", "Qconcursos", "qconcursos", "Estudos e idiomas"),
    915: ("DUOLINGO", "Super Duolingo", "duolingo", "Estudos e idiomas"),
    916: ("XBOX", "Xbox Game Pass Ultimate", "xbox", "Games"),
}


@lru_cache(maxsize=1)
def imported_content():
    return json.loads(Path(__file__).with_name("catalog_content.json").read_text(encoding="utf-8"))


def no_symbols(value):
    value = re.sub(r"[^\w\s.,:;!?@/()+%&'\"=·\-À-ÿ]", " ", value, flags=re.UNICODE)
    return re.sub(r"[ \t]+", " ", value).strip(" -|")


def subscription(service_id, raw_name, category):
    item = SUBSCRIPTIONS.get(service_id)
    if item and "streaming" in category.casefold() and item[0].casefold() in raw_name.casefold():
        return item
    return None


def imported_description(service_id, name):
    item = imported_content().get(str(service_id), {})
    # Match source name, not only ID, to avoid stale descriptions on new products.
    if no_symbols(item.get("sourceName", "")).casefold() != no_symbols(name).casefold():
        return ""
    return item.get("description", "")


def clean_description(value):
    value = re.sub(r"<br\s*/?>|</p>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"@?soupopular(?:\.ofc|\.net)?", "@seuusuario", value, flags=re.IGNORECASE)
    value = re.sub(r"[\U0001F000-\U0001FAFF\u2300-\u27ff]+", "\n", value)
    value = re.sub(r"[-_]{3,}", "\n", value)
    value = value.replace("\ufe0f", "").replace("\u200b", "")
    lines = [no_symbols(line) for line in value.splitlines()]
    return "\n".join(dict.fromkeys(line for line in lines if line and line not in {"Informações:", "Atenção:"}))[:8000]


def display_name(name):
    value = re.sub(r"\([^)]*\d+:\d+[^)]*\)", "", name)
    value = re.sub(r"[|\[{]", " · ", value)
    value = no_symbols(value)
    replacements = {r"\bIG\b": "Instagram", r"\bTK\b": "TikTok", r"\bYT\b": "YouTube",
                    r"\bWHSP\b": "WhatsApp", r"\bBR\b": "brasileiros",
                    r"\bHQ\b": "alta qualidade", r"\bMQ\b": "qualidade média",
                    r"\bSR\b": "sem reposição", r"\bAR(\d+)\b": r"reposição automática por \1 dias",
                    r"\bR(\d+)\b": r"reposição por \1 dias"}
    for pattern, replacement in replacements.items():
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    # Sentence case only for all-uppercase source words; preserve established brand names.
    value = re.sub(r"\b[A-ZÀ-Ý]{2,}\b", lambda m: m[0].lower(), value)
    value = re.sub(r"\s*[/]\s*", " / ", value)
    value = re.sub(r"(?:\s*·\s*)+", " · ", value).strip(" ·")
    return value[:1].upper() + value[1:]


def presentation(item):
    raw = SUBSCRIPTIONS.get(item.id)
    is_subscription = item.platform == "Streaming e Apps" and raw and item.name.startswith(raw[1])
    description = clean_description(item.description)
    warning = ""
    if item.id == 698 and "Facebook" in description:
        description = "Seguidores brasileiros para Instagram. A descrição detalhada recebida está divergente; consulte o atendimento antes de contratar."
        warning = "Descrição em revisão: confirme as condições no atendimento."
    elif item.id == 704 and "COPILOT" in description:
        warning = "A descrição contém informações divergentes. Confirme o plano e a entrega no atendimento."
    elif item.id == 906 and "NÃO há reposição" in description:
        warning = "O título menciona reposição, mas a descrição informa que não há. Confirme as condições antes de comprar."
    if is_subscription:
        manual = "manual" in description.casefold()
        # Avoid making customers follow an internal supplier workflow.
        if manual:
            description = re.sub(r"É super simples!.*?(?=Leia antes|Pagamento|$)", "", description, flags=re.DOTALL)
            description = re.sub(r"Entrega manual:.*?(?=\n|$)", "Entrega manual: solicite atendimento pelo bot após a confirmação do pedido.", description)
            description = re.sub(r"Como funciona\?", "", description)
        # Remove repeated advertising, retain plan restrictions and fulfilment terms.
        lines = []
        for line in description.splitlines():
            if line.startswith(("Qualidade:", "Situação:", "Assinatura:", "Leia antes", "Identificação:", "Garantia:")):
                continue
            line = line.replace("Pagamento único: Você paga uma vez e tem acesso à conta por 30 dias, para usar como e onde quiser.",
                                "Duração: 30 dias de acesso, com pagamento único.")
            line = line.replace("Garantia de 30 dias: Cobertura para qualquer eventual problema durante esse período.",
                                "Garantia informada: 30 dias para problemas no acesso.")
            if line.strip():
                lines.append(line.strip())
        description = "\n".join(lines)
        duration = re.search(r"(\d+) dias", item.name)
        short = f"Plano de {duration[1]} dias" if duration else "Assinatura digital"
        if "compartilhad" in (description + item.name).casefold():
            short += " · acesso compartilhado"
        elif "convite" in item.name.casefold():
            short += " · acesso por convite"
        else:
            short += " · consulte as condições"
        return {"displayName": item.name, "brand": raw[2], "summary": short,
                "details": description, "warning": warning,
                "manualDelivery": manual, "targetLabel": "Seu @usuário no Telegram",
                "targetHint": "Usado para identificar seu pedido. Não informe senhas."}
    full_name = display_name(item.name)
    parts = full_name.split(" · ")
    if len(parts) > 1 and len(parts[0].strip()) < 12 and parts[0].strip().casefold() in {"instagram", "tiktok", "youtube", "kwai", "telegram"}:
        parts = [parts[0] + " · " + parts[1], *parts[2:]]
    title = parts[0]
    subtitle = " · ".join(dict.fromkeys(parts[1:])) or item.family
    return {"displayName": title, "brand": "", "summary": subtitle,
            "details": description, "warning": warning, "manualDelivery": False,
            "targetLabel": "Link ou @usuário", "targetHint": "Use o destino indicado na descrição. Não informe senhas."}
