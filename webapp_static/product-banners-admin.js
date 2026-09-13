"use strict";
(() => {
  let products = [],
    selected = null,
    image = "",
    locked = false,
    reading = false,
    request = 0,
    limit = 20;
  const controls = [
    "productBannerSearch",
    "productBannerPlatform",
    "productBannerFile",
    "productBannerFit",
    "productBannerPosition",
    "saveProductBanner",
    "restoreProductBanner",
    "refreshProductBanners",
    "moreProductBanners",
  ];
  function disable(value) {
    controls.forEach((id) => ($(id).disabled = value));
  }
  function preview() {
    if (!selected) return;
    const service = {
      ...selected,
      banner: {
        ...selected.banner,
        fit: $("productBannerFit").value,
        position: $("productBannerPosition").value,
      },
    };
    if (image)
      service.banner = {
        ...service.banner,
        custom: true,
        url: `data:image/${$("productBannerFile").files[0].type.split("/")[1]};base64,${image}`,
      };
    const art = customProductArt(service) || element("div", "product-art");
    if (!service.banner.custom)
      art.append(
        logo(service.platform, service.brand),
        element("strong", "", service.displayName),
      );
    const copy = element("div", "product-copy");
    copy.append(
      element("h3", "", service.displayName),
      element("p", "", service.summary),
      element("strong", "product-price", service.unitPriceLabel),
      element("span", "product-cta", "Ver detalhes →"),
    );
    $("productBannerPreview").replaceChildren(art, copy);
  }
  function choose(service, scroll = true) {
    if (locked || reading) return;
    selected = service;
    image = "";
    request++;
    $("productBannerFile").value = "";
    $("productBannerName").textContent = service.displayName;
    $("productBannerCode").textContent =
      `${service.platform} · Cód. ${service.id}`;
    $("productBannerFit").value = service.banner.fit;
    $("productBannerPosition").value = service.banner.position;
    $("productBannerError").textContent = "";
    $("productBannerForm").classList.remove("hidden");
    preview();
    render();
    if (scroll) $("productBannerForm").scrollIntoView({ block: "start" });
  }
  function render() {
    const term = normalize($("productBannerSearch").value);
    const platform = $("productBannerPlatform").value;
    const rows = products.filter(
      (s) =>
        (!platform || s.platform === platform) &&
        normalize(`${s.id} ${s.name} ${s.displayName}`).includes(term),
    );
    $("productBannerCount").textContent = `${rows.length} produtos encontrados`;
    $("productBannerList").replaceChildren(
      ...rows.slice(0, limit).map((s) => {
        const button = action("product-banner-option", () => choose(s));
        button.setAttribute("aria-pressed", String(selected?.id === s.id));
        const text = element("span", "");
        text.append(
          element("strong", "", s.displayName),
          element(
            "small",
            "",
            `Cód. ${s.id} · ${s.banner.custom ? "Imagem personalizada" : "Arte original"}`,
          ),
        );
        button.append(logo(s.platform, s.brand), text);
        return button;
      }),
    );
    $("moreProductBanners").classList.toggle("hidden", rows.length <= limit);
  }
  async function load() {
    if (locked || reading || !state.bootstrap?.isAdmin) return;
    show("productBannersAdmin");
    locked = true;
    disable(true);
    try {
      const data = await api("/api/admin/product-banners");
      products = data.services.sort((a, b) =>
        a.displayName.localeCompare(b.displayName, "pt-BR"),
      );
      const current = $("productBannerPlatform").value;
      const platforms = [...new Set(products.map((s) => s.platform))].sort();
      $("productBannerPlatform").replaceChildren(
        new Option("Todos os produtos", ""),
        ...platforms.map((p) => new Option(p, p)),
      );
      $("productBannerPlatform").value =
        current || (selected ? "" : "Streaming e Apps");
      if (!platforms.includes($("productBannerPlatform").value))
        $("productBannerPlatform").value = "";
      const updated = products.find((s) => s.id === selected?.id);
      locked = false;
      if (updated) choose(updated, false);
      else {
        selected = null;
        $("productBannerForm").classList.add("hidden");
        render();
      }
      $("productBannerError").textContent = "";
    } catch (error) {
      $("productBannerError").textContent = error.message;
    } finally {
      locked = false;
      disable(false);
    }
  }
  $("productBannerFile").addEventListener("change", async () => {
    const version = ++request;
    image = "";
    const file = $("productBannerFile").files[0];
    preview();
    if (!file) return;
    if (
      file.size > 4 * 1024 * 1024 ||
      !["image/png", "image/jpeg", "image/webp"].includes(file.type)
    ) {
      $("productBannerError").textContent =
        "Escolha PNG, JPG ou WebP de até 4 MB.";
      $("productBannerFile").value = "";
      return;
    }
    reading = true;
    disable(true);
    try {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(Error("Não foi possível ler a imagem."));
        reader.readAsDataURL(file);
      });
      if (version !== request) return;
      image = data.split(",")[1];
      preview();
      $("productBannerError").textContent = "";
    } catch (error) {
      $("productBannerError").textContent = error.message;
    } finally {
      reading = false;
      disable(false);
    }
  });
  async function save(reset = false) {
    if (locked || reading || !selected) return;
    if (!reset && !image && !selected.banner.custom) {
      $("productBannerError").textContent =
        "Escolha uma imagem para este produto.";
      return;
    }
    locked = true;
    disable(true);
    try {
      if (
        !(await confirmOperation(
          reset ? "Restaurar arte original?" : "Publicar imagem do produto?",
          `${selected.displayName} · Cód. ${selected.id}. Somente a imagem deste produto será alterada.`,
        ))
      )
        return;
      const result = await post(`/api/admin/product-banners/${selected.id}`, {
        identity: selected.banner.identity,
        revision: selected.banner.revision,
        fit: $("productBannerFit").value,
        position: $("productBannerPosition").value,
        image: reset ? "" : image,
        reset,
      });
      selected.banner = result;
      if (state.catalog) {
        const cached = state.catalog.services.find((s) => s.id === selected.id);
        if (cached) cached.banner = result;
      }
      locked = false;
      choose(selected, false);
      locked = true;
      toast(
        reset ? "Arte original restaurada." : "Imagem do produto publicada.",
      );
      try {
        await window.storefront.refresh();
      } catch (_) {
        toast("Imagem salva. Reabra o catálogo para atualizar a vitrine.");
      }
    } catch (error) {
      $("productBannerError").textContent = error.message;
    } finally {
      locked = false;
      disable(false);
    }
  }
  $("manageProductBanners").addEventListener("click", load);
  $("backProductBanners").addEventListener("click", loadAdmin);
  $("refreshProductBanners").addEventListener("click", load);
  ["productBannerSearch", "productBannerPlatform"].forEach((id) =>
    $(id).addEventListener(id.endsWith("Search") ? "input" : "change", () => {
      limit = 20;
      render();
    }),
  );
  $("moreProductBanners").addEventListener("click", () => {
    limit += 20;
    render();
  });
  ["productBannerFit", "productBannerPosition"].forEach((id) =>
    $(id).addEventListener("change", preview),
  );
  $("productBannerForm").addEventListener("submit", (event) => {
    event.preventDefault();
    save();
  });
  $("restoreProductBanner").addEventListener("click", () => save(true));
})();
