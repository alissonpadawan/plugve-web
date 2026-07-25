(() => {
  "use strict";

  const triggers = document.querySelectorAll("[data-profile-dialog]");

  triggers.forEach((trigger) => {
    const dialogId = trigger.getAttribute("data-profile-dialog");
    const dialog = dialogId ? document.getElementById(dialogId) : null;
    if (!(dialog instanceof HTMLDialogElement)) return;

    const closeButton = dialog.querySelector("[data-dialog-close]");

    trigger.addEventListener("click", () => {
      dialog.showModal();
      document.body.classList.add("dialog-open");
    });

    closeButton?.addEventListener("click", () => dialog.close());

    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });

    dialog.addEventListener("close", () => {
      document.body.classList.remove("dialog-open");
      trigger.focus();
    });
  });
})();
