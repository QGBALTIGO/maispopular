"use strict";
(() => {
  const navigate = (view) => {
    if (view === "wallet") loadWallet();
    else if (view === "orders") loadOrders();
    else if (view === "affiliate") loadAffiliate();
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
  $("menuAdmin").addEventListener("click", () => {
    $("shopMenu").close();
    loadAdmin();
  });
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
})();
