"use strict";
(() => {
  let data = null,
    page = 0,
    selected = null,
    saving = false;
  async function load() {
    if (!state.bootstrap?.isAdmin) return;
    show("prices");
    $("priceError").textContent = "";
    try {
      data = await api("/api/admin/prices");
      $("priceMultiplier").value = data.multiplier.replace(".", ",");
      render();
      $("priceAudit").replaceChildren(
        ...data.audit.map((row) =>
          element(
            "p",
            "intro-copy",
            `${date(row.created_at)} · Admin ${row.admin_id} · ${row.service_id ? "Serviço #" + row.service_id : "Regra geral"} · ${row.old_value} → ${row.new_value} · ${row.reason}`,
          ),
        ),
      );
    } catch (error) {
      failure($("priceList"), error, load);
    }
  }
  function render() {
    if (!data) return;
    const query = normalize($("priceSearch").value);
    const rows = data.services.filter((s) =>
      normalize(`${s.id} ${s.name} ${s.platform}`).includes(query),
    );
    page = Math.min(page, Math.max(0, Math.ceil(rows.length / 20) - 1));
    $("priceCount").textContent =
      `${rows.length} serviços · página ${page + 1} de ${Math.max(1, Math.ceil(rows.length / 20))}`;
    $("pricePrevious").disabled = page === 0;
    $("priceNext").disabled = (page + 1) * 20 >= rows.length;
    $("priceList").replaceChildren(
      ...rows.slice(page * 20, (page + 1) * 20).map((s) => {
        const card = action("service-card price-row", () => edit(s));
        card.append(
          element("small", "muted", `${s.platform} · #${s.id}`),
          element("h3", "", s.name),
          element(
            "strong",
            "",
            `${s.unitLabel} ${s.kind === "package" ? "por pacote" : "por unidade"}`,
          ),
          element(
            "span",
            "chip",
            s.custom ? "Preço personalizado" : "Regra geral",
          ),
          element("span", "service-action", "Editar preço →"),
        );
        return card;
      }),
    );
    if (!rows.length)
      empty($("priceList"), "Nenhum serviço encontrado.", "search");
  }
  function edit(service) {
    selected = service;
    $("priceEditTitle").textContent = service.name;
    $("priceEditContext").textContent =
      `#${service.id} · Custo: R$ ${service.costUnit.replace(".", ",")} ${service.kind === "package" ? "por pacote" : "por unidade"}. Mudanças afetam novas compras.`;
    $("priceEditLabel").textContent =
      service.kind === "package"
        ? "Preço do pacote (R$)"
        : "Preço por unidade (R$) · até 6 casas decimais";
    $("priceEditValue").value = service.unitPrice.replace(".", ",");
    $("priceEditReason").value = "";
    $("priceEditError").textContent = "";
    $("priceReset").classList.toggle("hidden", !service.custom);
    $("priceEditor").showModal();
  }
  async function save(operation) {
    if (saving || !data) return;
    const general = operation === "multiplier";
    const reason = $(
      general ? "multiplierReason" : "priceEditReason",
    ).value.trim();
    const value = $(general ? "priceMultiplier" : "priceEditValue")
      .value.trim()
      .replace(",", ".");
    const errorNode = $(general ? "priceError" : "priceEditError");
    errorNode.textContent = "";
    if (
      reason.length < 5 ||
      (operation !== "reset" &&
        (!/^\d{1,5}(\.\d{1,6})?$/.test(value) || Number(value) <= 0))
    ) {
      errorNode.textContent =
        "Confira o valor e registre um motivo com pelo menos 5 caracteres.";
      return;
    }
    const belowCost = general
      ? Number(value) < 1
      : Number(value) < Number(selected.costUnit);
    const message = general
      ? `Aplicar custo × ${value} a todos os serviços sem exceção personalizada?`
      : operation === "reset"
        ? `Remover o preço personalizado de ${selected.name} e usar a regra geral?`
        : `Alterar ${selected.name} para R$ ${value.replace(".", ",")} ${selected.kind === "package" ? "por pacote" : "por unidade"}?`;
    saving = true;
    try {
      if (
        !(await confirmOperation(
          "Confirmar alteração de preço",
          message +
            (belowCost && operation !== "reset"
              ? " Atenção: o preço ficará abaixo do custo, gerando prejuízo."
              : "") +
            " Pedidos pagos mantêm o valor contratado.",
        ))
      )
        return;
      await post("/api/admin/prices", {
        operation,
        service_id: general ? null : selected.id,
        value,
        reason,
        revision: data.revision,
        confirmation: "CONFIRMO",
      });
      $("priceEditor").close();
      toast("Preço atualizado.");
      await load();
      window.storefront?.refresh();
    } catch (error) {
      errorNode.textContent = error.message;
    } finally {
      saving = false;
    }
  }
  $("managePrices").addEventListener("click", load);
  $("refreshPrices").addEventListener("click", load);
  $("backPriceAdmin").addEventListener("click", loadAdmin);
  $("priceSearch").addEventListener("input", () => {
    page = 0;
    render();
  });
  $("pricePrevious").addEventListener("click", () => {
    page--;
    render();
  });
  $("priceNext").addEventListener("click", () => {
    page++;
    render();
  });
  $("priceEditForm").addEventListener("submit", (event) => {
    event.preventDefault();
    save("unit");
  });
  $("multiplierForm").addEventListener("submit", (event) => {
    event.preventDefault();
    save("multiplier");
  });
  $("priceReset").addEventListener("click", () => save("reset"));
  $("priceEditClose").addEventListener("click", () => {
    if (!saving) $("priceEditor").close();
  });
})();
