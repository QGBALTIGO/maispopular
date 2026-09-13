"use strict";
const tg = window.Telegram?.WebApp;
const initData = tg?.initData || "";
const state = {
  bootstrap: null,
  catalog: null,
  platform: null,
  family: null,
  service: null,
  quote: null,
  view: "platforms",
  catalogRequest: 0,
  ordersPage: 0,
  ordersLoading: false,
  confirming: false,
};
const $ = (id) => document.getElementById(id);
const formatMoney = (value) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
    value,
  );
const number = (value) => new Intl.NumberFormat("pt-BR").format(value);
const normalize = (value) =>
  String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
const date = (value) =>
  new Date(value * 1000).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
const paths = {
  wallet:
    "M20 8V5a2 2 0 0 0-2-2H5a3 3 0 0 0 0 6h15v11H5a3 3 0 0 1-3-3V6M20 12h-5v5h5M17 14.5h.01",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  receipt: "M6 3h12v18l-3-2-3 2-3-2-3 2V3zM9 8h6M9 12h6",
  help: "M9.1 9a3 3 0 1 1 5.8 1c-.8 1-2.9 1.5-2.9 3M12 17h.01",
  search: "M21 21l-5-5M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0",
  plus: "M12 5v14M5 12h14",
  close: "M6 6l12 12M18 6 6 18",
  back: "M19 12H5m6-6-6 6 6 6",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  chevron: "m9 5 7 7-7 7",
  lock: "M6 10h12v11H6zM8 10V7a4 4 0 0 1 8 0v3M12 14v3",
  shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3zm-4 9 3 3 5-6",
  check: "m5 12 4 4L19 6",
  refresh: "M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3",
  users:
    "M16 21v-3a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v3M15 4a4 4 0 0 1 0 8M22 21v-3a4 4 0 0 0-3-3.9M12 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  heart:
    "M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  chat: "M21 11a9 9 0 0 1-9 9H3l2-4A9 9 0 1 1 21 11",
  share: "M12 16V3m-5 5 5-5 5 5M5 12H3v9h18v-9h-2",
  play: "m9 6 10 6-10 6V6zM3 3v18",
  bookmark: "M6 3h12v18l-6-4-6 4V3z",
  chart: "M4 20V10M12 20V4M20 20v-7",
  globe:
    "M21 12H3M12 3c-6 6-6 12 0 18 6-6 6-12 0-18M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  telegram: "m22 3-7 18-4-7-9-4L22 3zm-11 11 6-6",
  screen: "M3 4h18v13H3zM8 21h8m-4-4v4",
};
function icon(name, className = "") {
  const el = document.createElement("span");
  el.className = className;
  el.setAttribute("aria-hidden", "true");
  el.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round"><path d="${paths[name] || paths.grid}"/></svg>`;
  return el;
}
document
  .querySelectorAll("[data-icon]")
  .forEach((el) => el.append(icon(el.dataset.icon)));
const brandSlugs = {
  Instagram: "instagram",
  TikTok: "tiktok",
  YouTube: "youtube",
  Telegram: "telegram",
  Facebook: "facebook",
  WhatsApp: "whatsapp",
  Kwai: "kwai",
  "X / Twitter": "x",
  Threads: "threads",
  Spotify: "spotify",
  Twitch: "twitch",
  Discord: "discord",
  LinkedIn: "linkedin",
  Pinterest: "pinterest",
  SoundCloud: "soundcloud",
  SnackVideo: "snackvideo",
  Roblox: "roblox",
  Bluesky: "bluesky",
  Kick: "kick",
  Google: "google",
};
function logo(platform, slug = "") {
  const key = slug || brandSlugs[platform];
  const wrap = document.createElement("span");
  wrap.className = `brand-icon brand-${key || "generic"}`;
  wrap.setAttribute("aria-hidden", "true");
  if (key) {
    const img = document.createElement("img");
    img.src = `/assets/brands/${key}.${{ kwai: "png", snackvideo: "png", capcut: "ico", globoplay: "png", rakutenviki: "png", premiere: "ico", brainly: "jpg", qconcursos: "jpg" }[key] || "svg"}`;
    img.alt = "";
    img.width = 27;
    img.height = 27;
    img.addEventListener("error", () => wrap.replaceChildren(icon("screen")), {
      once: true,
    });
    wrap.append(img);
  } else
    wrap.append(icon(platform === "Streaming e Apps" ? "screen" : "globe"));
  return wrap;
}
function element(tag, className, text) {
  const el = document.createElement(tag);
  el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function action(className, callback) {
  const el = element("button", className);
  el.type = "button";
  el.addEventListener("click", callback);
  return el;
}
function familyIcon(name) {
  const n = normalize(name);
  for (const [word, key] of [
    ["seguidor", "users"],
    ["curtida", "heart"],
    ["visual", "eye"],
    ["coment", "chat"],
    ["membro", "users"],
    ["inscrito", "users"],
    ["compartilh", "share"],
    ["salv", "bookmark"],
    ["alcance", "chart"],
    ["filme", "screen"],
    ["video", "play"],
    ["live", "play"],
    ["play", "play"],
  ])
    if (n.includes(word)) return key;
  return "grid";
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.add("hidden"), 5500);
}
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      signal: AbortSignal.timeout(45000),
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": initData,
      },
    });
  } catch {
    throw new Error("A conexão demorou mais que o esperado. Tente novamente.");
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("Não foi possível carregar os dados. Tente novamente.");
  }
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Confira os dados e tente novamente.",
    );
  return data;
}
function busy(button, value) {
  button.disabled = value;
  button.setAttribute("aria-busy", String(value));
}
function updateBalance(data) {
  if (state.bootstrap) {
    state.bootstrap.balance = data.balance;
    state.bootstrap.balanceLabel = data.balanceLabel;
  }
  $("balanceLabel").textContent = data.balanceLabel;
  $("walletBalance").textContent = data.balanceLabel;
}
function show(id) {
  state.view = id;
  window.storeOperations?.onView(id);
  document
    .querySelectorAll(".view")
    .forEach((el) => el.classList.toggle("hidden", el.id !== id));
  const active = ["families", "services", "order", "success"].includes(id)
    ? "platforms"
    : ["deposit", "payment", "admin"].includes(id)
      ? "wallet"
      : id === "orderDetail"
        ? "orders"
        : id;
  document.querySelectorAll("[data-nav]").forEach((el) => {
    el.classList.toggle("active", el.dataset.nav === active);
    if (el.dataset.nav === active) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  if (tg?.BackButton) {
    id === "platforms" ? tg.BackButton.hide() : tg.BackButton.show();
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}
function goBack() {
  if ($("operationConfirm").open) {
    $("operationConfirm").close("no");
    return;
  }
  if ($("reviewModal").open) {
    if (!state.confirming) $("reviewModal").close();
    return;
  }
  navigate(
    {
      families: "platforms",
      services: "families",
      order: "services",
      deposit: "wallet",
      payment: "wallet",
      admin: "wallet",
      orderDetail: "orders",
    }[state.view] || "platforms",
  );
}
function openBot(start = "") {
  const url =
    (state.bootstrap?.botUrl || "https://t.me/MaisPopularBot") +
    (start ? `?start=${start}` : "");
  if (tg?.openTelegramLink) tg.openTelegramLink(url);
  else location.assign(url);
}
function failure(container, error, retry) {
  const el = element("div", "retry-panel");
  el.append(element("p", "", error.message));
  const button = action("secondary-button", retry);
  button.textContent = "Tentar novamente";
  el.append(button);
  container.replaceChildren(el);
}
function empty(container, text, key = "receipt") {
  const el = element("div", "empty-small");
  el.append(icon(key), element("p", "", text));
  container.replaceChildren(el);
}
function renderPlatforms() {
  const grid = $("platformGrid");
  grid.replaceChildren();
  $("subscriptionEntry").replaceChildren();
  for (const platform of state.bootstrap.platforms) {
    if (platform.name === "Streaming e Apps") {
      const card = action("subscription-entry", () =>
        selectPlatform(platform.name),
      );
      const copy = element("div", "");
      copy.append(
        element("strong", "", "Streaming e apps"),
        element("p", "", "Filmes, séries, criação e muito mais."),
      );
      card.append(logo(platform.name), copy, icon("arrow", "card-arrow"));
      $("subscriptionEntry").append(card);
      continue;
    }
    const card = action(
      `shop-product social-card social-${brandSlugs[platform.name] || "generic"}`,
      () => selectPlatform(platform.name),
    );
    const art = element("div", "product-art");
    art.append(logo(platform.name), element("strong", "", platform.name));
    const copy = element("div", "product-copy");
    copy.append(
      element("h3", "", platform.name),
      element("p", "", platform.summary),
      element("small", "social-from", "A partir de"),
      element("strong", "product-price", platform.fromPriceLabel),
      element(
        "small",
        "",
        platform.fromKind === "package"
          ? "por pacote"
          : `por unidade · mín. ${number(platform.fromMinimum)}`,
      ),
      element("span", "product-cta", "Ver categorias →"),
    );
    card.append(art, copy);
    grid.append(card);
  }
}
async function selectPlatform(name) {
  const request = ++state.catalogRequest;
  state.platform = name;
  state.family = null;
  state.service = null;
  $("familyPlatform").textContent = name;
  $("familyLogo").replaceChildren(logo(name));
  $("familyGrid").replaceChildren(
    element("div", "loading-inline", "Carregando categorias…"),
  );
  show("families");
  try {
    const catalog = await api(
      `/api/catalog?platform=${encodeURIComponent(name)}`,
    );
    if (request !== state.catalogRequest) return;
    state.catalog = catalog;
    renderFamilies();
  } catch (error) {
    if (request === state.catalogRequest)
      failure($("familyGrid"), error, () => selectPlatform(name));
  }
}
function renderFamilies() {
  const grid = $("familyGrid");
  grid.replaceChildren();
  for (const family of state.catalog.families) {
    const count = state.catalog.services.filter(
      (s) => s.family === family,
    ).length;
    const card = action("family-card", () => selectFamily(family));
    const copy = element("div", "");
    copy.append(
      element("strong", "", categoryLabel(family)),
      element(
        "small",
        "",
        `${count} ${count === 1 ? "opção disponível" : "opções disponíveis"}`,
      ),
    );
    card.append(
      icon(familyIcon(family), "family-icon"),
      copy,
      icon("chevron", "card-arrow"),
    );
    grid.append(card);
  }
}
function selectFamily(name) {
  state.family = name;
  $("serviceContext").replaceChildren(
    logo(state.platform),
    element("span", "", state.platform),
  );
  $("serviceHeading").textContent = name.replaceAll("/", " e ");
  $("serviceSearch").value = "";
  $("serviceSort").value = "default";
  renderCategoryTabs();
  renderServices();
  show("services");
}
function categoryLabel(name) {
  return (
    {
      "Curtidas/Reações": "Curtidas",
      "Seguidores/Inscritos": "Seguidores",
      Compartilhamentos: "Compartilhar",
    }[name] || name.replaceAll("/", " e ")
  );
}
function renderCategoryTabs() {
  $("categoryTabs").replaceChildren(
    ...state.catalog.families.map((name) => {
      const button = action("category-pill", () => selectFamily(name));
      button.setAttribute("aria-pressed", String(name === state.family));
      button.append(
        icon(familyIcon(name)),
        element("span", "", categoryLabel(name)),
      );
      return button;
    }),
  );
}
function customProductArt(service) {
  if (!service.banner?.custom) return null;
  const art = element("div", "product-art custom-product-art");
  const image = element(
    "img",
    `fit-${service.banner.fit} pos-${service.banner.position}`,
  );
  image.src = service.banner.url;
  image.alt = service.displayName;
  image.loading = "lazy";
  image.addEventListener(
    "error",
    () => {
      art.classList.remove("custom-product-art");
      art.replaceChildren(
        logo(service.platform, service.brand),
        element("strong", "", service.displayName),
      );
    },
    { once: true },
  );
  art.append(image);
  return art;
}
function renderServices() {
  const search = normalize($("serviceSearch").value);
  let rows = state.catalog.services.filter(
    (s) =>
      s.family === state.family &&
      normalize(`${s.id} ${s.name} ${s.displayName} ${s.summary}`).includes(
        search,
      ),
  );
  if ($("serviceSort").value === "price")
    rows.sort((a, b) => Number(a.retailRate) - Number(b.retailRate));
  if ($("serviceSort").value === "name")
    rows.sort((a, b) => a.displayName.localeCompare(b.displayName, "pt-BR"));
  $("resultCount").textContent =
    `${rows.length} ${rows.length === 1 ? "serviço" : "serviços"}`;
  const list = $("serviceList");
  list.replaceChildren();
  if (!rows.length) {
    empty(
      list,
      "Nenhum serviço encontrado. Tente outro nome ou código.",
      "search",
    );
    return;
  }
  for (const s of rows) {
    const card = action("service-card", () => selectService(s));
    const banner = customProductArt(s);
    if (banner) card.append(banner);
    const top = element("div", "service-top");
    top.append(
      logo(s.platform, s.brand),
      element("span", "service-code", `CÓD. ${s.id}`),
    );
    card.append(
      top,
      element("h3", "", s.displayName),
      element("p", "service-summary", s.summary),
    );
    if (s.manualDelivery)
      card.append(element("span", "chip warning", "Entrega manual"));
    const footer = element("div", "service-footer");
    const price = element("div", "");
    price.append(
      element("strong", "", s.unitPriceLabel),
      element(
        "small",
        "",
        s.kind === "package"
          ? "por assinatura / pacote"
          : `por unidade · mín. ${number(s.minimum)}`,
      ),
    );
    const cta = element("span", "service-action", "Ver opções");
    cta.append(icon("arrow"));
    footer.append(price, cta);
    card.append(footer);
    list.append(card);
  }
}
function selectService(s) {
  state.service = s;
  state.quote = null;
  $("selectedLogo").replaceChildren(logo(s.platform, s.brand));
  $("selectedBadge").textContent = `${s.platform} · ${s.id}`;
  $("selectedName").textContent = s.displayName;
  $("selectedSummary").textContent = s.summary;
  $("selectedDescription").replaceChildren(
    ...s.details
      .split(/\n+/)
      .filter(Boolean)
      .map((text) => element("p", "", text)),
  );
  $("selectedDescription").closest("details").open = s.details.length < 500;
  $("productWarning").textContent = s.warning;
  $("productWarning").classList.toggle("hidden", !s.warning);
  const chips = $("selectedChips");
  chips.replaceChildren();
  if (s.kind !== "package") {
    chips.append(
      element(
        "span",
        "chip",
        `Mín. ${number(s.minimum)} · Máx. ${number(s.maximum)}`,
      ),
    );
    if (s.refill !== null)
      chips.append(
        element(
          "span",
          "chip",
          s.refill ? "Reposição: consulte condições" : "Sem reposição pela API",
        ),
      );
  }
  if (s.manualDelivery)
    chips.append(element("span", "chip warning", "Entrega manual"));
  $("targetLabel").textContent = s.targetLabel;
  $("targetHint").textContent = s.targetHint;
  $("target").value =
    s.kind === "package" && state.bootstrap.user.username
      ? `@${state.bootstrap.user.username}`
      : "";
  $("answer").value = "";
  $("valueField").classList.toggle("hidden", s.kind === "package");
  $("answerField").classList.toggle("hidden", s.kind !== "poll");
  const control = element(
    s.kind === "custom comments" ? "textarea" : "input",
    "",
  );
  control.id = "value";
  control.maxLength = s.kind === "custom comments" ? 3500 : 13;
  if (s.kind !== "custom comments") control.inputMode = "numeric";
  control.value = s.kind === "custom comments" ? "" : String(s.minimum);
  control.addEventListener("input", updatePrice);
  $("valueControl").replaceChildren(control);
  $("valueLabel").textContent =
    s.kind === "custom comments" ? "Seus comentários" : "Quantidade";
  $("valueHint").textContent =
    s.kind === "custom comments"
      ? `Escreva um comentário por linha. De ${number(s.minimum)} a ${number(s.maximum)} comentários.`
      : `De ${number(s.minimum)} a ${number(s.maximum)} unidades. Use apenas números.`;
  $("quantityChips").replaceChildren();
  if (!["package", "custom comments"].includes(s.kind)) {
    [...new Set([s.minimum, 100, 500, 1000, 5000])]
      .filter((n) => n >= s.minimum && n <= s.maximum)
      .sort((a, b) => a - b)
      .slice(0, 5)
      .forEach((n) => {
        const b = action("", () => {
          control.value = String(n);
          updatePrice();
        });
        b.dataset.quantity = String(n);
        b.textContent = number(n);
        $("quantityChips").append(b);
      });
  }
  $("selectedRate").textContent =
    `${s.unitPriceLabel} ${s.kind === "package" ? "por pacote" : "por unidade"}`;
  updatePrice();
  show("order");
}
// Exact decimal arithmetic, with the same ceiling-to-cent rule as the server.
function priceCents(rate, quantity, packagePrice = false) {
  const [whole, fraction = ""] = String(rate).split(".");
  const scale = 10n ** BigInt(fraction.length);
  const raw =
    BigInt(whole + fraction) * BigInt(packagePrice ? 1 : quantity) * 100n;
  const divisor = scale * (packagePrice ? 1n : 1000n);
  return Number((raw + divisor - 1n) / divisor);
}
function quantity() {
  const s = state.service;
  if (s.kind === "package") return 1;
  const raw = $("value").value.trim();
  if (s.kind === "custom comments")
    return raw.split("\n").filter((x) => x.trim()).length;
  return /^[0-9]{1,13}$/.test(raw) ? Number(raw) : NaN;
}
function updatePrice() {
  const s = state.service;
  const q = quantity();
  const valid =
    Number.isSafeInteger(q) &&
    q > 0 &&
    (s.kind === "package" || (q >= s.minimum && q <= s.maximum));
  $("quantityError").textContent = valid
    ? ""
    : `Informe ${s.kind === "custom comments" ? "de" : "uma quantidade inteira de"} ${number(s.minimum)} a ${number(s.maximum)}.`;
  $("livePrice").textContent = valid
    ? formatMoney(priceCents(s.retailRate, q, s.kind === "package") / 100)
    : "—";
  $("reviewButton").disabled = !valid;
  document
    .querySelectorAll("[data-quantity]")
    .forEach((el) =>
      el.classList.toggle("selected", Number(el.dataset.quantity) === q),
    );
  return valid;
}
async function review(event) {
  event.preventDefault();
  if (!updatePrice()) return;
  if (!$("target").value.trim()) {
    $("target").focus();
    toast("Informe o destino do pedido.");
    return;
  }
  const button = $("reviewButton");
  busy(button, true);
  try {
    const quote = await api("/api/quote", {
      method: "POST",
      body: JSON.stringify({
        service_id: state.service.id,
        target: $("target").value,
        value: state.service.kind === "package" ? null : $("value").value,
        answer: state.service.kind === "poll" ? $("answer").value : null,
      }),
    });
    state.quote = quote;
    updateBalance(quote);
    $("reviewService").textContent = state.service.displayName;
    $("reviewTarget").textContent = $("target").value.trim();
    $("reviewQuantity").textContent =
      state.service.kind === "package" ? "1 pacote" : number(quantity());
    $("reviewPrice").textContent = quote.costLabel;
    const after =
      Math.round(Number(quote.balance) * 100) -
      Math.round(Number(quote.cost) * 100);
    $("reviewBalance").textContent =
      after < 0 ? "Saldo insuficiente" : formatMoney(after / 100);
    const insufficient = after < 0;
    $("reviewWarning").textContent = insufficient
      ? `Adicione pelo menos ${formatMoney(-after / 100)} ao saldo para este pedido. As recargas começam em R$ 20.`
      : state.service.manualDelivery
        ? "Este serviço tem entrega manual. O acesso não é liberado automaticamente ao confirmar."
        : "O pedido entra em processamento após a confirmação. Consulte o prazo e as condições na descrição do serviço.";
    $("reviewWarning").classList.toggle("hidden", false);
    $("confirmButton").classList.toggle("hidden", insufficient);
    $("modalDeposit").classList.toggle("hidden", !insufficient);
    $("confirmButton").disabled = insufficient;
    $("reviewModal").showModal();
    tg?.HapticFeedback?.impactOccurred("light");
  } catch (error) {
    toast(error.message);
  } finally {
    busy(button, false);
  }
}
async function confirmOrder() {
  if (state.confirming || !state.quote) return;
  state.confirming = true;
  busy($("confirmButton"), true);
  document
    .querySelectorAll("[data-close-modal]")
    .forEach((el) => (el.disabled = true));
  try {
    const result = await api(`/api/orders/${state.quote.id}/confirm`, {
      method: "POST",
      body: "{}",
    });
    updateBalance(result);
    if (
      ![
        "SUBMITTED",
        "UNKNOWN",
        "SENDING",
        "QUEUED",
        "MANUAL",
        "COMPLETED",
      ].includes(result.state)
    )
      throw new Error(
        "Não foi possível enviar este pedido. Confira o saldo e os dados antes de tentar novamente.",
      );
    const checking = result.state === "UNKNOWN";
    $("successTitle").textContent =
      result.state === "COMPLETED"
        ? "Pedido concluído"
        : checking
          ? "Pedido em verificação"
          : "Pedido recebido";
    $("successText").textContent =
      `Pedido ${result.id}. ${result.state === "COMPLETED" ? "A entrega foi concluída. Consulte os detalhes em Meus pedidos." : checking ? "Estamos verificando a confirmação. Não faça outro pedido para o mesmo destino." : "Seu pedido está em processamento. A entrega segue o prazo e as condições da descrição. Acompanhe as atualizações em Meus pedidos."}`;
    $("reviewModal").close();
    state.quote = null;
    show("success");
    tg?.HapticFeedback?.notificationOccurred("success");
  } catch (error) {
    toast(
      error.message +
        " Em caso de conexão interrompida, consulte Meus pedidos antes de repetir.",
    );
  } finally {
    state.confirming = false;
    busy($("confirmButton"), false);
    document
      .querySelectorAll("[data-close-modal]")
      .forEach((el) => (el.disabled = false));
  }
}
async function loadWallet() {
  show("wallet");
  $("ledgerList").replaceChildren(
    element("div", "loading-inline", "Atualizando carteira…"),
  );
  busy($("refreshWallet"), true);
  try {
    const data = await api("/api/account");
    updateBalance(data);
    const list = $("ledgerList");
    list.replaceChildren();
    if (!data.movements.length)
      empty(list, "Sua carteira ainda não tem movimentações.", "wallet");
    for (const row of data.movements) {
      const el = element("div", "activity-row");
      const copy = element("div", "");
      copy.append(
        element("p", "", row.label),
        element("small", "", date(row.createdAt)),
      );
      el.append(
        icon(row.amountCents > 0 ? "plus" : "receipt", "family-icon"),
        copy,
        element(
          "strong",
          row.amountCents > 0 ? "positive" : "",
          row.amountLabel,
        ),
      );
      list.append(el);
    }
  } catch (error) {
    failure($("ledgerList"), error, loadWallet);
  } finally {
    busy($("refreshWallet"), false);
  }
}
function statusLabel(row) {
  const statuses = {
    pending: "Pendente",
    processing: "Processando",
    "in progress": "Em andamento",
    completed: "Concluído",
    partial: "Entrega parcial",
    canceled: "Cancelado",
    cancelled: "Cancelado",
    refunded: "Reembolsado",
    failed: "Falhou",
    awaiting: "Aguardando atualização",
  };
  const local = {
    QUEUED: "Em processamento",
    MANUAL: "Em processamento",
    COMPLETED: "Concluído",
    SENDING: "Enviando",
    UNKNOWN: "Em verificação",
    REJECTED: "Não realizado",
    EXPIRED: "Expirado",
  };
  return (
    local[row.state] ||
    statuses[row.status.toLowerCase()] ||
    "Aguardando atualização"
  );
}
async function loadOrders(more = false) {
  if (state.ordersLoading) return;
  state.ordersLoading = true;
  show("orders");
  busy($("refreshOrders"), true);
  busy($("moreOrders"), true);
  if (!more) {
    state.ordersPage = 0;
    $("ordersList").replaceChildren(
      element("div", "loading-inline", "Carregando pedidos…"),
    );
    $("moreOrders").classList.add("hidden");
  }
  try {
    const page = more ? state.ordersPage + 1 : 0;
    const data = await api(`/api/orders?page=${page}`);
    state.ordersPage = page;
    $("ordersCount").textContent =
      `${data.total} ${data.total === 1 ? "pedido" : "pedidos"}`;
    if (!more) $("ordersList").replaceChildren();
    if (!data.orders.length && !more)
      empty($("ordersList"), "Seus pedidos aparecem aqui após a confirmação.");
    for (const row of data.orders) {
      const card = element("article", "service-card order-card");
      const top = element("div", "service-top");
      const status = statusLabel(row);
      top.append(
        element("span", "service-code", `#${row.id.slice(0, 8)}`),
        element(
          "span",
          `status ${status === "Concluído" ? "complete" : ["Em verificação", "Não realizado", "Entrega parcial"].includes(status) ? "attention" : ""}`,
          status,
        ),
      );
      const bottom = element("div", "order-bottom");
      bottom.append(
        element("small", "", date(row.createdAt)),
        element("strong", "", row.costLabel),
      );
      card.append(
        top,
        element("h3", "", row.serviceName),
        element("p", "order-target", row.target),
        bottom,
      );
      const detail = action("text-button", () => openOrderDetail(row.id));
      detail.textContent = "Ver detalhes do pedido";
      card.append(detail);
      $("ordersList").append(card);
    }
    $("moreOrders").classList.toggle("hidden", !data.hasMore);
  } catch (error) {
    if (more) toast(error.message);
    else failure($("ordersList"), error, () => loadOrders());
  } finally {
    state.ordersLoading = false;
    busy($("refreshOrders"), false);
    busy($("moreOrders"), false);
  }
}
function navigate(id) {
  if (!state.bootstrap) return;
  if (id === "wallet") loadWallet();
  else if (id === "orders") loadOrders();
  else show(id);
}
async function boot() {
  $("loading").classList.remove("hidden");
  $("authError").classList.add("hidden");
  try {
    state.bootstrap = await api("/api/bootstrap");
    updateBalance(state.bootstrap);
    $("catalogSummary").textContent =
      `${state.bootstrap.serviceCount} serviços`;
    renderPlatforms();
    $("app").classList.remove("hidden");
    $("bottomNav").classList.remove("hidden");
    window.storeOperations?.boot();
    window.storefront?.boot();
    const requested = new URLSearchParams(location.search).get("platform");
    if (
      requested &&
      state.bootstrap.platforms.some((p) => p.name === requested)
    )
      await selectPlatform(requested);
  } catch (error) {
    $("errorTitle").textContent = initData
      ? "Não foi possível abrir a loja"
      : "Abra pelo Telegram";
    $("errorText").textContent = error.message;
    $("authError").classList.remove("hidden");
  } finally {
    $("loading").classList.add("hidden");
  }
}
document
  .querySelectorAll("[data-nav]")
  .forEach((el) =>
    el.addEventListener("click", () => navigate(el.dataset.nav)),
  );
document
  .querySelectorAll("[data-back]")
  .forEach((el) =>
    el.addEventListener("click", () => navigate(el.dataset.back)),
  );
document.querySelectorAll("[data-close-modal]").forEach((el) =>
  el.addEventListener("click", () => {
    if (!state.confirming) $("reviewModal").close();
  }),
);
$("reviewModal").addEventListener("cancel", (event) => {
  if (state.confirming) event.preventDefault();
});
$("brandHome").addEventListener("click", () => navigate("platforms"));
$("balanceButton").addEventListener("click", () => navigate("wallet"));
$("serviceSearch").addEventListener("input", renderServices);
$("serviceSort").addEventListener("change", renderServices);
$("orderForm").addEventListener("submit", review);
$("confirmButton").addEventListener("click", confirmOrder);
$("depositButton").addEventListener("click", () => openDeposit());
$("modalDeposit").addEventListener("click", () => {
  $("reviewModal").close();
  openDeposit();
});
$("openBotHelp").addEventListener("click", (event) => {
  if (tg?.openTelegramLink) {
    event.preventDefault();
    tg.openTelegramLink("https://t.me/suportemaispopular");
  }
});
// Fallback for older Telegram WebViews without named-details support.
document.querySelectorAll(".faq details").forEach((detail) => {
  detail.addEventListener("toggle", () => {
    if (!detail.open) return;
    document.querySelectorAll(".faq details").forEach((other) => {
      if (other !== detail) other.open = false;
    });
  });
});
$("refreshWallet").addEventListener("click", loadWallet);
$("refreshOrders").addEventListener("click", () => loadOrders());
$("moreOrders").addEventListener("click", () => loadOrders(true));
$("newOrder").addEventListener("click", () => show("platforms"));
$("viewOrders").addEventListener("click", () => loadOrders());
$("retryBoot").addEventListener("click", boot);
if (tg) {
  tg.ready();
  tg.expand();
  if (initData && tg.isVersionAtLeast?.("6.1")) {
    tg.BackButton?.onClick(goBack);
  }
}
boot();
