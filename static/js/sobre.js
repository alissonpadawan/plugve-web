(() => {
  "use strict";

  const entries = Array.from(document.querySelectorAll(".author-entry"));
  const hoverMedia = window.matchMedia("(hover: hover) and (pointer: fine)");

  const setOpen = (entry, open) => {
    const trigger = entry.querySelector("[data-author-popover]");
    entry.classList.toggle("is-open", open);
    trigger?.setAttribute("aria-expanded", String(open));
  };

  const closeAll = (except = null) => {
    entries.forEach((entry) => {
      if (entry !== except) setOpen(entry, false);
    });
  };

  entries.forEach((entry) => {
    const trigger = entry.querySelector("[data-author-popover]");
    if (!(trigger instanceof HTMLButtonElement)) return;

    entry.addEventListener("mouseenter", () => {
      if (!hoverMedia.matches) return;
      closeAll(entry);
      setOpen(entry, true);
    });

    entry.addEventListener("mouseleave", () => {
      if (!hoverMedia.matches) return;
      setOpen(entry, false);
    });

    entry.addEventListener("focusin", () => {
      closeAll(entry);
      setOpen(entry, true);
    });

    entry.addEventListener("focusout", () => {
      window.setTimeout(() => {
        if (!entry.contains(document.activeElement)) setOpen(entry, false);
      }, 0);
    });

    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = !entry.classList.contains("is-open");
      closeAll(entry);
      setOpen(entry, willOpen);
    });
  });

  document.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Node)) return;
    if (!entries.some((entry) => entry.contains(event.target))) closeAll();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const openEntry = entries.find((entry) => entry.classList.contains("is-open"));
    if (!openEntry) return;
    const trigger = openEntry.querySelector("[data-author-popover]");
    setOpen(openEntry, false);
    if (trigger instanceof HTMLButtonElement) trigger.focus();
  });
})();
