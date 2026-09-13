"use strict";
(() => {
  const statusLabels = { OPEN: "Inscrições abertas", DRAWING: "Apuração em andamento", COMPLETED: "Encerrado" };
  function openBot(url) {
    if (tg?.openTelegramLink) tg.openTelegramLink(url);
    else location.assign(url);
  }
  async function loadRaffle() {
    show("raffle");
    $("raffleError").textContent = "";
    try {
      const data = await api("/api/raffle");
      const when = new Date(data.campaign.scheduledAt * 1000).toLocaleString("pt-BR", { day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit" });
      $("raffleCountdown").textContent = `${when} · @MaisPopular`;
      const participant = data.participant;
      $("raffleStatus").textContent = participant?.status === "ELIGIBLE"
        ? `Participação confirmada · ${data.cards.length} cartela(s) · ${data.referrals} indicação(ões) válida(s)`
        : `${statusLabels[data.campaign.status] || data.campaign.status}. Confirme sua participação pelo bot.`;
      $("raffleCards").replaceChildren(...data.cards.map((card, index) => {
        const el = element("article", "raffle-card");
        el.append(element("small", "", `CARTELA ${index + 1} · ${card.source === "BASE" ? "PARTICIPAÇÃO" : "INDICAÇÃO"}`));
        const values = element("div", "raffle-numbers");
        card.numbers.split(" • ").forEach((value) => values.append(element("span", "raffle-number", value)));
        el.append(values); return el;
      }));
      $("raffleChannels").replaceChildren(...data.channels.map((channel) => {
        const link = element("a", "", channel.name); link.href = channel.url; return link;
      }));
      $("raffleJoin").textContent = participant?.status === "ELIGIBLE" ? "Ver cartelas e meu link no bot" : "Participar pelo bot";
      $("raffleJoin").onclick = () => openBot(data.joinUrl);
    } catch (error) { $("raffleError").textContent = error.message; }
  }
  async function loadRaffleAdmin() {
    if (!state.bootstrap?.isAdmin) return toast("Acesso exclusivo de administrador.");
    show("raffleAdmin"); $("raffleAdminError").textContent = "";
    try {
      const data = await api("/api/admin/raffle");
      $("raffleAdminStats").replaceChildren(
        ...[["Status", statusLabels[data.campaign.status] || data.campaign.status], ["Participantes", number(data.participants)], ["Elegíveis", number(data.eligible)], ["Cartelas", number(data.cards)]].map(([label,value]) => {
          const el = element("div", ""); el.append(element("small", "", label), element("strong", "", value)); return el;
        }),
      );
      $("raffleWinners").replaceChildren(...data.winners.map((row) => {
        const el = element("article", "service-card");
        el.append(element("h3", "", `${row.position}º · ${row.display_name || row.username || row.user_id}`), element("p", "intro-copy", `Dados: ${JSON.parse(row.dice_values).map((v) => String(v).padStart(2,"0")).join(" • ")} · Distância ${row.distance}`), element("small", "", row.prize_choice ? `Escolheu ${row.prize_choice === "netflix" ? "Netflix 4K" : "Crunchyroll Premium"}` : "Aguardando escolha")); return el;
      }));
      if (!data.winners.length) empty($("raffleWinners"), "A apuração ainda não começou.", "grid");
    } catch (error) { $("raffleAdminError").textContent = error.message; }
  }
  $("raffleEntry").addEventListener("click", loadRaffle);
  $("manageRaffle").addEventListener("click", loadRaffleAdmin);
  $("refreshRaffleAdmin").addEventListener("click", loadRaffleAdmin);
  $("backRaffleAdmin").addEventListener("click", loadAdmin);
  window.loadRaffle = loadRaffle;
  window.loadRaffleAdmin = loadRaffleAdmin;
})();
