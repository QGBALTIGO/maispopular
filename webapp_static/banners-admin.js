"use strict";
(() => {
  let banners = [],
    selected = 1,
    image = "",
    sending = false,
    fileRequest = 0,
    reviewing = false;
  const inputIds = [
    "bannerFile",
    "bannerTitle",
    "bannerTarget",
    "bannerFit",
    "bannerPosition",
  ];
  function preview() {
    $("bannerPreview").className =
      `fit-${$("bannerFit").value} pos-${$("bannerPosition").value}`;
  }
  function choose(slot) {
    if (sending) return;
    selected = slot;
    image = "";
    fileRequest++;
    $("saveBanner").disabled = false;
    const banner = banners.find((b) => b.slot === slot);
    if (!banner) return;
    $("bannerFile").value = "";
    $("bannerPreview").src = banner.url;
    $("bannerTitle").value = banner.title;
    $("bannerTarget").value = banner.target;
    $("bannerFit").value = banner.fit;
    $("bannerPosition").value = banner.position;
    $("bannerError").textContent = "";
    preview();
    [...$("bannerSlots").children].forEach((b, i) =>
      b.setAttribute("aria-pressed", String(i + 1 === slot)),
    );
  }
  async function load() {
    if (!state.bootstrap?.isAdmin) return;
    show("bannersAdmin");
    try {
      const data = await api("/api/banners");
      banners = data.banners;
      $("bannerSlots").replaceChildren(
        ...banners.map((b) => {
          const button = action("", () => choose(b.slot));
          button.textContent = `Banner ${b.slot}`;
          return button;
        }),
      );
      choose(selected);
    } catch (error) {
      $("bannerError").textContent = error.message;
    }
  }
  $("bannerFile").addEventListener("change", async () => {
    const current = ++fileRequest;
    image = "";
    const file = $("bannerFile").files[0];
    $("bannerPreview").src = banners.find((b) => b.slot === selected).url;
    if (!file) {
      $("bannerPreview").src = banners.find((b) => b.slot === selected).url;
      return;
    }
    if (
      file.size > 4 * 1024 * 1024 ||
      !["image/png", "image/jpeg", "image/webp"].includes(file.type)
    ) {
      $("bannerError").textContent = "Escolha PNG, JPG ou WebP de até 4 MB.";
      $("bannerFile").value = "";
      return;
    }
    $("saveBanner").disabled = true;
    try {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(Error("Não foi possível ler a imagem."));
        reader.readAsDataURL(file);
      });
      if (current !== fileRequest) return;
      image = data.split(",")[1];
      $("bannerPreview").src = data;
      $("bannerError").textContent = "";
    } catch (error) {
      $("bannerError").textContent = error.message;
    } finally {
      if (current === fileRequest) $("saveBanner").disabled = false;
    }
  });
  async function save(reset = false) {
    if (sending || reviewing || !banners.length || $("saveBanner").disabled)
      return;
    if (!reset && !$("bannerForm").reportValidity()) return;
    reviewing = true;
    const approved = await confirmOperation(
      reset ? "Restaurar banner original?" : "Publicar este banner?",
      reset
        ? "A imagem e as opções deste banner voltarão ao original."
        : "A imagem e o enquadramento da prévia serão exibidos aos clientes.",
    );
    reviewing = false;
    if (!approved || sending) return;
    sending = true;
    inputIds.forEach((id) => ($(id).disabled = true));
    busy($("saveBanner"), true);
    try {
      const b = banners.find((b) => b.slot === selected);
      await post(`/api/admin/banners/${selected}`, {
        title: $("bannerTitle").value,
        target: $("bannerTarget").value,
        fit: $("bannerFit").value,
        position: $("bannerPosition").value,
        revision: b.revision,
        image: reset ? "" : image,
        reset,
      });
      sending = false;
      await load();
      await window.storefront.reloadBanners();
      toast(reset ? "Banner original restaurado." : "Banner publicado.");
    } catch (error) {
      $("bannerError").textContent = error.message;
    } finally {
      sending = false;
      inputIds.forEach((id) => ($(id).disabled = false));
      busy($("saveBanner"), false);
    }
  }
  $("manageBanners").addEventListener("click", load);
  $("backBannerAdmin").addEventListener("click", loadAdmin);
  $("bannerFit").addEventListener("change", preview);
  $("bannerPosition").addEventListener("change", preview);
  $("bannerForm").addEventListener("submit", (e) => {
    e.preventDefault();
    save();
  });
  $("restoreBanner").addEventListener("click", () => save(true));
  $("refreshBannersAdmin").addEventListener("click", load);
})();
