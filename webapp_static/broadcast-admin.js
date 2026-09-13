"use strict";
(() => {
  let attempt = null,
    timer = null,
    loading = false;
  const labels = {
    QUEUED: "Na fila",
    RUNNING: "Enviando",
    COMPLETED: "Concluída",
    CANCELLED: "Cancelada",
  };
  function preview() {
    const message = $("broadcastMessage").value;
    const button = $("broadcastButtonText").value.trim();
    $("broadcastCount").textContent = `${message.length} / 3500`;
    $("broadcastPreview").textContent = message || "Sua mensagem aparecerá aqui.";
    $("broadcastPreviewButton").textContent = button;
    $("broadcastPreviewButton").classList.toggle("hidden", !button);
  }
  function render(data) {
    $("broadcastAudience").textContent = `${number(data.audience)} clientes`;
    $("broadcastList").replaceChildren(
      ...data.broadcasts.map((row) => {
        const done = row.sent + row.failed;
        const card = element("article", "service-card broadcast-job");
        const top = element("div", "service-top");
        top.append(
          element("strong", "", labels[row.status] || row.status),
          element("small", "muted", date(row.createdAt)),
        );
        const progress = element("progress", "");
        progress.max = Math.max(row.total, 1);
        progress.value = done;
        card.append(
          top,
          element("p", "broadcast-excerpt", row.message),
          progress,
          element("small", "", `${row.sent} entregues · ${row.failed} falhas · ${row.total - done} pendentes`),
        );
        if (["QUEUED", "RUNNING"].includes(row.status)) {
          const cancel = action("text-button", async () => {
            if (!(await confirmOperation("Cancelar transmissão", "As mensagens já entregues não podem ser removidas. Deseja impedir os próximos envios?"))) return;
            busy(cancel, true);
            try {
              await post(`/api/admin/broadcasts/${row.id}/cancel`);
              toast("Transmissão cancelada.");
              await loadBroadcasts();
            } catch (error) {
              toast(error.message);
            } finally {
              busy(cancel, false);
            }
          });
          cancel.textContent = "Cancelar próximos envios";
          card.append(cancel);
        }
        return card;
      }),
    );
    if (!data.broadcasts.length)
      empty($("broadcastList"), "Nenhuma transmissão realizada.", "chat");
    clearTimeout(timer);
    if (data.broadcasts.some((row) => ["QUEUED", "RUNNING"].includes(row.status)) && state.view === "broadcastAdmin")
      timer = setTimeout(loadBroadcasts, 2500);
  }
  async function loadBroadcasts() {
    if (!state.bootstrap?.isAdmin) return toast("Acesso exclusivo de administrador.");
    show("broadcastAdmin");
    if (loading) return;
    loading = true;
    $("broadcastError").textContent = "";
    try {
      render(await api("/api/admin/broadcasts"));
    } catch (error) {
      $("broadcastError").textContent = error.message;
    } finally {
      loading = false;
    }
  }
  $("broadcastMessage").addEventListener("input", preview);
  $("broadcastButtonText").addEventListener("input", preview);
  $("broadcastButtonTarget").addEventListener("change", () => {
    if ($("broadcastButtonTarget").value === "none") $("broadcastButtonText").value = "";
    preview();
  });
  $("broadcastForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      message: $("broadcastMessage").value.trim(),
      button_text: $("broadcastButtonText").value.trim(),
      button_target: $("broadcastButtonTarget").value,
    };
    if (!payload.message) return toast("Escreva a mensagem da transmissão.");
    if (Boolean(payload.button_text) !== (payload.button_target !== "none"))
      return toast("Escolha o texto e o destino do botão.");
    const audience = $("broadcastAudience").textContent;
    if (!(await confirmOperation("Confirmar transmissão", `A mensagem será enviada para ${audience}. Confira a prévia antes de continuar.`))) return;
    const signature = JSON.stringify(payload);
    if (!attempt || attempt.signature !== signature)
      attempt = { signature, id: requestId() };
    busy($("broadcastSubmit"), true);
    try {
      await post("/api/admin/broadcasts", { ...payload, request_id: attempt.id, confirmation: "CONFIRMO" });
      attempt = null;
      $("broadcastForm").reset();
      preview();
      toast("Transmissão iniciada.");
      await loadBroadcasts();
    } catch (error) {
      $("broadcastError").textContent = error.message;
    } finally {
      busy($("broadcastSubmit"), false);
    }
  });
  $("manageBroadcasts").addEventListener("click", loadBroadcasts);
  $("backBroadcastAdmin").addEventListener("click", () => {
    clearTimeout(timer);
    loadAdmin();
  });
  $("refreshBroadcasts").addEventListener("click", loadBroadcasts);
  window.loadBroadcasts = loadBroadcasts;
  preview();
})();
