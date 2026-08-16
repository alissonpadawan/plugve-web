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
    const chars = String(value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!chars) return "";
    const prefix = PREFIXES.has(chars[0]) ? chars[0] : "";
    if (!prefix) return "";
    let date = "";
    let suffix = "";
    for (const char of chars.slice(1)) {
      if (date.length < 8) {
        if (/\d/.test(char)) date += char;
        continue;
      }
      if (suffix.length < 10 && SUFFIX_CHARS.has(char)) suffix += char;
    }
    let formatted = `${prefix}-`;
    if (date) formatted += date;
    if (date.length === 8) formatted += `-${suffix}`;
    return formatted.slice(0, 21);
  }
  function clearError(){ if(error) error.textContent=""; input.removeAttribute("aria-invalid"); }
  function setError(message){ if(error) error.textContent=message; input.setAttribute("aria-invalid","true"); }
  function openSearch(){ previousFocus=document.activeElement; overlay.hidden=false; overlay.setAttribute("aria-hidden","false"); document.body.classList.add("result-search-open"); clearError(); requestAnimationFrame(()=>input.focus()); }
  function closeSearch(){ overlay.hidden=true; overlay.setAttribute("aria-hidden","true"); document.body.classList.remove("result-search-open"); clearError(); if(previousFocus && typeof previousFocus.focus==="function") previousFocus.focus(); }
  function submitSearch(){ const code=formatResultCode(input.value); input.value=code; if(!COMPLETE_RE.test(code)){ setError("Digite um código CurVE completo."); return; } clearError(); window.location.assign(`/resultado/${encodeURIComponent(code)}`); }
  trigger.addEventListener("click",openSearch);
  closeButton?.addEventListener("click",closeSearch);
  overlay.addEventListener("click",event=>{ if(event.target===overlay) closeSearch(); });
  dialog.addEventListener("click",event=>event.stopPropagation());
  input.addEventListener("input",()=>{ input.value=formatResultCode(input.value); clearError(); });
  input.addEventListener("paste",()=>setTimeout(()=>{ input.value=formatResultCode(input.value); clearError(); },0));
  input.addEventListener("keydown",event=>{ if(event.key==="Enter"){ event.preventDefault(); submitSearch(); } });
  document.addEventListener("keydown",event=>{ if(event.key==="Escape" && !overlay.hidden) closeSearch(); });
})();
