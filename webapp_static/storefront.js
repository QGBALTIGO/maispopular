"use strict";
(() => {
  let booted = false,
    current = 0,
    timer;
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  let paused = motion.matches;
  const slides = [
    [
      "social.png",
      "Impulsione suas redes sociais",
      "Seguidores, curtidas e visualizações. Explore os serviços.",
      "#socialSection",
    ],
    [
      "services.png",
      "Mais opções para o seu dia",
      "Assinaturas, ferramentas e serviços digitais em um só lugar.",
      "#streamingSection",
    ],
    [
      "support.png",
      "Conte com nosso atendimento",
      "Dúvidas sobre pedidos ou saldo? Fale com a equipe.",
      "https://t.me/suportemaispopular",
    ],
  ];
  function switchSlide(index) {
    current = (index + slides.length) % slides.length;
    [...$("heroSlides").children].forEach((slide, i) =>
      slide.classList.toggle("hidden", i !== current),
    );
    [...$("heroDots").children].forEach((dot, i) =>
      dot.setAttribute("aria-pressed", String(i === current)),
    );
  }
  function schedule() {
    clearTimeout(timer);
    if (paused) return;
    timer = setTimeout(() => {
      if (
        !document.hidden &&
        state.view === "platforms" &&
        !$("heroSlides").matches(":hover") &&
        !document.activeElement?.closest(".shop-hero")
      )
        switchSlide(current + 1);
      schedule();
    }, 6500);
  }
  function pause(value) {
    paused = value;
    $("heroPause").textContent = paused ? "Reproduzir" : "Pausar";
    $("heroPause").setAttribute(
      "aria-label",
      paused ? "Reproduzir banners" : "Pausar banners",
    );
    schedule();
  }
  function carousel() {
    $("platforms").addEventListener("click", (event) => {
      const link = event.target.closest('a[href^="#"]');
      if (!link) return;
      const target = document.getElementById(
        link.getAttribute("href").slice(1),
      );
      if (target) {
        event.preventDefault();
        target.scrollIntoView({
          behavior: motion.matches ? "instant" : "smooth",
          block: "start",
        });
      }
    });
    slides.forEach(([file, title, text, destination], index) => {
      const slide = element("a", "hero-slide");
      slide.href = destination;
      if (destination.startsWith("https:")) {
        slide.target = "_blank";
        slide.rel = "noopener noreferrer";
      }
      const img = element("img", "");
      img.src = `/assets/banners/${file}`;
      img.width = 2011;
      img.height = 782;
      img.alt = title;
      img.loading = index ? "lazy" : "eager";
      img.decoding = "async";
      if (!index) img.fetchPriority = "high";
      const caption = element("div", "hero-caption");
      caption.append(
        element("strong", "", title),
        element("span", "", text),
        element("b", "", "Explorar ↗"),
      );
      slide.append(img, caption);
      $("heroSlides").append(slide);
      const dot = action("hero-dot", () => {
        switchSlide(index);
        pause(true);
      });
      dot.setAttribute("aria-label", `Banner ${index + 1}: ${title}`);
      $("heroDots").append(dot);
    });
    switchSlide(0);
    pause(paused);
    $("heroPause").addEventListener("click", () => pause(!paused));
    motion.addEventListener("change", (event) => {
      if (event.matches) pause(true);
    });
    let touchStart;
    $("heroSlides").addEventListener(
      "touchstart",
      (e) => {
        touchStart = e.changedTouches[0].clientX;
      },
      { passive: true },
    );
    $("heroSlides").addEventListener(
      "touchend",
      (e) => {
        const distance = e.changedTouches[0].clientX - touchStart;
        if (Math.abs(distance) > 60) {
          switchSlide(current + (distance < 0 ? 1 : -1));
          pause(true);
        }
      },
      { passive: true },
    );
  }
  const titles = {
    netflix: "Netflix",
    disneyplus: "Disney+",
    primevideo: "Prime Video",
    hbo: "HBO Max",
    globoplay: "Globoplay",
    openai: "ChatGPT Plus",
    canva: "Canva Pro",
    capcut: "CapCut Premium",
    nordvpn: "NordVPN",
    brainly: "Brainly Plus",
    qconcursos: "Qconcursos",
    youtube: "YouTube Premium",
    crunchyroll: "Crunchyroll",
    paramountplus: "Paramount+",
    rakutenviki: "Rakuten Viki",
    premiere: "Premiere",
    duolingo: "Super Duolingo",
    xbox: "Xbox Game Pass",
  };
  async function products() {
    if (!state.bootstrap.platforms.some((p) => p.name === "Streaming e Apps")) {
      empty($("streamingProducts"), "Novas assinaturas em breve.");
      empty($("toolProducts"), "Novas ferramentas em breve.");
      return;
    }
    try {
      const catalog = await api(
        "/api/catalog?platform=" + encodeURIComponent("Streaming e Apps"),
      );
      $("streamingProducts").replaceChildren();
      $("toolProducts").replaceChildren();
      const priority = [
        "netflix",
        "disneyplus",
        "hbo",
        "primevideo",
        "globoplay",
        "crunchyroll",
        "youtube",
        "paramountplus",
        "premiere",
        "rakutenviki",
        "canva",
        "openai",
        "capcut",
        "nordvpn",
        "brainly",
        "qconcursos",
        "duolingo",
        "xbox",
      ];
      const ordered = [...catalog.services].sort(
        (a, b) =>
          (priority.indexOf(a.brand) < 0 ? 999 : priority.indexOf(a.brand)) -
            (priority.indexOf(b.brand) < 0 ? 999 : priority.indexOf(b.brand)) ||
          a.displayName.length - b.displayName.length,
      );
      for (const service of ordered) {
        const card = action(
          `shop-product product-${service.brand || "generic"}`,
          () => {
            ++state.catalogRequest;
            state.platform = catalog.platform;
            state.catalog = catalog;
            $("familyPlatform").textContent = catalog.platform;
            $("familyLogo").replaceChildren(logo(catalog.platform));
            renderFamilies();
            selectFamily(service.family);
            selectService(service);
          },
        );
        const art = element("div", "product-art");
        art.append(
          logo(service.platform, service.brand),
          element("strong", "", titles[service.brand] || service.displayName),
        );
        const body = element("div", "product-copy");
        body.append(
          element("h3", "", service.displayName),
          element("p", "", service.summary),
          element("strong", "product-price", service.rateLabel),
          element(
            "small",
            "",
            service.kind === "package"
              ? "por assinatura / pacote"
              : "a cada 1.000 unidades",
          ),
          element("span", "product-cta", "Ver detalhes →"),
        );
        card.append(art, body);
        const isTool = [
          "openai",
          "canva",
          "capcut",
          "nordvpn",
          "brainly",
          "qconcursos",
          "duolingo",
          "xbox",
        ].includes(service.brand);
        $(isTool ? "toolProducts" : "streamingProducts").append(card);
      }
      $("subscriptionEntry").classList.add("hidden");
    } catch (error) {
      failure($("streamingProducts"), error, products);
      empty(
        $("toolProducts"),
        "Atualize as assinaturas para carregar os apps.",
      );
    }
  }
  window.storefront = {
    boot() {
      if (booted) return;
      booted = true;
      carousel();
      products();
    },
  };
  if (state.bootstrap) window.storefront.boot();
})();
