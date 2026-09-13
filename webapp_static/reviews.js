"use strict";
(() => {
  let page = 0,
    loading = false;
  const stars = (rating) => {
    const node = element(
      "span",
      "review-stars",
      "★".repeat(rating) + "☆".repeat(5 - rating),
    );
    node.setAttribute("aria-label", `${rating} de 5 estrelas`);
    return node;
  };
  async function load(reset = true) {
    if (loading) return;
    loading = true;
    if (reset) page = 0;
    try {
      const data = await api(`/api/reviews?page=${page}`);
      const summary = $("reviewsSummary");
      summary.replaceChildren();
      if (data.count) {
        summary.append(
          element("strong", "review-average", data.average.replace(".", ",")),
          stars(Math.round(Number(data.average))),
          element(
            "p",
            "",
            `Baseado em ${number(data.count)} ${data.count === 1 ? "avaliação" : "avaliações"}`,
          ),
        );
      } else {
        summary.append(
          element("h3", "", "Sua experiência importa"),
          element(
            "p",
            "",
            "Ainda não recebemos avaliações. Depois da entrega, avalie seu pedido e ajude outros clientes a escolher.",
          ),
        );
      }
      if (reset) $("reviewsList").replaceChildren();
      for (const review of data.reviews) {
        const card = element("article", "customer-review"),
          header = element("div", "customer-review-header");
        const avatar = element(
          "span",
          "review-avatar",
          review.name[0].toUpperCase(),
        );
        avatar.setAttribute("aria-hidden", "true");
        const identity = element("div", "");
        identity.append(
          element("strong", "", review.name),
          element("span", "review-verified", "✓ Compra verificada"),
        );
        const when = element(
          "time",
          "",
          new Intl.DateTimeFormat("pt-BR", {
            day: "2-digit",
            month: "short",
            year: "numeric",
          }).format(review.createdAt * 1000),
        );
        when.dateTime = new Date(review.createdAt * 1000).toISOString();
        header.append(avatar, identity, when);
        card.append(
          header,
          stars(review.rating),
          element("p", "review-comment", review.comment),
        );
        $("reviewsList").append(card);
      }
      $("moreReviews").classList.toggle("hidden", !data.hasMore);
      $("reviewsError").textContent = "";
      page++;
    } catch (error) {
      $("reviewsError").textContent = error.message;
    } finally {
      loading = false;
    }
  }
  function orderForm(row, container) {
    if (row.reviewed) {
      container.append(
        element(
          "p",
          "review-thanks",
          "✓ Obrigado por compartilhar sua avaliação.",
        ),
      );
      return;
    }
    if (!row.canReview) return;
    const form = element("form", "review-form");
    form.append(
      element("p", "eyebrow", "PEDIDO ENTREGUE"),
      element("h2", "", "Como foi sua experiência?"),
      element(
        "p",
        "intro-copy",
        "Sua opinião será publicada na loja. Use um apelido e não inclua telefone, CPF ou dados de acesso.",
      ),
    );
    const group = element("fieldset", "review-rating");
    group.append(element("legend", "", "Sua nota"));
    for (let i = 1; i <= 5; i++) {
      const label = element("label", ""),
        input = element("input", "");
      input.type = "radio";
      input.name = "rating";
      input.value = i;
      input.required = true;
      label.append(input, element("span", "", `${i} ★`));
      group.append(label);
    }
    form.append(group);
    const nameLabel = element("label", "field"),
      name = element("input", "");
    name.name = "name";
    name.required = true;
    name.minLength = 2;
    name.maxLength = 40;
    name.autocomplete = "off";
    nameLabel.append(element("span", "", "Apelido público"), name);
    const commentLabel = element("label", "field"),
      comment = element("textarea", "");
    comment.name = "comment";
    comment.rows = 4;
    comment.minLength = 10;
    comment.maxLength = 600;
    comment.required = true;
    comment.placeholder = "Conte como foi a entrega e o atendimento.";
    commentLabel.append(element("span", "", "Sua avaliação"), comment);
    const consentLabel = element("label", "review-consent"),
      consent = element("input", "");
    consent.type = "checkbox";
    consent.required = true;
    consent.name = "consent";
    consentLabel.append(
      consent,
      document.createTextNode(
        "Autorizo a publicação do meu apelido, nota e comentário na loja.",
      ),
    );
    const error = element("p", "field-error");
    error.setAttribute("role", "alert");
    const submit = element("button", "primary-button", "Publicar avaliação");
    submit.type = "submit";
    form.append(nameLabel, commentLabel, consentLabel, error, submit);
    let sending = false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (sending || !form.reportValidity()) return;
      sending = true;
      busy(submit, true);
      error.textContent = "";
      try {
        await post(`/api/orders/${row.id}/review`, {
          name: name.value.trim(),
          rating: Number(new FormData(form).get("rating")),
          comment: comment.value.trim(),
          consent: consent.checked,
        });
        toast("Avaliação publicada. Obrigado!");
        await openOrderDetail(row.id);
        await load();
      } catch (e) {
        error.textContent = e.message;
      } finally {
        sending = false;
        busy(submit, false);
      }
    });
    container.append(form);
  }
  $("moreReviews").addEventListener("click", () => load(false));
  $("reviewOrders").addEventListener("click", loadOrders);
  $("refreshReviews").addEventListener("click", () => load());
  window.customerReviews = { load, orderForm };
  if (state.bootstrap) load();
})();
