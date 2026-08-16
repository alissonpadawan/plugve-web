(() => {
  "use strict";
  const PREFIXES = new Set(["S", "D", "F"]);
  const SUFFIX_CHARS = new Set("23456789ABCDEFGHJKLMNPQRSTUVWXYZ".split(""));
  const COMPLETE_RE = /^[SDF]-\d{8}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{10}$/;
  const trigger = document.getElementById("result_search_trigger");
  const overlay = document.getElementById("result_search_overlay");
  const dialog = overlay?.querySelector(".result-search-dialog");
  const closeButton = document.getElementById("result_search_close");
  const input = document.getElementById("result_search_input");
  const error = document.getElementById("result_search_error");
  if (!trigger || !overlay || !dialog || !input) return;
  let previousFocus = null;

  function formatResultCode(value) {
    const upper = String(value || "").toUpperCase().replace(/[^A-Z0-9-]/g, "");
    if (!upper) return "";

    let prefix = "";
    let date = "";
    let suffix = "";
    let keepFirstSeparator = false;
    let keepSecondSeparator = false;

    if (upper.includes("-")) {
      const parts = upper.split("-");
      prefix = PREFIXES.has((parts[0] || "")[0]) ? parts[0][0] : "";
      if (!prefix) return "";
      keepFirstSeparator = parts.length >= 2;
      keepSecondSeparator = parts.length >= 3;
      date = (parts[1] || "").replace(/\D/g, "").slice(0, 8);
      suffix = parts.slice(2).join("").split("").filter(char => SUFFIX_CHARS.has(char)).join("").slice(0, 10);
    } else {
      const compact = upper.replace(/[^A-Z0-9]/g, "");
      prefix = PREFIXES.has(compact[0]) ? compact[0] : "";
      if (!prefix) return "";
      const rest = compact.slice(1);
      date = rest.replace(/\D/g, "").slice(0, 8);
      // Na entrada compacta, os 8 primeiros caracteres numéricos formam a data.
      // O restante só vira sufixo depois que a data está completa.
      if (date.length === 8) {
        let numericSeen = 0;
        let remainder = "";
        for (const char of rest) {
          if (numericSeen < 8 && /\d/.test(char)) { numericSeen += 1; continue; }
          remainder += char;
        }
        suffix = remainder.split("").filter(char => SUFFIX_CHARS.has(char)).join("").slice(0, 10);
        keepSecondSeparator = true;
      }
      keepFirstSeparator = rest.length > 0;
    }

    let formatted = prefix;
    if (keepFirstSeparator || date || suffix) formatted += `-${date}`;
    if (keepSecondSeparator || suffix) formatted += `-${suffix}`;
    return formatted.slice(0, 21);
  }

  function tokenCountBefore(value, caret) {
    return (String(value || "").slice(0, Math.max(0, caret || 0)).match(/[A-Z0-9]/gi) || []).length;
  }

  function caretAfterTokenCount(value, tokenCount) {
    if (tokenCount <= 0) return 0;
    let seen = 0;
    for (let i = 0; i < value.length; i += 1) {
      if (/[A-Z0-9]/i.test(value[i])) seen += 1;
      if (seen >= tokenCount) return i + 1;
    }
    return value.length;
  }

  function applyMaskPreservingCaret() {
    const before = input.value;
    const caret = input.selectionStart ?? before.length;
    const tokens = tokenCountBefore(before, caret);
    const formatted = formatResultCode(before);
    input.value = formatted;
    const nextCaret = Math.min(caretAfterTokenCount(formatted, tokens), formatted.length);
    try { input.setSelectionRange(nextCaret, nextCaret); } catch (_) {}
    clearError();
  }

  function deleteAcrossSeparator(direction) {
    const start = input.selectionStart ?? 0;
    const end = input.selectionEnd ?? start;
    if (start !== end) return false;
    const value = input.value;
    if (direction === "backward" && start > 0 && value[start - 1] === "-") {
      const removeAt = start - 2;
      if (removeAt < 0) return false;
      input.value = value.slice(0, removeAt) + value.slice(removeAt + 1);
      const formatted = formatResultCode(input.value);
      input.value = formatted;
      const caret = Math.min(removeAt, formatted.length);
      try { input.setSelectionRange(caret, caret); } catch (_) {}
      clearError();
      return true;
    }
    if (direction === "forward" && start < value.length && value[start] === "-") {
      const removeAt = start + 1;
      input.value = value.slice(0, removeAt) + value.slice(removeAt + 1);
      const formatted = formatResultCode(input.value);
      input.value = formatted;
      const caret = Math.min(start, formatted.length);
      try { input.setSelectionRange(caret, caret); } catch (_) {}
      clearError();
      return true;
    }
    return false;
  }

  function clearError(){ if(error) error.textContent=""; input.removeAttribute("aria-invalid"); }
  function setError(message){ if(error) error.textContent=message; input.setAttribute("aria-invalid","true"); }
  function openSearch(){
    previousFocus=document.activeElement;
    overlay.hidden=false;
    overlay.setAttribute("aria-hidden","false");
    document.body.classList.add("result-search-open");
    clearError();
    requestAnimationFrame(()=>{ input.focus(); input.select(); });
  }
  function closeSearch(){
    overlay.hidden=true;
    overlay.setAttribute("aria-hidden","true");
    document.body.classList.remove("result-search-open");
    input.value="";
    clearError();
    if(previousFocus && typeof previousFocus.focus==="function") previousFocus.focus();
  }
  function submitSearch(){
    const code=formatResultCode(input.value);
    input.value=code;
    if(!COMPLETE_RE.test(code)){ setError("Digite um código CurVE completo."); return; }
    clearError();
    window.location.assign(`/resultado/${encodeURIComponent(code)}`);
  }

  trigger.addEventListener("click",openSearch);
  closeButton?.addEventListener("click",closeSearch);
  overlay.addEventListener("click",event=>{ if(event.target===overlay) closeSearch(); });
  dialog.addEventListener("click",event=>event.stopPropagation());
  input.addEventListener("input",applyMaskPreservingCaret);
  input.addEventListener("paste",()=>setTimeout(applyMaskPreservingCaret,0));
  input.addEventListener("keydown",event=>{
    if(event.key==="Enter"){ event.preventDefault(); submitSearch(); return; }
    if(event.key==="Backspace" && deleteAcrossSeparator("backward")){ event.preventDefault(); return; }
    if(event.key==="Delete" && deleteAcrossSeparator("forward")){ event.preventDefault(); }
  });
  document.addEventListener("keydown",event=>{ if(event.key==="Escape" && !overlay.hidden) closeSearch(); });
})();
