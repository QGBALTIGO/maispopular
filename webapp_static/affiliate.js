"use strict";
(() => {
  let loading = false;
  async function loadAffiliate() {
    if (loading) return;
    show("affiliate");
    loading = true;
    $("affiliateError").textContent = "";
    try {
      const data = await api("/api/affiliate");
      $("affiliateEarned").textContent = data.earnedLabel;
      $("affiliateInvited").textContent = number(data.invited);
      $("affiliateLink").value = data.link;
      $("affiliatePeople").replaceChildren(
        ...data.people.map((person) => {
          const row = element("div", "activity-row");
          const info = element("div", "");
          info.append(
            element("p", "", person.display_name || "Cliente"),
            element("small", "", `${person.username ? "@" + person.username + " · " : ""}entrou em ${date(person.created_at)}`),
          );
          row.append(icon("users", "family-icon"), info, element("strong", "positive", person.earnedLabel));
          return row;
        }),
      );
      if (!data.people.length)
        empty($("affiliatePeople"), "Seus indicados aparecerão aqui.", "users");
    } catch (error) {
      $("affiliateError").textContent = error.message;
    } finally {
      loading = false;
    }
  }
  $("affiliateEntry").addEventListener("click", loadAffiliate);
  $("copyAffiliate").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("affiliateLink").value);
      toast("Link de indicação copiado.");
    } catch {
      $("affiliateLink").select();
      toast("Selecione e copie o link acima.");
    }
  });
  window.loadAffiliate = loadAffiliate;
})();
