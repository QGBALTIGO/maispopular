"use strict";
let depositAmount = 20,
  paymentAttempt = null,
  creditAttempt = null;
let activePayment = null,
  paymentTimer = null,
  paymentLoading = false,
  operationsBooted = false;
const post = (path, body) =>
  api(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
const paymentLabels = {
  CREATED: "Pronto para gerar",
  CREATING: "Gerando seu Pix…",
  UNKNOWN: "Geração pendente de confirmação",
  PENDING: "Aguardando pagamento",
  PAID: "Pagamento aprovado. Saldo disponível!",
  EXPIRED: "Este código Pix expirou",
  FAILED: "Recarga não concluída",
  REVERSED: "Pagamento estornado",
};

function confirmOperation(title, text) {
  const dialog = $("operationConfirm");
  if (dialog.open) return Promise.resolve(false);
  $("operationTitle").textContent = title;
  $("operationText").textContent = text;
  dialog.returnValue = "no";
  return new Promise((resolve) => {
    dialog.addEventListener(
      "close",
      () => resolve(dialog.returnValue === "yes"),
      { once: true },
    );
    dialog.showModal();
  });
}

function openDeposit() {
  show("deposit");
  const choices = state.bootstrap.depositOptions;
  if (!choices.includes(depositAmount)) depositAmount = choices[0];
  const buttons = choices.map((amount) => {
    const button = action("amount-button", () => {
      depositAmount = amount;
      openDeposit();
    });
    button.type = "button";
    button.textContent = `R$ ${amount}`;
    button.setAttribute("aria-pressed", String(amount === depositAmount));
    return button;
  });
  $("depositAmounts").replaceChildren(...buttons);
  $("generatePix").textContent = `Gerar Pix de ${formatMoney(depositAmount)}`;
  if (!$("payerName").value)
    $("payerName").value = state.bootstrap.user.firstName;
}

async function generatePayment(event) {
  event.preventDefault();
  if ($("depositFields").disabled) return;
  const payload = {
    amount: depositAmount,
    name: $("payerName").value,
    email: $("payerEmail").value,
    phone: $("payerPhone").value,
    document: $("payerDocument").value,
  };
  const signature = JSON.stringify(payload);
  if (!paymentAttempt || paymentAttempt.signature !== signature)
    paymentAttempt = { signature, id: crypto.randomUUID() };
  $("depositError").textContent = "";
  $("depositFields").disabled = true;
  $("generatePix").textContent = "Gerando seu Pix…";
  try {
    const row = await post("/api/payments", {
      ...payload,
      request_id: paymentAttempt.id,
    });
    // Do not retain payer identity in browser storage or after a completed request.
    paymentAttempt = null;
    $("depositForm").reset();
    renderPayment(row);
  } catch (error) {
    $("depositError").textContent =
      error.message + " Tentar novamente reutiliza esta tentativa.";
  } finally {
    $("depositFields").disabled = false;
    $("generatePix").textContent = `Gerar Pix de ${formatMoney(depositAmount)}`;
  }
}

async function loadPayments() {
  try {
    const data = await api("/api/payments");
    if (!data.payments.length)
      return empty(
        $("paymentList"),
        "Suas recargas aparecem aqui. Você pode reabrir um Pix pendente.",
        "wallet",
      );
    $("paymentList").replaceChildren(
      ...data.payments.map((row) => {
        const button = action("service-card payment-entry", () =>
          openPayment(row.id),
        );
        button.append(
          element("strong", "", row.amountLabel),
          element(
            "p",
            "service-summary",
            paymentLabels[row.status] || "Em análise",
          ),
          element("small", "muted", date(row.createdAt)),
        );
        return button;
      }),
    );
  } catch (error) {
    failure($("paymentList"), error, loadPayments);
  }
}

async function openPayment(id) {
  try {
    renderPayment(await api(`/api/payments/${id}`));
  } catch (error) {
    toast(error.message);
  }
}

function renderPayment(row) {
  const alreadyOpen = state.view === "payment" && activePayment?.id === row.id;
  activePayment = row;
  if (!alreadyOpen) show("payment");
  updateBalance(row);
  $("paymentHeading").textContent =
    row.status === "PAID" ? "Saldo liberado" : "Seu Pix";
  $("paymentStatus").textContent = paymentLabels[row.status] || "Em análise";
  $("paymentAmount").textContent = row.amountLabel;
  const expiry = row.expiresAt
    ? new Date(row.expiresAt.replace(" ", "T"))
    : null;
  $("paymentExpires").textContent =
    expiry && !isNaN(expiry)
      ? `Validade: ${expiry.toLocaleString("pt-BR")}`
      : "";
  const payable = row.status === "PENDING" && row.qrCode;
  $("pixContent").classList.toggle("hidden", !payable);
  if (payable) $("pixImage").src = row.qrImage;
  else $("pixImage").removeAttribute("src");
  $("pixCode").value = payable ? row.qrCode : "";
  $("retryPix").classList.toggle(
    "hidden",
    !["CREATED", "UNKNOWN", "CREATING"].includes(row.status),
  );
  $("anotherPix").classList.toggle(
    "hidden",
    !["PAID", "FAILED", "EXPIRED", "REVERSED"].includes(row.status),
  );
  $("refreshPix").classList.toggle(
    "hidden",
    !["PENDING", "EXPIRED"].includes(row.status),
  );
  $("paymentError").textContent = "";
  clearTimeout(paymentTimer);
  if (["PENDING", "CREATING", "UNKNOWN"].includes(row.status))
    paymentTimer = setTimeout(() => refreshPayment(false), 10000);
}

async function refreshPayment(manual = true, retry = false) {
  if (!activePayment || paymentLoading || state.view !== "payment") return;
  if (!manual && document.hidden) {
    paymentTimer = setTimeout(() => refreshPayment(false), 10000);
    return;
  }
  paymentLoading = true;
  busy($("refreshPix"), true);
  busy($("retryPix"), true);
  const id = activePayment.id;
  try {
    const row = retry
      ? await post(`/api/payments/${id}/retry`)
      : activePayment.status === "PENDING" || manual
        ? await post(`/api/payments/${id}/refresh`)
        : await api(`/api/payments/${id}`);
    if (state.view === "payment" && activePayment.id === id) renderPayment(row);
  } catch (error) {
    $("paymentError").textContent = error.message;
  } finally {
    paymentLoading = false;
    busy($("refreshPix"), false);
    busy($("retryPix"), false);
  }
}

async function openOrderDetail(id) {
  show("orderDetail");
  const container = $("orderDetailContent");
  container.replaceChildren(element("p", "intro-copy", "Carregando pedido…"));
  try {
    const row = await api(`/api/orders/${id}`);
    const title = element("h1", "", row.serviceName);
    const panel = element("article", "product-detail");
    panel.append(
      element("p", "eyebrow", `PEDIDO #${id.slice(0, 8)}`),
      title,
      element("p", "intro-copy", statusLabel(row)),
      element("p", "order-target", row.target),
      element(
        "p",
        "intro-copy",
        `Total: ${row.costLabel} · ${date(row.createdAt)}`,
      ),
      element(
        "p",
        "intro-copy",
        `Contagem inicial: ${row.startCount} · Restante: ${row.remains}`,
      ),
    );
    if (row.state === "UNKNOWN")
      panel.append(
        element(
          "p",
          "notice",
          "A equipe está verificando este pedido. Não repita a compra.",
        ),
      );
    const refresh = action("secondary-button", async () => {
      busy(refresh, true);
      try {
        await post(`/api/orders/${id}/refresh`);
        await openOrderDetail(id);
      } catch (error) {
        toast(error.message);
      } finally {
        busy(refresh, false);
      }
    });
    refresh.textContent = "Atualizar andamento";
    panel.append(refresh);
    for (const kind of ["refill", "cancel"]) {
      if (!row[kind]) continue;
      const label =
        kind === "refill" ? "Solicitar reposição" : "Solicitar cancelamento";
      const button = action("secondary-button", async () => {
        busy(button, true);
        try {
          const draft = await post(`/api/orders/${id}/actions/${kind}`);
          if (
            !(await confirmOperation(
              label,
              "A solicitação será analisada conforme as condições do serviço. Não há garantia de aprovação nem reembolso automático.",
            ))
          )
            return;
          const result = await post(`/api/actions/${draft.id}/confirm`);
          toast(
            result.state === "SUBMITTED"
              ? "Solicitação registrada."
              : "Solicitação em análise ou não concluída. Fale com o suporte se necessário.",
          );
          await openOrderDetail(id);
        } catch (error) {
          toast(error.message);
        } finally {
          busy(button, false);
        }
      });
      button.textContent = label;
      panel.append(button);
    }
    for (const item of row.actions) {
      panel.append(
        element(
          "p",
          "intro-copy",
          `${item.kind === "refill" ? "Reposição" : "Cancelamento"}: ${{ SUBMITTED: "Enviado", UNKNOWN: "Em verificação", REJECTED: "Não realizado", SENDING: "Enviando" }[item.state] || "Em análise"}`,
        ),
      );
      if (item.hasRefill) {
        const check = action("text-button", async () => {
          try {
            const result = await api(`/api/actions/${item.id}`);
            toast(`Reposição: ${result.status}`);
          } catch (error) {
            toast(error.message);
          }
        });
        check.textContent = "Consultar reposição";
        panel.append(check);
      }
    }
    container.replaceChildren(panel);
  } catch (error) {
    failure(container, error, () => openOrderDetail(id));
  }
}

async function loadAdminUsers() {
  const data = await api(
    `/api/admin/users?search=${encodeURIComponent($("adminSearch").value)}`,
  );
  $("adminUsers").replaceChildren(
    ...data.users.map((user) => {
      const card = action("service-card payment-entry", () => {
        $("creditUser").value = user.user_id;
        $("creditAmount").focus();
      });
      card.append(
        element("strong", "", user.display_name || "Cliente"),
        element(
          "p",
          "service-summary",
          `${user.user_id} ${user.username ? "· @" + user.username : ""}`,
        ),
        element(
          "p",
          "intro-copy",
          `Saldo: ${formatMoney(user.balance_cents / 100)}`,
        ),
      );
      return card;
    }),
  );
  if (!data.users.length) empty($("adminUsers"), "Nenhum cliente encontrado.");
}

async function loadAdmin() {
  if (!state.bootstrap?.isAdmin)
    return toast("Acesso exclusivo de administrador.");
  show("admin");
  $("adminError").textContent = "";
  busy($("refreshAdmin"), true);
  try {
    const data = await api("/api/admin"),
      stats = data.stats;
    $("adminStats").replaceChildren(
      ...[
        ["Clientes", stats.users],
        ["Pedidos", stats.orders],
        ["Saldo dos clientes", formatMoney(stats.wallet_cents / 100)],
        ["Recargas aprovadas", formatMoney(stats.paid_cents / 100)],
        ["Recargas abertas", stats.pending_payments],
        ["Capacidade operacional", stats.operationalLabel],
      ].map(([label, value]) => {
        const card = element("div", "stat-card");
        card.append(
          element("small", "muted", label),
          element("strong", "", String(value)),
        );
        return card;
      }),
    );
    await loadAdminUsers();
    $("adminCredits").replaceChildren(
      ...data.credits.map((row) => {
        const card = element("div", "activity-row credit-audit");
        card.append(
          element(
            "strong",
            "positive",
            `+ ${formatMoney(row.amount_cents / 100)}`,
          ),
          element("p", "", `Cliente ${row.user_id} · ${row.reason}`),
          element(
            "small",
            "",
            `Admin ${row.admin_id} · ${date(row.created_at)}`,
          ),
        );
        return card;
      }),
    );
    if (!data.credits.length)
      empty($("adminCredits"), "Nenhum crédito administrativo registrado.");
    $("adminUnknown").replaceChildren(
      ...data.unknownOrders.map((row) => {
        const card = element("div", "service-card");
        card.append(
          element("strong", "", row.service_name),
          element(
            "p",
            "intro-copy",
            `${row.id} · Cliente ${row.user_id} · ${formatMoney(Number(row.cost))}`,
          ),
        );
        const label = element("label", "field");
        label.textContent = "ID externo confirmado ou naocriado";
        const input = element("input", "");
        input.maxLength = 20;
        label.append(input);
        card.append(label);
        const button = action("secondary-button", async () => {
          if (!/^(naocriado|[1-9][0-9]{0,19})$/.test(input.value))
            return toast("Confira o ID externo ou digite naocriado.");
          const decision = input.value;
          if (
            !(await confirmOperation(
              "Resolver pedido",
              `${row.id}: ${decision}. Use naocriado somente após verificar que não existe pedido no fornecedor; essa decisão devolve o saldo.`,
            ))
          )
            return;
          busy(button, true);
          try {
            await post(`/api/admin/orders/${row.id}/resolve`, {
              decision,
              confirmation: "CONFIRMO",
            });
            await loadAdmin();
          } catch (error) {
            toast(error.message);
          } finally {
            busy(button, false);
          }
        });
        button.textContent = "Revisar resolução";
        card.append(button);
        return card;
      }),
    );
    if (!data.unknownOrders.length)
      empty($("adminUnknown"), "Nenhum pedido aguardando verificação.");
  } catch (error) {
    $("adminError").textContent = error.message;
  } finally {
    busy($("refreshAdmin"), false);
  }
}

$("creditForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if ($("creditSubmit").disabled) return;
  const payload = {
    user_id: Number($("creditUser").value),
    amount: $("creditAmount").value,
    reason: $("creditReason").value,
  };
  if (
    !Number.isSafeInteger(payload.user_id) ||
    payload.user_id <= 0 ||
    !/^\d{1,4}([.,]\d{1,2})?$/.test(payload.amount)
  )
    return toast("Confira o ID e o valor.");
  busy($("creditSubmit"), true);
  try {
    if (
      !(await confirmOperation(
        "Confirmar crédito",
        `Adicionar ${formatMoney(Number(payload.amount.replace(",", ".")))} ao cliente ${payload.user_id}? Motivo: ${payload.reason}`,
      ))
    )
      return;
    const signature = JSON.stringify(payload);
    if (!creditAttempt || creditAttempt.signature !== signature)
      creditAttempt = { signature, id: crypto.randomUUID() };
    const result = await post("/api/admin/credits", {
      ...payload,
      request_id: creditAttempt.id,
    });
    creditAttempt = null;
    $("creditResult").textContent =
      `Crédito registrado para ${result.userId}. Saldo: ${formatMoney(result.balanceCents / 100)}.`;
    $("creditForm").reset();
    await loadAdmin();
  } catch (error) {
    $("creditResult").textContent = error.message;
  } finally {
    busy($("creditSubmit"), false);
  }
});
$("depositForm").addEventListener("submit", generatePayment);
$("refreshPayments").addEventListener("click", loadPayments);
$("refreshPix").addEventListener("click", () => refreshPayment(true));
$("retryPix").addEventListener("click", () => refreshPayment(true, true));
$("anotherPix").addEventListener("click", openDeposit);
$("copyPix").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("pixCode").value);
    toast("Código Pix copiado.");
  } catch {
    $("pixCode").focus();
    $("pixCode").select();
    toast("Selecione e copie o código acima.");
  }
});
$("backOrders").addEventListener("click", () => loadOrders());
$("adminEntry").addEventListener("click", loadAdmin);
$("refreshAdmin").addEventListener("click", loadAdmin);
$("adminSearchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await loadAdminUsers();
  } catch (error) {
    toast(error.message);
  }
});
window.storeOperations = {
  onView(view) {
    if (view !== "payment") clearTimeout(paymentTimer);
    if (view === "wallet") loadPayments();
  },
  boot() {
    if (operationsBooted) return;
    operationsBooted = true;
    $("adminEntry").classList.toggle("hidden", !state.bootstrap.isAdmin);
    const view = new URLSearchParams(location.search).get("view");
    if (view === "deposit") openDeposit();
    else if (view === "admin") loadAdmin();
    else if (["wallet", "orders", "help"].includes(view)) navigate(view);
  },
};
if (state.bootstrap) window.storeOperations.boot();
