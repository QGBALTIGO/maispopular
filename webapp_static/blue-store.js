"use strict";
(() => {
  const navigate = (view) => {
    if (view === "wallet") loadWallet();
    else if (view === "orders") loadOrders();
    else show(view);
  };
  $("openShopMenu").addEventListener("click", () => {
    if (!state.bootstrap) return toast("Abra a loja pelo Telegram.");
    $("menuAdmin").classList.toggle("hidden", !state.bootstrap.isAdmin);
    $("shopMenu").showModal();
  });
  $("closeShopMenu").addEventListener("click", () => $("shopMenu").close());
  document.querySelectorAll("[data-shop-nav]").forEach((button) =>
    button.addEventListener("click", () => {
      $("shopMenu").close();
      navigate(button.dataset.shopNav);
    }),
  );
  $("menuReviews").addEventListener("click", () => {
    $("shopMenu").close();
    show("platforms");
    $("reviewsSection").scrollIntoView();
  });
  $("menuAdmin").addEventListener("click", () => {
    $("shopMenu").close();
    loadAdmin();
  });
  $("heroDeposit").addEventListener("click", () => loadWallet());
  $("shopSearch").addEventListener("click", () => {
    if (!state.bootstrap) return toast("Abra a loja pelo Telegram.");
    $("globalSearch").showModal();
    $("globalSearchInput").focus();
  });
  $("closeGlobalSearch").addEventListener("click", () =>
    $("globalSearch").close(),
  );
  let timer,
    request = 0;
  $("globalSearchInput").addEventListener("input", () => {
    clearTimeout(timer);
    const sequence = ++request;
    const term = $("globalSearchInput").value.trim();
    $("globalSearchResults").replaceChildren();
    $("globalSearchStatus").textContent =
      term.length < 2 ? "Digite pelo menos 2 caracteres." : "Buscando…";
    if (term.length < 2) return;
    timer = setTimeout(async () => {
      try {
        const data = await api(`/api/search?q=${encodeURIComponent(term)}`);
        if (sequence !== request) return;
        $("globalSearchStatus").textContent = data.hasMore
          ? "Primeiros 30 resultados. Refine a busca para encontrar mais."
          : `${data.services.length} resultados encontrados`;
        for (const service of data.services) {
          const card = action("service-card", async () => {
            busy(card, true);
            try {
              await selectPlatform(service.platform);
              if (!state.catalog || state.catalog.platform !== service.platform)
                return;
              selectFamily(service.family);
              selectService(
                state.catalog.services.find((s) => s.id === service.id) ||
                  service,
              );
              $("globalSearch").close();
            } finally {
              busy(card, false);
            }
          });
          card.append(
            element("p", "eyebrow", `${service.platform} · #${service.id}`),
            element("h3", "", service.displayName),
            element("strong", "", service.unitPriceLabel),
            element(
              "small",
              "",
              service.kind === "package"
                ? " por pacote"
                : ` por unidade · mín. ${number(service.minimum)}`,
            ),
          );
          $("globalSearchResults").append(card);
        }
      } catch (error) {
        if (sequence === request)
          $("globalSearchStatus").textContent = error.message;
      }
    }, 300);
  });
  let booted = false;
  function boot() {
    if (booted) return;
    booted = true;
    const picks = [
      ["Instagram", "instagram", "Redes sociais"],
      ["Streaming e Apps", "netflix", "Streaming e apps"],
      ["TikTok", "tiktok", "TikTok"],
      ["Telegram", "telegram", "Telegram"],
      ["Streaming e Apps", "hbo", "HBO Max"],
    ];
    for (const [platform, brand, title] of picks) {
      if (!state.bootstrap.platforms.some((p) => p.name === platform)) continue;
      const card = action(`floating-product floating-${brand}`, () =>
        selectPlatform(platform),
      );
      if (brand === "instagram" || brand === "netflix") {
        const img = element("img", "");
        img.src = `/assets/banners/${brand === "instagram" ? "social-blue-v2.png" : "streaming-blue-v2.png"}`;
        img.alt = "";
        img.width = 1672;
        img.height = 941;
        card.append(img);
      } else {
        const art = element("div", "product-art");
        art.append(logo(platform, brand), element("strong", "", title));
        card.append(art);
      }
      card.append(element("span", "", title));
      $("floatingProducts").append(card);
    }
  }
  window.blueStore = { boot };
  if (state.bootstrap) boot();
})();
