(() => {
  "use strict";

  const form = document.getElementById("contact-form");
  const status = document.getElementById("contact-status");
  if (!(form instanceof HTMLFormElement)) return;

  form.addEventListener("submit", (event) => {
    event.preventDefault();

    if (!form.reportValidity()) {
      if (status) status.textContent = "Revise os campos obrigatórios antes de continuar.";
      return;
    }

    const data = new FormData(form);
    const nome = String(data.get("nome") || "").trim();
    const email = String(data.get("email") || "").trim();
    const assunto = String(data.get("assunto") || "Contato pelo site").trim();
    const mensagem = String(data.get("mensagem") || "").trim();

    const subject = `[CurVE] ${assunto}`;
    const body = [
      `Nome: ${nome}`,
      `E-mail para retorno: ${email}`,
      "",
      "Mensagem:",
      mensagem,
    ].join("\n");

    if (status) status.textContent = "Abrindo seu aplicativo de e-mail para revisão e envio.";

    const mailto = `mailto:sv.alisson@gmail.com?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    window.location.href = mailto;
  });
})();
