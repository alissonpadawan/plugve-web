(() => {
  "use strict";

  const form = document.getElementById("contact-form");
  const status = document.getElementById("contact-status");
  const submitButton = form?.querySelector("[data-contact-submit]");
  if (!(form instanceof HTMLFormElement)) return;

  const setStatus = (message, isError = false) => {
    if (!status) return;
    status.textContent = message;
    status.classList.toggle("is-error", isError);
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!form.reportValidity()) {
      setStatus("Revise os campos obrigatórios antes de enviar.", true);
      return;
    }

    const data = new FormData(form);
    const payload = {
      nome: String(data.get("nome") || "").trim(),
      email: String(data.get("email") || "").trim(),
      assunto: String(data.get("assunto") || "").trim(),
      mensagem: String(data.get("mensagem") || "").trim(),
      website: String(data.get("website") || "").trim(),
    };

    if (submitButton instanceof HTMLButtonElement) submitButton.disabled = true;
    setStatus("Enviando mensagem...");

    try {
      const response = await fetch("/api/contato", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": String(form.dataset.contactCsrf || ""),
        },
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        throw new Error(result.error || "Não foi possível enviar a mensagem.");
      }

      form.reset();
      setStatus(result.message || "Mensagem enviada. Obrigado pelo contato.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Não foi possível enviar a mensagem.", true);
    } finally {
      if (submitButton instanceof HTMLButtonElement) submitButton.disabled = false;
    }
  });
})();
