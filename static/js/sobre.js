(() => {
  "use strict";

  const numberFormatter = new Intl.NumberFormat("pt-BR");

  /* Perfis dos autores */
  const entries = Array.from(document.querySelectorAll(".author-entry"));
  const hoverMedia = window.matchMedia("(hover: hover) and (pointer: fine)");

  const setAuthorOpen = (entry, open) => {
    const trigger = entry.querySelector("[data-author-popover]");
    entry.classList.toggle("is-open", open);
    trigger?.setAttribute("aria-expanded", String(open));
  };

  const closeAuthors = (except = null) => {
    entries.forEach((entry) => {
      if (entry !== except) setAuthorOpen(entry, false);
    });
  };

  entries.forEach((entry) => {
    const trigger = entry.querySelector("[data-author-popover]");
    if (!(trigger instanceof HTMLButtonElement)) return;

    entry.addEventListener("mouseenter", () => {
      if (!hoverMedia.matches) return;
      closeAuthors(entry);
      setAuthorOpen(entry, true);
    });

    entry.addEventListener("mouseleave", () => {
      if (!hoverMedia.matches) return;
      setAuthorOpen(entry, false);
    });

    entry.addEventListener("focusin", () => {
      closeAuthors(entry);
      setAuthorOpen(entry, true);
    });

    entry.addEventListener("focusout", () => {
      window.setTimeout(() => {
        if (!entry.contains(document.activeElement)) setAuthorOpen(entry, false);
      }, 0);
    });

    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = !entry.classList.contains("is-open");
      closeAuthors(entry);
      setAuthorOpen(entry, willOpen);
    });
  });

  document.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Node)) return;
    if (!entries.some((entry) => entry.contains(event.target))) closeAuthors();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const openEntry = entries.find((entry) => entry.classList.contains("is-open"));
    if (!openEntry) return;
    const trigger = openEntry.querySelector("[data-author-popover]");
    setAuthorOpen(openEntry, false);
    if (trigger instanceof HTMLButtonElement) trigger.focus();
  });

  /* Avaliação e visitantes */
  const engagement = document.querySelector("[data-sobre-engagement]");
  const csrfToken = engagement?.getAttribute("data-csrf-token") || "";
  const engagementFeedback = document.querySelector("[data-engagement-feedback]");
  const likeCount = document.querySelector("[data-like-count]");
  const dislikeCount = document.querySelector("[data-dislike-count]");
  const visitorCount = document.querySelector("[data-visitor-count]");
  const voteButtons = Array.from(document.querySelectorAll("[data-vote]"));

  [likeCount, dislikeCount, visitorCount].forEach((element) => {
    if (element) element.textContent = numberFormatter.format(Number(element.textContent || 0));
  });

  const setFeedback = (element, message, isError = false) => {
    if (!(element instanceof HTMLElement)) return;
    element.textContent = message;
    element.classList.toggle("is-error", isError);
  };

  const updateStats = (payload) => {
    if (likeCount) likeCount.textContent = numberFormatter.format(Number(payload.likes || 0));
    if (dislikeCount) dislikeCount.textContent = numberFormatter.format(Number(payload.dislikes || 0));
    if (visitorCount) visitorCount.textContent = numberFormatter.format(Number(payload.visitors || 0));

    voteButtons.forEach((button) => {
      const active = button.getAttribute("data-vote") === payload.user_vote;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  };

  voteButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      const vote = button.getAttribute("data-vote");
      voteButtons.forEach((item) => { item.disabled = true; });
      setFeedback(engagementFeedback, "");

      try {
        const response = await fetch("/api/sobre/vote", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
          },
          body: JSON.stringify({ vote }),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || "Não foi possível registrar sua avaliação.");
        updateStats(payload);
        setFeedback(engagementFeedback, payload.user_vote ? "Avaliação registrada." : "Avaliação removida.");
      } catch (error) {
        setFeedback(engagementFeedback, error instanceof Error ? error.message : "Não foi possível registrar sua avaliação.", true);
      } finally {
        voteButtons.forEach((item) => { item.disabled = false; });
      }
    });
  });

  /* Compartilhamento */
  const shareDialog = document.getElementById("share-about-dialog");
  const shareUrlInput = document.getElementById("share-about-url");
  const shareFeedback = document.querySelector("[data-share-feedback]");
  const shareTitle = "Sobre a CurVE — Calculadora Veicular";
  const canonicalUrl = `${window.location.origin}${window.location.pathname}`;

  const buildShareUrls = () => {
    const url = encodeURIComponent(canonicalUrl);
    const title = encodeURIComponent(shareTitle);
    return {
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${url}`,
      x: `https://twitter.com/intent/tweet?url=${url}&text=${title}`,
      linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${url}`,
      whatsapp: `https://wa.me/?text=${encodeURIComponent(`${shareTitle} ${canonicalUrl}`)}`,
    };
  };

  const openShareDialog = () => {
    if (!(shareDialog instanceof HTMLDialogElement)) return;
    if (shareUrlInput instanceof HTMLInputElement) shareUrlInput.value = canonicalUrl;
    const urls = buildShareUrls();
    document.querySelectorAll("[data-share-platform]").forEach((link) => {
      const platform = link.getAttribute("data-share-platform");
      if (link instanceof HTMLAnchorElement && platform && urls[platform]) link.href = urls[platform];
    });
    setFeedback(shareFeedback, "");
    if (!shareDialog.open) shareDialog.showModal();
  };

  document.querySelector("[data-open-share]")?.addEventListener("click", openShareDialog);
  document.querySelector("[data-close-share]")?.addEventListener("click", () => {
    if (shareDialog instanceof HTMLDialogElement) shareDialog.close();
  });

  shareDialog?.addEventListener("click", (event) => {
    if (!(shareDialog instanceof HTMLDialogElement)) return;
    const rect = shareDialog.getBoundingClientRect();
    const outside = event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
    if (outside) shareDialog.close();
  });

  document.querySelector("[data-copy-share]")?.addEventListener("click", async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(canonicalUrl);
      } else if (shareUrlInput instanceof HTMLInputElement) {
        shareUrlInput.select();
        document.execCommand("copy");
      }
      setFeedback(shareFeedback, "Link copiado.");
    } catch {
      setFeedback(shareFeedback, "Não foi possível copiar. Selecione o link manualmente.", true);
    }
  });

  const nativeShareButton = document.querySelector("[data-native-share]");
  if (nativeShareButton instanceof HTMLButtonElement && typeof navigator.share === "function") {
    nativeShareButton.hidden = false;
    nativeShareButton.addEventListener("click", async () => {
      try {
        await navigator.share({ title: shareTitle, url: canonicalUrl });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setFeedback(shareFeedback, "Não foi possível abrir o compartilhamento do dispositivo.", true);
      }
    });
  }

  /* Comentários */
  const commentForm = document.getElementById("sobre-comment-form");
  const commentBody = document.getElementById("comment-body");
  const characterCount = document.querySelector("[data-comment-character-count]");
  const commentFeedback = document.querySelector("[data-comment-feedback]");
  const commentSubmit = document.querySelector("[data-comment-submit]");
  const commentsList = document.querySelector("[data-comments-list]");
  const commentsEmpty = document.querySelector("[data-comments-empty]");
  const commentsMore = document.querySelector("[data-comments-more]");
  const commentsTotal = document.querySelector("[data-comments-total]");
  if (commentsTotal) commentsTotal.textContent = numberFormatter.format(Number(commentsTotal.textContent || 0));

  const updateCharacterCount = () => {
    if (!(commentBody instanceof HTMLTextAreaElement) || !characterCount) return;
    characterCount.textContent = String(commentBody.value.length);
  };
  commentBody?.addEventListener("input", updateCharacterCount);
  updateCharacterCount();

  const buildCommentElement = (comment) => {
    const article = document.createElement("article");
    article.className = "comment-item";
    article.dataset.commentId = String(comment.id);

    const meta = document.createElement("div");
    meta.className = "comment-meta";
    const name = document.createElement("strong");
    name.textContent = String(comment.name || "");
    const time = document.createElement("time");
    time.textContent = String(comment.date || "");
    meta.append(name, time);

    const body = document.createElement("p");
    body.textContent = String(comment.body || "");
    article.append(meta, body);
    return article;
  };

  const updateCommentsTotal = (value) => {
    if (commentsTotal) commentsTotal.textContent = numberFormatter.format(Number(value || 0));
  };

  commentForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!(commentForm instanceof HTMLFormElement) || !commentForm.reportValidity()) return;

    const formData = new FormData(commentForm);
    const payload = {
      name: String(formData.get("name") || ""),
      email: String(formData.get("email") || ""),
      comment: String(formData.get("comment") || ""),
      website: String(formData.get("website") || ""),
    };

    if (commentSubmit instanceof HTMLButtonElement) commentSubmit.disabled = true;
    setFeedback(commentFeedback, "Publicando...");

    try {
      const response = await fetch("/api/sobre/comments", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "Não foi possível publicar o comentário.");

      if (commentsList instanceof HTMLElement) {
        const previousVisible = commentsList.children.length;
        commentsList.prepend(buildCommentElement(result.comment));
        if (previousVisible <= 5 && commentsList.children.length > 5) {
          commentsList.lastElementChild?.remove();
          commentsMore?.classList.remove("is-hidden");
        }
      }
      commentsEmpty?.classList.add("is-hidden");
      updateCommentsTotal(result.stats?.comments || 0);
      if (commentBody instanceof HTMLTextAreaElement) commentBody.value = "";
      updateCharacterCount();
      setFeedback(commentFeedback, "Comentário publicado.");
    } catch (error) {
      setFeedback(commentFeedback, error instanceof Error ? error.message : "Não foi possível publicar o comentário.", true);
    } finally {
      if (commentSubmit instanceof HTMLButtonElement) commentSubmit.disabled = false;
    }
  });

  commentsMore?.addEventListener("click", async () => {
    if (!(commentsMore instanceof HTMLButtonElement)) return;
    const offset = Number(commentsMore.dataset.commentsOffset || 0);
    commentsMore.disabled = true;
    commentsMore.textContent = "Carregando...";

    try {
      const response = await fetch(`/api/sobre/comments?offset=${offset}&limit=5`);
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "Não foi possível carregar os comentários.");

      if (commentsList instanceof HTMLElement) {
        const existingIds = new Set(Array.from(commentsList.querySelectorAll("[data-comment-id]")).map((item) => item.getAttribute("data-comment-id")));
        result.comments.forEach((comment) => {
          if (!existingIds.has(String(comment.id))) commentsList.append(buildCommentElement(comment));
        });
      }
      commentsMore.dataset.commentsOffset = String(Number(result.offset || 0) + Number(result.comments?.length || 0));
      commentsMore.classList.toggle("is-hidden", !result.has_more);
    } catch (error) {
      setFeedback(commentFeedback, error instanceof Error ? error.message : "Não foi possível carregar os comentários.", true);
    } finally {
      commentsMore.disabled = false;
      commentsMore.textContent = "Ver mais";
    }
  });
})();
