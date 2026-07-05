(function () {
  "use strict";

  const root = window.CurVE = window.CurVE || {};
  const EVENTO_ATUALIZADO = "curve:marcadores-curvas:atualizados";
  const ENDPOINT = "/api/depreciacao/marcadores_curvas?v=20260705_v35_marcadores_unificados";

  const estado = {
    carregado: false,
    carregando: null,
    dados: null,
    porNome: new Map(),
    porCodigo: new Map(),
    modelos: new Set(),
    codigosModelo: new Set()
  };

  function normalizar(valor) {
    return String(valor || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function limparMarcadorTexto(valor) {
    return String(valor || "").replace(/^\s*[✓✔≈]\s*/u, "").trim();
  }

  function nomeOption(option) {
    if (!option) return "";
    return limparMarcadorTexto(option.dataset.nome || option.dataset.nomeOriginal || option.label || option.textContent || "");
  }

  function tipoMarcador(item) {
    const tipo = String(item?.tipo_curva || item?.tipo_curva_aplicada || "").toLowerCase();
    if (tipo === "similaridade" || item?.curva_por_similaridade || item?.similaridade_curva) return "similaridade";
    return item ? "propria" : "";
  }

  function limparCachesAntigos() {
    try {
      const remover = [];
      const prefixos = [
        "curve:depreciacao:marcadores:",
        "plugve:curvas:marcadores:"
      ];
      Object.keys(localStorage || {}).forEach((chave) => {
        if (prefixos.some(prefixo => chave.startsWith(prefixo))) remover.push(chave);
      });
      remover.forEach((chave) => localStorage.removeItem(chave));
    } catch (e) {}
  }

  function registrarChave(chave, marcador) {
    const n = normalizar(chave);
    if (!n) return;
    estado.modelos.add(n);
    estado.porNome.set(n, marcador);
  }

  function registrarDados(data) {
    const itens = Array.isArray(data?.modelos)
      ? data.modelos
      : [...(data?.curvas_combustao || []), ...(data?.curvas_eletrico || [])];

    estado.porNome = new Map();
    estado.porCodigo = new Map();
    estado.modelos = new Set();
    estado.codigosModelo = new Set();

    itens.forEach((item) => {
      if (!item) return;
      const tipo = tipoMarcador(item);
      const marcador = {
        ...item,
        tipo_curva: tipo === "similaridade" ? "similaridade" : "propria",
        simbolo: tipo === "similaridade" ? "" : "✓"
      };

      const titulo = item.titulo || "";
      const marca = item.marca || "";
      const modelo = item.modelo || "";
      registrarChave(titulo, marcador);
      registrarChave(modelo, marcador);
      registrarChave(`${marca || ""} ${modelo || ""}`, marcador);

      const codigoModelo = String(item.codigo_modelo || item.modelo_id || item.model_id || "").trim();
      if (codigoModelo) {
        estado.codigosModelo.add(codigoModelo);
        estado.porCodigo.set(codigoModelo, marcador);
      }
    });

    estado.dados = data || { ok: true, modelos: [] };
    estado.carregado = true;

    // Compatibilidade com scripts antigos do site.
    window.PLUGVE_MODELOS_COM_CURVA = estado.modelos;
    window.PLUGVE_MARCADORES_CURVAS = estado.porNome;
    window.PLUGVE_MARCADORES_CURVAS_CODIGO = estado.porCodigo;

    document.dispatchEvent(new CustomEvent(EVENTO_ATUALIZADO, { detail: { data: estado.dados } }));
    return estado.dados;
  }

  function obter(nomeModelo, codigoModelo) {
    const codigo = String(codigoModelo || "").trim();
    if (codigo && estado.porCodigo.has(codigo)) return estado.porCodigo.get(codigo);
    const nome = normalizar(nomeModelo);
    if (nome && estado.porNome.has(nome)) return estado.porNome.get(nome);
    return null;
  }

  function obterPorOption(option) {
    if (!option || !option.value) return null;
    return obter(nomeOption(option), option.value);
  }

  function aplicarNoOption(option, nomeModelo) {
    if (!option || !option.value) return null;
    const nome = limparMarcadorTexto(nomeModelo || nomeOption(option));
    if (nome) option.dataset.nome = nome;

    const marcador = obter(nome, option.value);
    const temCurva = Boolean(marcador);
    const tipo = tipoMarcador(marcador);
    const simbolo = tipo === "similaridade" ? "" : (temCurva ? "✓" : "");

    option.dataset.curvaSalva = temCurva ? "1" : "0";
    option.dataset.tipoCurva = tipo || "";
    option.dataset.modeloReferencia = marcador?.modelo_referencia || marcador?.modelo_referencia_similaridade || "";
    option.dataset.chaveCurvaReferencia = marcador?.chave_curva_referencia || "";
    option.textContent = `${simbolo ? `${simbolo} ` : ""}${nome || nomeOption(option)}`;

    option.classList.toggle("option-saved-curve", temCurva);
    if (temCurva) {
      option.style.color = "#047857";
      option.style.fontWeight = option.dataset.temZeroKm === "1" ? "900" : "800";
      option.title = tipo === "similaridade" && option.dataset.modeloReferencia
        ? `${nome} — curva herdada de ${option.dataset.modeloReferencia}`
        : `${nome} — curva própria salva`;
    } else {
      option.style.color = "";
      option.style.fontWeight = option.dataset.temZeroKm === "1" ? "800" : "";
      option.title = "";
    }
    return marcador;
  }

  function aplicarNoSelect(select) {
    if (!select) return;
    Array.from(select.options || []).forEach((option) => {
      if (option.value) aplicarNoOption(option);
    });
  }

  function aplicarNosSelects(selects) {
    const lista = Array.isArray(selects) && selects.length
      ? selects
      : Array.from(document.querySelectorAll("select#fipe_modelo, select#ve_modelo, select#icev_modelo, select#atual_modelo, select[data-fipe-modelo='1']"));
    lista.forEach(aplicarNoSelect);
    try { window.atualizarComboboxesFipeCurVE?.(); } catch (e) {}
  }

  function carregar(opcoes = {}) {
    limparCachesAntigos();
    if (estado.carregando && !opcoes.forcar) return estado.carregando;
    if (estado.carregado && !opcoes.forcar) return Promise.resolve(estado.dados);

    estado.carregando = fetch(ENDPOINT, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-cache",
        Pragma: "no-cache"
      }
    })
      .then(resp => resp.ok ? resp.json() : { ok: false, modelos: [] })
      .then(data => {
        if (!data || data.ok === false) return data || { ok: false, modelos: [] };
        const registrado = registrarDados(data);
        aplicarNosSelects();
        return registrado;
      })
      .catch(() => ({ ok: false, modelos: [] }))
      .finally(() => { estado.carregando = null; });
    return estado.carregando;
  }

  root.marcadores = {
    eventoAtualizado: EVENTO_ATUALIZADO,
    estado,
    normalizar,
    limparMarcadorTexto,
    nomeOption,
    registrarDados,
    obter,
    obterPorOption,
    aplicarNoOption,
    aplicarNoSelect,
    aplicarNosSelects,
    carregar
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => carregar());
  } else {
    carregar();
  }
})();
