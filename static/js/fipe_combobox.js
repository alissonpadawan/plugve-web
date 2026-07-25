(function () {
  "use strict";

  const SELECTOR = [
    "select#fipe_marca",
    "select#fipe_modelo",
    "select#ve_marca",
    "select#ve_modelo",
    "select#icev_marca",
    "select#icev_modelo",
    "select#atual_marca",
    "select#atual_modelo",
    "select[data-fipe-combobox='1']"
  ].join(",");

  const instancias = new WeakMap();
  let instanciaAberta = null;

  function normalizar(texto) {
    return String(texto || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  function normalizarChaveMarcador(texto) {
    return String(texto || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function limparMarcadorCurva(texto) {
    return String(texto || "").replace(/^\s*[✓✔≈]\s*/u, "").trim();
  }

  function textoOpcao(option) {
    if (!option) return "";
    return limparMarcadorCurva(option.dataset.nome || option.dataset.nomeOriginal || option.textContent || option.label || "");
  }

  function opcaoSelecionada(select) {
    return select.options[select.selectedIndex] || select.querySelector("option:checked") || select.options[0] || null;
  }

  function fecharInstancia(inst) {
    if (!inst) return;
    inst.wrapper.classList.remove("open");
    inst.button.setAttribute("aria-expanded", "false");
    inst.search.value = "";
  }

  function fecharAberta() {
    if (instanciaAberta) fecharInstancia(instanciaAberta);
    instanciaAberta = null;
  }

  function optionTemDestaqueZero(option) {
    const peso = String(option?.style?.fontWeight || "");
    return option?.dataset?.temZeroKm === "1" || peso === "700" || peso === "800" || peso === "bold";
  }

  function optionPendente(option) {
    const cls = String(option?.className || "");
    return option?.dataset?.varrida === "0" || cls.includes("marca-pendente-varredura") || option?.dataset?.modeloNovo === "1";
  }

  function marcadorGlobalOption(option) {
    if (!option || !option.value) return null;
    const servico = window.CurVE?.marcadores;
    if (servico?.obterPorOption) {
      const marcador = servico.obterPorOption(option);
      if (marcador) return marcador;
    }
    const porCodigo = window.PLUGVE_MARCADORES_CURVAS_CODIGO;
    const codigo = String(option.value || "").trim();
    if (codigo && porCodigo && typeof porCodigo.has === "function" && porCodigo.has(codigo)) {
      return porCodigo.get(codigo);
    }
    const porNome = window.PLUGVE_MARCADORES_CURVAS;
    const nome = normalizarChaveMarcador(textoOpcao(option));
    if (nome && porNome && typeof porNome.has === "function" && porNome.has(nome)) {
      return porNome.get(nome);
    }
    return null;
  }

  function optionTemCurvaSalva(option) {
    if (!option || !option.value) return false;
    return option.dataset.curvaSalva === "1" || Boolean(marcadorGlobalOption(option)) || /^\s*[✓✔≈]\s*/u.test(option.textContent || "");
  }

  function tipoCurvaOption(option) {
    const tipo = String(option?.dataset?.tipoCurva || "").toLowerCase();
    if (tipo === "similaridade") return "similaridade";
    const marcador = marcadorGlobalOption(option);
    const tipoMarcador = String(marcador?.tipo_curva || marcador?.tipo_curva_aplicada || (marcador?.curva_por_similaridade ? "similaridade" : "")).toLowerCase();
    if (tipoMarcador === "similaridade") return "similaridade";
    return optionTemCurvaSalva(option) ? "propria" : "";
  }

  function simboloCurvaOption(option) {
    const tipo = tipoCurvaOption(option);
    if (tipo === "similaridade") return "";
    return tipo === "propria" ? "✓" : "";
  }

  function atualizarBotao(inst) {
    const select = inst.select;
    const option = opcaoSelecionada(select);
    const texto = textoOpcao(option) || select.dataset.placeholder || "Selecione";
    const semValor = !select.value;

    const temCurva = !!option && optionTemCurvaSalva(option);
    const simbolo = simboloCurvaOption(option);
    inst.label.textContent = temCurva && simbolo ? `${simbolo} ${texto}` : texto;
    inst.button.disabled = !!select.disabled;
    inst.wrapper.classList.toggle("is-disabled", !!select.disabled);
    inst.wrapper.classList.toggle("has-value", !semValor);
    inst.wrapper.classList.toggle("has-placeholder", semValor);
    inst.wrapper.classList.toggle("selected-zero-km", !!option && optionTemDestaqueZero(option));
    inst.wrapper.classList.toggle("selected-pending", !!option && optionPendente(option));
    inst.wrapper.classList.toggle("selected-saved-curve", temCurva);
  }

  function montarItem(inst, option) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "fipe-combobox-option";
    item.setAttribute("role", "option");
    item.dataset.value = option.value || "";
    item.disabled = !!option.disabled;
    const tipoCurva = tipoCurvaOption(option);
    const simboloCurva = simboloCurvaOption(option);
    item.title = option.title || (tipoCurva === "similaridade" && option.dataset.modeloReferencia
      ? `${textoOpcao(option)} — curva herdada de ${option.dataset.modeloReferencia}`
      : textoOpcao(option));

    if (optionTemCurvaSalva(option) && simboloCurva) {
      const marker = document.createElement("span");
      marker.className = "fipe-combobox-curve-check";
      marker.textContent = simboloCurva;
      marker.setAttribute("aria-hidden", "true");
      item.appendChild(marker);
    }

    const label = document.createElement("span");
    label.className = "fipe-combobox-option-text";
    label.textContent = textoOpcao(option) || "Selecione";
    item.appendChild(label);

    if (option.value === inst.select.value) {
      item.classList.add("is-selected");
      item.setAttribute("aria-selected", "true");
    } else {
      item.setAttribute("aria-selected", "false");
    }
    if (optionTemDestaqueZero(option)) item.classList.add("is-zero-km");
    if (optionPendente(option)) item.classList.add("is-pending");
    if (optionTemCurvaSalva(option)) item.classList.add("is-saved-curve");
    if (tipoCurva === "similaridade") item.classList.add("is-similarity-curve");

    item.addEventListener("click", () => {
      if (item.disabled) return;
      const valorAnterior = inst.select.value;
      inst.select.value = option.value;
      atualizarBotao(inst);
      inst.renderizarLista("");
      fecharAberta();
      inst.button.focus({ preventScroll: true });
      if (inst.select.value !== valorAnterior || option.value === "") {
        inst.select.dispatchEvent(new Event("input", { bubbles: true }));
        inst.select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    item.addEventListener("keydown", (ev) => {
      const itens = Array.from(inst.list.querySelectorAll(".fipe-combobox-option:not(:disabled)"));
      const idx = itens.indexOf(item);
      if (ev.key === "ArrowDown") {
        ev.preventDefault();
        (itens[idx + 1] || itens[0])?.focus();
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        (itens[idx - 1] || itens[itens.length - 1])?.focus();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        fecharAberta();
        inst.button.focus({ preventScroll: true });
      }
    });

    return item;
  }

  function criarInstancia(select) {
    if (!select || instancias.has(select) || select.dataset.fipeComboboxEnhanced === "1") return null;

    select.classList.add("fipe-native-select-hidden");
    select.dataset.fipeComboboxEnhanced = "1";

    const wrapper = document.createElement("div");
    wrapper.className = "fipe-combobox";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "fipe-combobox-toggle";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");

    const label = document.createElement("span");
    label.className = "fipe-combobox-label";
    label.textContent = "Selecione";

    const caret = document.createElement("span");
    caret.className = "fipe-combobox-caret";
    caret.setAttribute("aria-hidden", "true");
    caret.textContent = "▾";

    button.appendChild(label);
    button.appendChild(caret);

    const panel = document.createElement("div");
    panel.className = "fipe-combobox-panel";

    const searchWrap = document.createElement("div");
    searchWrap.className = "fipe-combobox-search-wrap";

    const search = document.createElement("input");
    search.type = "search";
    search.className = "fipe-combobox-search";
    search.autocomplete = "off";
    search.spellcheck = false;
    search.placeholder = "Pesquisar";

    const icon = document.createElement("span");
    icon.className = "fipe-combobox-search-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "";

    searchWrap.appendChild(search);
    searchWrap.appendChild(icon);

    const list = document.createElement("div");
    list.className = "fipe-combobox-list";
    list.setAttribute("role", "listbox");

    panel.appendChild(searchWrap);
    panel.appendChild(list);
    wrapper.appendChild(button);
    wrapper.appendChild(panel);
    select.insertAdjacentElement("afterend", wrapper);

    const inst = {
      select,
      wrapper,
      button,
      label,
      panel,
      search,
      list,
      renderizarLista: null
    };

    inst.renderizarLista = function (termo) {
      const filtro = normalizar(termo);
      list.innerHTML = "";
      const options = Array.from(select.options || []);
      const filtradas = options.filter((option) => {
        const texto = textoOpcao(option);
        if (!filtro) return true;
        return normalizar(texto).includes(filtro) || normalizar(option.value).includes(filtro);
      });

      if (!filtradas.length) {
        const vazio = document.createElement("div");
        vazio.className = "fipe-combobox-empty";
        vazio.textContent = "Nenhuma opção encontrada";
        list.appendChild(vazio);
        return;
      }

      filtradas.forEach((option) => list.appendChild(montarItem(inst, option)));
    };

    function abrir() {
      if (select.disabled) return;
      // Reaplica os marcadores no momento da abertura. O combobox deve
      // renderizar a verdade única do endpoint de marcadores, não depender
      // de texto/cache de cada página.
      try {
        window.CurVE?.marcadores?.aplicarNoSelect?.(select);
        window.aplicarChecksModelosFipe?.();
        window.CurVE?.marcadores?.carregar?.().then(() => {
          window.CurVE?.marcadores?.aplicarNoSelect?.(select);
          atualizarBotao(inst);
          if (wrapper.classList.contains("open")) inst.renderizarLista(search.value || "");
        });
      } catch (e) {}
      if (instanciaAberta && instanciaAberta !== inst) fecharInstancia(instanciaAberta);
      const jaAberta = wrapper.classList.contains("open");
      if (jaAberta) {
        fecharAberta();
        return;
      }
      atualizarBotao(inst);
      inst.renderizarLista("");
      wrapper.classList.add("open");
      button.setAttribute("aria-expanded", "true");
      instanciaAberta = inst;
      window.requestAnimationFrame(() => {
        search.focus({ preventScroll: true });
        search.select();
      });
    }

    button.addEventListener("click", abrir);
    button.addEventListener("keydown", (ev) => {
      if (["Enter", " ", "ArrowDown"].includes(ev.key)) {
        ev.preventDefault();
        abrir();
      }
    });

    search.addEventListener("input", () => inst.renderizarLista(search.value));
    search.addEventListener("keydown", (ev) => {
      const itens = Array.from(list.querySelectorAll(".fipe-combobox-option:not(:disabled)"));
      if (ev.key === "Escape") {
        ev.preventDefault();
        fecharAberta();
        button.focus({ preventScroll: true });
      } else if (ev.key === "ArrowDown") {
        ev.preventDefault();
        itens[0]?.focus();
      } else if (ev.key === "Enter" && itens.length === 1) {
        ev.preventDefault();
        itens[0].click();
      }
    });

    select.addEventListener("change", () => {
      atualizarBotao(inst);
      if (wrapper.classList.contains("open")) inst.renderizarLista(search.value);
    });

    const observer = new MutationObserver(() => {
      atualizarBotao(inst);
      if (wrapper.classList.contains("open")) inst.renderizarLista(search.value);
    });
    observer.observe(select, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
      attributeFilter: ["disabled", "class", "style", "title", "data-nome", "data-nome-original", "data-tem-zero-km", "data-varrida", "data-modelo-novo", "data-curva-salva", "data-tipo-curva", "data-modelo-referencia", "data-chave-curva-referencia", "selected"]
    });

    select.form?.addEventListener("reset", () => {
      window.setTimeout(() => atualizarBotao(inst), 0);
    });

    instancias.set(select, inst);
    atualizarBotao(inst);
    return inst;
  }

  function aplicarComboboxes(root) {
    const escopo = root && root.querySelectorAll ? root : document;
    escopo.querySelectorAll(SELECTOR).forEach(criarInstancia);
  }

  document.addEventListener("click", (ev) => {
    if (!instanciaAberta) return;
    if (!instanciaAberta.wrapper.contains(ev.target)) fecharAberta();
  });

  function inicializarComboboxesFipeCurVE() {
    aplicarComboboxes(document);
    const obs = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType !== 1) return;
          if (node.matches?.(SELECTOR)) criarInstancia(node);
          aplicarComboboxes(node);
        });
      }
    });
    if (document.body) obs.observe(document.body, { childList: true, subtree: true });
  }

  document.addEventListener("curve:marcadores-curvas:atualizados", () => {
    try { window.CurVE?.marcadores?.aplicarNosSelects?.(); } catch (e) {}
    try { window.atualizarComboboxesFipeCurVE?.(); } catch (e) {}
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", inicializarComboboxesFipeCurVE);
  } else {
    inicializarComboboxesFipeCurVE();
  }

  window.atualizarComboboxesFipeCurVE = function () {
    aplicarComboboxes(document);
    document.querySelectorAll(SELECTOR).forEach((select) => {
      const inst = instancias.get(select);
      if (!inst) return;
      atualizarBotao(inst);
      if (inst.wrapper.classList.contains("open")) {
        inst.renderizarLista(inst.search.value || "");
      }
    });
  };
})();
