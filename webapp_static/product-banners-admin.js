"use strict";
(() => {
  let items = [],
    selected = null,
    image = "",
    localUrl = "";
  let locked = false,
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
  function decoratedBanner() {
    return {
      ...selected.banner,
      custom: Boolean(localUrl || selected.banner.custom),
      url: localUrl || selected.banner.url,
      fit: $("productBannerFit").value,
      position: $("productBannerPosition").value,
    };
  }
  function defaultArt(item) {
    const art = element("div", "product-art");
    art.append(
      logo(
        item.editorType === "platform" ? item.name : item.platform,
        item.brand,
      ),
      element("strong", "", item.displayName),
    );
    return art;
  }
  function preview() {
    if (!selected) return;
    const item = { ...selected, banner: decoratedBanner() };
    const art =
      (item.editorType === "platform"
        ? customPlatformArt(item)
        : customProductArt(item)) || defaultArt(item);
    const copy = element("div", "product-copy");
    if (item.editorType === "platform") {
      copy.append(
        element("h3", "", item.displayName),
        element("p", "", item.summary),
        element("small", "social-from", "A partir de"),
        element("strong", "product-price", item.fromPriceLabel),
        element(
          "small",
          "",
          item.fromKind === "package"
            ? "por pacote"
            : `por unidade · mín. ${number(item.fromMinimum)}`,
        ),
        element("span", "product-cta", "Ver categorias →"),
      );
    } else {
      copy.append(
        element("h3", "", item.displayName),
        element("p", "", item.summary),
        element("strong", "product-price", item.unitPriceLabel),
        element(
          "small",
          "",
          item.kind === "package"
            ? "por assinatura / pacote"
            : `por unidade · mín. ${number(item.minimum)}`,
        ),
        element("span", "product-cta", "Ver detalhes →"),
      );
    }
    $("productBannerPreview").replaceChildren(art, copy);
  }
  function choose(item, scroll = true) {
    if (locked || reading) return;
    selected = item;
    image = "";
    localUrl = "";
    request++;
    $("productBannerFile").value = "";
    $("productBannerName").textContent = item.displayName;
    $("productBannerCode").textContent =
      item.editorType === "platform"
        ? "Redes sociais · banner geral do catálogo"
        : `${item.platform} · Cód. ${item.id}`;
    $("productBannerFit").value = item.banner.fit;
    $("productBannerPosition").value = item.banner.position;
    $("productBannerError").textContent = "";
    $("productBannerForm").classList.remove("hidden");
    preview();
    render();
    if (scroll) $("productBannerForm").scrollIntoView({ block: "start" });
  }
  function render() {
    const term = normalize($("productBannerSearch").value);
    const section = $("productBannerPlatform").value;
    const rows = items.filter(
      (item) =>
        (!section || item.editorType === section) &&
        normalize(`${item.id || ""} ${item.name} ${item.displayName}`).includes(
          term,
        ),
    );
    $("productBannerCount").textContent =
      `${rows.length} ${rows.length === 1 ? "card encontrado" : "cards encontrados"}`;
    $("productBannerList").replaceChildren(
      ...rows.slice(0, limit).map((item) => {
        const button = action("product-banner-option", () => choose(item));
        button.setAttribute(
          "aria-pressed",
          String(selected?.editorKey === item.editorKey),
        );
        const copy = element("span", "");
        copy.append(
          element("strong", "", item.displayName),
          element(
            "small",
            "",
            `${item.editorType === "platform" ? "Banner geral da rede" : `Cód. ${item.id}`} · ${item.banner.custom ? "Imagem personalizada" : "Arte original"}`,
          ),
        );
        button.append(
          logo(
            item.editorType === "platform" ? item.name : item.platform,
            item.brand,
          ),
          copy,
        );
        return button;
      }),
    );
    $("moreProductBanners").classList.toggle("hidden", rows.length <= limit);
  }
  function buildItems(data) {
    const platformItems = data.platforms.map((entry) => {
      const visible = state.bootstrap.platforms.find(
        (p) => p.name === entry.name,
      );
      return {
        ...visible,
        ...entry,
        editorType: "platform",
        editorKey: `platform:${entry.name}`,
        displayName: entry.name,
      };
    });
    const serviceItems = data.services.map((service) => ({
      ...service,
      editorType: "service",
      editorKey: `service:${service.id}`,
    }));
    return [...platformItems, ...serviceItems];
  }
  async function load() {
    if (locked || reading || !state.bootstrap?.isAdmin) return;
    show("productBannersAdmin");
    locked = true;
    disable(true);
    try {
      const previous = selected?.editorKey;
      items = buildItems(await api("/api/admin/product-banners"));
      $("productBannerPlatform").replaceChildren(
        new Option("Redes sociais — banner geral", "platform"),
        new Option("Streaming e apps — por produto", "service"),
        new Option("Todos os cards", ""),
      );
      if (
        !["platform", "service", ""].includes($("productBannerPlatform").value)
      )
        $("productBannerPlatform").value = "platform";
      const updated = items.find((item) => item.editorKey === previous);
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
    localUrl = "";
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
      localUrl = data;
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
        "Escolha uma imagem para este card.";
      return;
    }
    locked = true;
    disable(true);
    try {
      const subject =
        selected.editorType === "platform"
          ? `a rede ${selected.displayName}`
          : `o produto ${selected.displayName}`;
      if (
        !(await confirmOperation(
          reset ? "Restaurar arte original?" : "Publicar imagem do card?",
          `Somente ${subject} será alterado.`,
        ))
      )
        return;
      const payload = {
        identity: selected.banner.identity,
        revision: selected.banner.revision,
        fit: $("productBannerFit").value,
        position: $("productBannerPosition").value,
        image: reset ? "" : image,
        reset,
      };
      const result =
        selected.editorType === "platform"
          ? await post("/api/admin/platform-banners", {
              ...payload,
              platform: selected.name,
            })
          : await post(`/api/admin/product-banners/${selected.id}`, payload);
      selected.banner = result;
      locked = false;
      choose(selected, false);
      locked = true;
      await window.storefront.refresh();
      toast(reset ? "Arte original restaurada." : "Imagem do card publicada.");
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
