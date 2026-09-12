"""Vitrine pública organizada por plataforma."""
import time

from telegram import Update
from telegram.ext import ContextTypes

from domain import family_sort_key, money_brl, normalize, platform_sort_key
from ui_common import PAGE, btn, category_key, e, home_rows, pager, panel, say, uid


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    p.store.abort_drafts(uid(update))
    context.user_data.pop("flow", None)
    balance = p.store.balance_cents(uid(update)) / 100
    name = (update.effective_user.first_name or "cliente")[:60]
    await say(update,
        f"<b>Bem-vindo à {e(p.settings.bot_name)}, {e(name)}!</b>\n\n"
        "Escolha uma rede social, confira os detalhes e acompanhe tudo pelo próprio bot.\n\n"
        f"👛 <b>Seu saldo:</b> {money_brl(balance)}",
        home_rows(p.is_admin(uid(update)), p.settings.webapp_url()))


async def identity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await say(update, f"🆔 <b>Seu ID</b>\n\n<code>{uid(update)}</code>",
              [[btn("🏠 Início", "home")]])


async def help_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await say(update,
        "❓ <b>Como comprar</b>\n\n"
        "1️⃣ Adicione saldo por Pix.\n"
        "2️⃣ Abra o catálogo e escolha a rede social.\n"
        "3️⃣ Selecione o serviço, informe o link e a quantidade.\n"
        "4️⃣ Confira o resumo e confirme.\n\n"
        "O preço exibido no resumo é o valor final debitado da carteira. "
        "Nunca envie senhas; cada serviço solicita somente um link ou @usuário.\n\n"
        "/start — início\n/catalogo — redes sociais\n/buscar — localizar serviço\n"
        "/saldo — carteira\n/recarga — adicionar saldo\n/pedidos — acompanhar pedidos\n"
        "/cancelar — descartar preenchimento atual",
        [[btn("🏠 Início", "home")]])


async def balance_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    balance = p.store.balance_cents(uid(update)) / 100
    entries = p.store.ledger(uid(update), 5)
    history = []
    for row in entries:
        sign = "+" if row["amount_cents"] >= 0 else "−"
        history.append(f"{sign} {money_brl(abs(row['amount_cents']) / 100)} · {e(row['description'])}")
    await say(update,
        f"👛 <b>Minha carteira</b>\n\n💰 Saldo disponível: <b>{money_brl(balance)}</b>\n\n"
        + ("<b>Últimas movimentações</b>\n" + "\n".join(history) if history else "Nenhuma movimentação ainda."),
        [[btn("💳 Adicionar saldo", "deposit")],
         [btn("🔄 Atualizar", "balance"), btn("🏠 Início", "home")]])


async def catalog_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    services = await panel(context).catalog()
    counts = {name: sum(s.platform == name for s in services) for name in {s.platform for s in services}}
    platforms = sorted(counts, key=platform_sort_key)
    buttons = [btn(f"{name} · {counts[name]}", f"platform:{category_key(name)}:0")
               for name in platforms]
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    rows += [[btn("🔎 Buscar serviço", "search_prompt"), btn("🏠 Início", "home")]]
    await say(update,
        f"🛍️ <b>Catálogo</b>\n\n{len(services)} serviços disponíveis em {len(platforms)} áreas.\n\n"
        "Escolha a rede ou plataforma:", rows)


async def platform_page(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, page: int) -> None:
    services = [s for s in await panel(context).catalog() if category_key(s.platform) == key]
    if not services:
        raise ValueError("Esta categoria não está mais disponível. Reabra o catálogo.")
    counts = {name: sum(s.family == name for s in services) for name in {s.family for s in services}}
    families = sorted(counts, key=family_sort_key)
    buttons = [btn(f"{name} · {counts[name]}",
                   f"family:{key}:{category_key(name)}:0") for name in families]
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    rows += [[btn("🌐 Todas as redes", "catalog:0"), btn("🏠 Início", "home")]]
    await say(update,
        f"<b>{e(services[0].platform)}</b>\n\n"
        f"{len(services)} serviços. Escolha o tipo que você procura:", rows)


async def family_page(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      platform_key: str, family_key: str, page: int) -> None:
    services = [s for s in await panel(context).catalog()
                if category_key(s.platform) == platform_key and category_key(s.family) == family_key]
    if not services:
        raise ValueError("Esta opção não está mais disponível. Reabra o catálogo.")
    page = min(max(page, 0), (len(services) - 1) // PAGE)
    rows = [[btn(f"#{s.id} · {s.name[:42]}", f"service:{s.id}")]
            for s in services[page * PAGE:(page + 1) * PAGE]]
    rows += [pager(f"family:{platform_key}:{family_key}", page, len(services)),
             [btn(f"↩️ Tipos de {services[0].platform[:22]}", f"platform:{platform_key}:0"),
              btn("🏠 Início", "home")]]
    await say(update,
        f"<b>{e(services[0].platform)} · {e(services[0].family)}</b>\n\n"
        f"{len(services)} opção(ões). Toque em uma para ver preço, limites e descrição:", rows)


async def search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    panel(context).store.abort_drafts(uid(update))
    context.user_data["flow"] = {"step": "search", "expires": time.time() + 900}
    await say(update, "🔎 <b>Buscar serviço</b>\n\nEnvie uma rede, tipo de serviço ou código.\n"
              "Exemplos: <code>Instagram</code>, <code>seguidores</code>, <code>Telegram</code>.",
              [[btn("🏠 Voltar", "home")]])


async def search_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    term = context.user_data.get("search", "")
    words = normalize(term).split()
    services = [s for s in await panel(context).catalog()
                if all(word in normalize(f"{s.id} {s.name} {s.category} {s.platform} {s.description}") for word in words)]
    page = min(max(page, 0), max(0, (len(services) - 1) // PAGE))
    rows = [[btn(f"#{s.id} · {s.name[:47]}", f"service:{s.id}")]
            for s in services[page * PAGE:(page + 1) * PAGE]]
    if services:
        rows.append(pager("search", page, len(services)))
    rows += [[btn("🔎 Nova busca", "search_prompt"), btn("🏠 Início", "home")]]
    await say(update, f"🔎 <b>Resultados para “{e(term)}”</b>\n\n{len(services)} serviços encontrados.", rows)


async def service_page(update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int) -> None:
    p = panel(context)
    s = await p.service(service_id)
    unit = "por pacote" if s.kind.casefold() == "package" else "por 1.000 unidades"
    flags = lambda value: "Disponível" if value is True else ("Indisponível" if value is False else "Consulte após a compra")
    text = (
        f"<b>{e(s.name)}</b>\n\n"
        f"🏷️ Código: <code>{s.id}</code>\n"
        f"🌐 Rede: {e(s.platform)}\n"
        f"💵 Valor: <b>{money_brl(p.retail_rate(s))}</b> {unit}\n"
        f"📏 Mínimo: <b>{s.minimum}</b> · Máximo: <b>{s.maximum}</b>\n"
        f"♻️ Reposição: {flags(s.refill)}\n"
        f"🚫 Cancelamento: {flags(s.cancel)}\n\n"
        f"<b>Sobre o serviço</b>\n{e(s.description)}"
    )
    rows = [[btn("🛒 Comprar", f"buy:{s.id}")],
            [btn(f"↩️ Voltar para {s.family[:30]}",
                 f"family:{category_key(s.platform)}:{category_key(s.family)}:0")],
            [btn("🏠 Início", "home")]]
    await say(update, text, rows)
