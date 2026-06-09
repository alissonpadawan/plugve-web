let ultimoResumoDepreciacao = null;

function atualizarStatusResultado(texto, classe) {
  const el = document.getElementById("resultado_status");
  if (!el) return;
  el.textContent = texto;
  el.className = classe || "muted";
}

function limparResumo() {
  document.getElementById("res_valor_atual").textContent = "-";
  document.getElementById("res_valor_futuro").textContent = "-";
  document.getElementById("res_depreciacao").textContent = "-";
  document.getElementById("res_taxa").textContent = "-";
  document.getElementById("res_confianca").textContent = "-";
  document.getElementById("res_origem").textContent = "-";
  document.getElementById("res_tipo_usado").textContent = "-";
  esconderDetalhes();
  configurarBotoesResultado(false, false);
}

function configurarBotoesResultado(curvaEncontrada, podeCalcularFuturo) {
  const btnDetalhes = document.getElementById("btn_ver_detalhes");
  const btnCalcular = document.getElementById("btn_calcular_futuro");
  const btnUsarTCO = document.getElementById("btn_usar_no_tco");

  if (btnDetalhes) {
    btnDetalhes.classList.toggle("hidden", !curvaEncontrada);
    btnDetalhes.disabled = !curvaEncontrada;
  }

  if (btnCalcular) {
    btnCalcular.classList.toggle("hidden", !podeCalcularFuturo);
    btnCalcular.disabled = !podeCalcularFuturo;
    if (podeCalcularFuturo) btnCalcular.textContent = "Calcular depreciação e salvar curva";
  }

  if (btnUsarTCO) {
    const modoTCO = estaEmModoBridgeTCO();
    btnUsarTCO.classList.toggle("hidden", !(modoTCO && curvaEncontrada));
    btnUsarTCO.disabled = !(modoTCO && curvaEncontrada);
  }
}

function preencherResumo(data) {
  document.getElementById("res_valor_atual").textContent = formatarMoedaBR(data.valor_atual);
  document.getElementById("res_valor_futuro").textContent = data.valor_futuro != null && Number(data.valor_futuro) > 0 ? formatarMoedaBR(data.valor_futuro) : "-";
  document.getElementById("res_depreciacao").textContent = data.depreciacao_percentual != null && Number(data.depreciacao_percentual) > 0 ? `${Number(data.depreciacao_percentual).toFixed(2).replace(".", ",")}%` : "-";
  document.getElementById("res_taxa").textContent = data.taxa_anual_percentual != null && Number(data.taxa_anual_percentual) > 0 ? `${Number(data.taxa_anual_percentual).toFixed(2).replace(".", ",")}% a.a.` : "-";
  document.getElementById("res_confianca").textContent = data.confianca || "-";
  document.getElementById("res_origem").textContent = data.origem_curva || "-";
  document.getElementById("res_tipo_usado").textContent = data.detalhes?.tipo_label || data.tipo_curva || "-";
}

function montarLinhaDetalhe(rotulo, valor) {
  const tr = document.createElement("tr");
  const th = document.createElement("th");
  const td = document.createElement("td");
  th.textContent = rotulo;
  td.textContent = valor || "-";
  tr.appendChild(th);
  tr.appendChild(td);
  return tr;
}

function mostrarDetalhes() {
  const box = document.getElementById("detalhes_resultado");
  const corpo = document.getElementById("detalhes_corpo");
  if (!box || !corpo || !ultimoResumoDepreciacao) return;

  const detalhes = ultimoResumoDepreciacao.detalhes || {};
  const curva = detalhes.curva || {};
  const familia = detalhes.familia || {};

  corpo.innerHTML = "";
  corpo.appendChild(montarLinhaDetalhe("Tipo utilizado", detalhes.tipo_label || ultimoResumoDepreciacao.tipo_curva));
  corpo.appendChild(montarLinhaDetalhe("Tipo de match", detalhes.tipo_match || curva.tipo_match));
  corpo.appendChild(montarLinhaDetalhe("Ano usado como proxy", curva.ano_modelo_proxy || "-"));
  corpo.appendChild(montarLinhaDetalhe("Código ano proxy", curva.codigo_ano_proxy || "-"));
  corpo.appendChild(montarLinhaDetalhe("Nome proxy", curva.nome_proxy || "-"));
  corpo.appendChild(montarLinhaDetalhe("Origem", ultimoResumoDepreciacao.origem_curva));
  corpo.appendChild(montarLinhaDetalhe("Confiança", ultimoResumoDepreciacao.confianca));
  corpo.appendChild(montarLinhaDetalhe("Pontos históricos", ultimoResumoDepreciacao.pontos_historicos));
  corpo.appendChild(montarLinhaDetalhe("Janela histórica", ultimoResumoDepreciacao.janela_historica_meses ? `${ultimoResumoDepreciacao.janela_historica_meses} meses` : "-"));
  corpo.appendChild(montarLinhaDetalhe("Período inicial", detalhes.periodo_inicial || curva.periodo_inicial));
  corpo.appendChild(montarLinhaDetalhe("Período final", detalhes.periodo_final || curva.periodo_final));
  corpo.appendChild(montarLinhaDetalhe("Família", familia.family_nome || curva.family_nome || familia.family_id || curva.family_id));
  corpo.appendChild(montarLinhaDetalhe("Modelo base", curva.modelo_base_curva || familia.modelo_base_curva || familia.modelo_base_curva_eletrico || familia.modelo_base_curva_combustao));
  corpo.appendChild(montarLinhaDetalhe("Ano base", curva.ano_base_curva || familia.ano_base_curva || familia.ano_base_curva_eletrico || familia.ano_base_curva_combustao));
  corpo.appendChild(montarLinhaDetalhe("Fonte de ajuste", curva.fonte_ajuste));
  corpo.appendChild(montarLinhaDetalhe("Status da curva", curva.status_final || curva.confianca_ev));

  const auditoria = detalhes.auditoria_historico || {};
  if (Object.keys(auditoria).length > 0) {
    corpo.appendChild(montarLinhaDetalhe("Primeiro valor histórico", auditoria.primeiro_valor != null ? formatarMoedaBR(auditoria.primeiro_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Último valor histórico", auditoria.ultimo_valor != null ? formatarMoedaBR(auditoria.ultimo_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Variação total", auditoria.variacao_total_percentual != null ? `${Number(auditoria.variacao_total_percentual).toFixed(2).replace(".", ",")}%` : "-"));
    corpo.appendChild(montarLinhaDetalhe("Método da taxa", auditoria.metodo_taxa));
    corpo.appendChild(montarLinhaDetalhe("Status da série", auditoria.status_serie));
  }

  box.classList.remove("hidden");
}

function esconderDetalhes() {
  const box = document.getElementById("detalhes_resultado");
  if (box) box.classList.add("hidden");
}

async function consultarResumoDepreciacao(detalheFipe) {
  if (!detalheFipe) return;

  atualizarStatusResultado("Buscando curva salva...", "muted");
  limparResumo();

  const payload = {
    ...detalheFipe,
    tipo: document.getElementById("tipo_veiculo")?.value || "auto",
    horizonte_anos: document.getElementById("horizonte_anos")?.value || 5
  };

  try {
    const resp = await fetch("/api/depreciacao/resumo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    ultimoResumoDepreciacao = data;

    if (data.encontrado) {
      atualizarStatusResultado(`✓ ${data.mensagem || "Curva salva encontrada."}`, "encontrado");
      preencherResumo(data);
      configurarBotoesResultado(true, false);
      if (estaEmModoBridgeTCO()) {
        definirAbaAtiva("auditoria");
        mostrarDetalhes();
      }
    } else {
      atualizarStatusResultado((data.mensagem || "Curva não encontrada.") + " Clique em Calcular depreciação para gerar e salvar a curva quando houver histórico suficiente.", "nao-encontrado");
      document.getElementById("res_valor_atual").textContent = formatarMoedaBR(data.valor_atual || detalheFipe.valor_atual);
      document.getElementById("res_tipo_usado").textContent = data.detalhes?.tipo_label || data.tipo_curva || "-";
      configurarBotoesResultado(false, true);
    }
  } catch (e) {
    ultimoResumoDepreciacao = null;
    atualizarStatusResultado("Erro ao consultar depreciação.", "erro");
    configurarBotoesResultado(false, false);
  }
}

async function carregarStatusBases() {
  const el = document.getElementById("status_bases");
  if (!el) return;
  try {
    const resp = await fetch("/api/depreciacao/status");
    const data = await resp.json();
    el.textContent = `Bases: ${data.curvas_combustao || 0} curvas combustão, ${data.curvas_eletrico || 0} curvas elétricas.`;
  } catch (e) {
    el.textContent = "Não foi possível carregar o status das bases.";
  }
}


function montarPayloadDepreciacao() {
  if (!ultimoDetalheFipe) return null;
  return {
    ...ultimoDetalheFipe,
    tipo: document.getElementById("tipo_veiculo")?.value || "auto",
    horizonte_anos: document.getElementById("horizonte_anos")?.value || 5
  };
}

function mostrarRetornoCalculo(data) {
  const box = document.getElementById("detalhes_resultado");
  const corpo = document.getElementById("detalhes_corpo");
  if (!box || !corpo) return;

  const motor = data.motor || {};
  corpo.innerHTML = "";
  corpo.appendChild(montarLinhaDetalhe("Status", data.status || "-"));
  corpo.appendChild(montarLinhaDetalhe("Mensagem", data.mensagem || "-"));
  corpo.appendChild(montarLinhaDetalhe("Tipo detectado", data.tipo_detectado || "-"));
  corpo.appendChild(montarLinhaDetalhe("Tipo utilizado", data.tipo_label || data.tipo_utilizado || "-"));
  corpo.appendChild(montarLinhaDetalhe("Taxa anual calculada", motor.taxa_anual_percentual != null ? `${Number(motor.taxa_anual_percentual).toFixed(2).replace(".", ",")}% a.a.` : "-"));
  corpo.appendChild(montarLinhaDetalhe("Pontos históricos", motor.pontos_historicos));
  corpo.appendChild(montarLinhaDetalhe("Janela histórica", motor.janela_historica_meses ? `${motor.janela_historica_meses} meses` : "-"));
  corpo.appendChild(montarLinhaDetalhe("Período inicial", motor.periodo_inicial));
  corpo.appendChild(montarLinhaDetalhe("Período final", motor.periodo_final));
  const auditoria = motor.auditoria_historico || {};
  if (Object.keys(auditoria).length > 0) {
    corpo.appendChild(montarLinhaDetalhe("Primeiro valor histórico", auditoria.primeiro_valor != null ? formatarMoedaBR(auditoria.primeiro_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Último valor histórico", auditoria.ultimo_valor != null ? formatarMoedaBR(auditoria.ultimo_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Menor valor histórico", auditoria.menor_valor != null ? formatarMoedaBR(auditoria.menor_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Maior valor histórico", auditoria.maior_valor != null ? formatarMoedaBR(auditoria.maior_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Variação total", auditoria.variacao_total_percentual != null ? `${Number(auditoria.variacao_total_percentual).toFixed(2).replace(".", ",")}%` : "-"));
    corpo.appendChild(montarLinhaDetalhe("Zero km detectado", auditoria.zero_km_detectado ? "Sim" : "Não"));
    corpo.appendChild(montarLinhaDetalhe("Proxy aplicado", auditoria.proxy_aplicado ? "Sim" : "Não"));
    corpo.appendChild(montarLinhaDetalhe("Ano usado como proxy", auditoria.ano_modelo_proxy || "-"));
    corpo.appendChild(montarLinhaDetalhe("Código ano proxy", auditoria.codigo_ano_proxy || "-"));
    corpo.appendChild(montarLinhaDetalhe("Nome proxy", auditoria.nome_proxy || "-"));
    corpo.appendChild(montarLinhaDetalhe("Método da taxa", auditoria.metodo_taxa));
    corpo.appendChild(montarLinhaDetalhe("Status da série", auditoria.status_serie));
    corpo.appendChild(montarLinhaDetalhe("Intervalos com queda", auditoria.intervalos_queda));
    corpo.appendChild(montarLinhaDetalhe("Intervalos com alta", auditoria.intervalos_alta));
  }

  corpo.appendChild(montarLinhaDetalhe("Próxima etapa", data.proxima_etapa || "-"));

  if (Array.isArray(data.etapas_previstas)) {
    corpo.appendChild(montarLinhaDetalhe("Fluxo preparado", data.etapas_previstas.join(" | ")));
  }

  box.classList.remove("hidden");
}

async function solicitarCalculoSobDemanda() {
  const payload = montarPayloadDepreciacao();
  if (!payload) {
    atualizarStatusResultado("Selecione um veículo antes de calcular.", "erro");
    return;
  }

  const btn = document.getElementById("btn_calcular_futuro");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Preparando cálculo...";
  }

  atualizarStatusResultado("Preparando estrutura do cálculo sob demanda...", "muted");

  try {
    const resp = await fetch("/api/depreciacao/calcular", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await resp.json();

    if (data.ok) {
      atualizarStatusResultado(`✓ ${data.mensagem || "Curva calculada e salva."}`, "encontrado");
      if (data.resultado) {
        ultimoResumoDepreciacao = data.resultado;
        preencherResumo(data.resultado);
        configurarBotoesResultado(true, false);
      }
      definirAbaAtiva("auditoria");
      mostrarRetornoCalculo(data);
    } else {
      atualizarStatusResultado(data.mensagem || "Falha ao calcular curva.", "erro");
      mostrarRetornoCalculo(data);
    }
  } catch (e) {
    atualizarStatusResultado("Erro ao chamar o cálculo sob demanda.", "erro");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Calcular depreciação e salvar curva";
    }
  }
}


function obterParametroUrl(nome) {
  return new URLSearchParams(window.location.search).get(nome);
}

function estaEmModoBridgeTCO() {
  return obterParametroUrl("bridge") === "tco" && !!obterParametroUrl("prefixo");
}

function obterPrefixoTCO() {
  return obterParametroUrl("prefixo") || "";
}

function obterPayloadTCOBridge() {
  const prefixo = obterPrefixoTCO();
  if (!prefixo) return null;
  try {
    return JSON.parse(sessionStorage.getItem(`plugve_tco_depreciacao_${prefixo}`) || "null");
  } catch (e) {
    return null;
  }
}

function aguardarOpcaoSelect(selectId, valor, tentativas = 80) {
  return new Promise((resolve) => {
    let contador = 0;
    const timer = setInterval(() => {
      const el = document.getElementById(selectId);
      if (!el) {
        clearInterval(timer);
        resolve(false);
        return;
      }
      const existe = Array.from(el.options || []).some(opt => String(opt.value) === String(valor));
      if (existe || contador >= tentativas) {
        clearInterval(timer);
        resolve(existe);
      }
      contador += 1;
    }, 100);
  });
}

async function inicializarBridgeTCO() {
  if (!estaEmModoBridgeTCO()) return;
  const payload = obterPayloadTCOBridge();
  if (!payload) {
    atualizarStatusResultado("Não foi possível recuperar o veículo vindo do TCO. Volte ao simulador e abra novamente.", "erro");
    return;
  }

  atualizarStatusResultado("Veículo recebido do TCO. Carregando seleção FIPE...", "muted");

  const tipo = document.getElementById("tipo_veiculo");
  const horizonte = document.getElementById("horizonte_anos");
  if (tipo) tipo.value = payload.tipo || "auto";
  if (horizonte && payload.horizonte_anos) horizonte.value = String(payload.horizonte_anos);

  const temMarca = await aguardarOpcaoSelect("fipe_marca", payload.codigo_marca);
  if (!temMarca) {
    atualizarStatusResultado("Não encontrei a marca no seletor FIPE. Faça a seleção manualmente.", "erro");
    return;
  }

  document.getElementById("fipe_marca").value = payload.codigo_marca;
  await carregarModelosFipe();

  const temModelo = await aguardarOpcaoSelect("fipe_modelo", payload.codigo_modelo);
  if (!temModelo) {
    atualizarStatusResultado("Não encontrei o modelo no seletor FIPE. Faça a seleção manualmente.", "erro");
    return;
  }

  document.getElementById("fipe_modelo").value = payload.codigo_modelo;
  await carregarAnosFipe();

  const temAno = await aguardarOpcaoSelect("fipe_ano", payload.codigo_ano);
  if (!temAno) {
    atualizarStatusResultado("Não encontrei o ano/combustível no seletor FIPE. Faça a seleção manualmente.", "erro");
    return;
  }

  document.getElementById("fipe_ano").value = payload.codigo_ano;
  await consultarPrecoFipe();
}

function montarResultadoParaTCO() {
  if (!ultimoResumoDepreciacao || !ultimoResumoDepreciacao.encontrado) return null;
  return {
    taxa_anual_percentual: ultimoResumoDepreciacao.taxa_anual_percentual,
    depreciacao_percentual: ultimoResumoDepreciacao.depreciacao_percentual,
    valor_atual: ultimoResumoDepreciacao.valor_atual,
    valor_futuro: ultimoResumoDepreciacao.valor_futuro,
    confianca: ultimoResumoDepreciacao.confianca,
    origem_curva: ultimoResumoDepreciacao.origem_curva,
    tipo_curva: ultimoResumoDepreciacao.tipo_curva,
    status: ultimoResumoDepreciacao.status,
    mensagem: ultimoResumoDepreciacao.mensagem
  };
}

function usarResultadoNoTCOEFechar() {
  const prefixo = obterPrefixoTCO();
  const resultado = montarResultadoParaTCO();
  if (!prefixo || !resultado) {
    atualizarStatusResultado("Ainda não existe depreciação validada para enviar ao TCO.", "erro");
    return;
  }

  localStorage.setItem(`plugve_depreciacao_validada_${prefixo}`, JSON.stringify(resultado));

  if (window.opener) {
    window.opener.postMessage({
      tipo: "plugve_depreciacao_validada",
      prefixo: prefixo,
      resultado: resultado
    }, "*");
  }

  window.close();
  atualizarStatusResultado("Resultado enviado ao TCO. Você pode fechar esta aba.", "encontrado");
}


document.addEventListener("DOMContentLoaded", () => {
  carregarStatusBases();

  document.getElementById("tipo_veiculo")?.addEventListener("change", () => {
    if (ultimoDetalheFipe) consultarResumoDepreciacao(ultimoDetalheFipe);
  });

  document.getElementById("horizonte_anos")?.addEventListener("change", () => {
    if (ultimoDetalheFipe) consultarResumoDepreciacao(ultimoDetalheFipe);
  });

  document.getElementById("btn_ver_detalhes")?.addEventListener("click", mostrarDetalhes);
  document.getElementById("btn_usar_no_tco")?.addEventListener("click", usarResultadoNoTCOEFechar);
  document.getElementById("btn_calcular_futuro")?.addEventListener("click", solicitarCalculoSobDemanda);
  document.getElementById("btn_fechar_detalhes")?.addEventListener("click", esconderDetalhes);

  setTimeout(inicializarBridgeTCO, 500);
});

// ============================================================
// Painel web de depreciação - visão mais próxima do programa original
// ============================================================
let painelDepreciacaoDados = null;

function formatarPercentualBR(valor, casas = 2) {
  const n = Number(valor || 0);
  if (!Number.isFinite(n) || n <= 0) return "-";
  return `${n.toFixed(casas).replace(".", ",")}%`;
}

function definirAbaAtiva(nome) {
  document.querySelectorAll(".tab-button").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === nome);
  });
  document.querySelectorAll(".tab-panel").forEach(panel => {
    panel.classList.add("hidden");
  });
  const alvo = document.getElementById(`tab_${nome}`);
  if (alvo) alvo.classList.remove("hidden");
}

function atualizarKpisPainel(status) {
  const set = (id, valor) => {
    const el = document.getElementById(id);
    if (el) el.textContent = valor ?? "-";
  };
  set("kpi_modelos", status.modelos_cadastrados || 0);
  set("kpi_curvas_combustao", status.curvas_combustao || 0);
  set("kpi_curvas_eletrico", status.curvas_eletrico || 0);
  set("kpi_hist_combustao", status.historico_combustao || 0);
  set("kpi_hist_eletrico", status.historico_eletrico || 0);

  const texto = `Bases: ${status.curvas_combustao || 0} curvas combustão, ${status.curvas_eletrico || 0} curvas elétricas, ${status.modelos_cadastrados || 0} modelos cadastrados.`;
  const box = document.getElementById("status_bases");
  const boxConsulta = document.getElementById("status_bases_consulta");
  if (box) box.textContent = texto;
  if (boxConsulta) boxConsulta.textContent = texto;
}

function montarCelula(texto) {
  const td = document.createElement("td");
  td.textContent = texto || "-";
  return td;
}

function montarBadge(texto) {
  const span = document.createElement("span");
  span.className = "badge";
  span.textContent = texto || "-";
  return span;
}

function renderizarTabelaCurvas(lista) {
  const tbody = document.getElementById("tabela_curvas_corpo");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!lista || lista.length === 0) {
    const tr = document.createElement("tr");
    tr.appendChild(montarCelula("Nenhuma curva encontrada."));
    tr.firstChild.colSpan = 8;
    tbody.appendChild(tr);
    return;
  }

  lista.slice(0, 120).forEach(item => {
    const tr = document.createElement("tr");
    const tdTipo = document.createElement("td");
    tdTipo.appendChild(montarBadge(item.tipo === "eletrico" ? "Elétrico" : "Combustão"));
    tr.appendChild(tdTipo);
    tr.appendChild(montarCelula(item.titulo));
    tr.appendChild(montarCelula(item.ano_modelo));
    tr.appendChild(montarCelula(formatarPercentualBR(item.taxa_anual_percentual)));
    tr.appendChild(montarCelula(item.confianca));
    tr.appendChild(montarCelula(item.pontos_historicos));
    tr.appendChild(montarCelula(item.janela_historica_meses ? `${item.janela_historica_meses} meses` : "-"));
    tr.appendChild(montarCelula(item.origem));
    tr.dataset.busca = `${item.tipo} ${item.titulo} ${item.codigo_fipe} ${item.confianca} ${item.origem}`.toLowerCase();
    tbody.appendChild(tr);
  });
}

function renderizarTabelaHistoricos(lista) {
  const tbody = document.getElementById("tabela_historicos_corpo");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!lista || lista.length === 0) {
    const tr = document.createElement("tr");
    tr.appendChild(montarCelula("Nenhum histórico encontrado."));
    tr.firstChild.colSpan = 8;
    tbody.appendChild(tr);
    return;
  }

  lista.slice(0, 120).forEach(item => {
    const tr = document.createElement("tr");
    const tdTipo = document.createElement("td");
    tdTipo.appendChild(montarBadge(item.tipo === "eletrico" ? "Elétrico" : "Combustão"));
    tr.appendChild(tdTipo);
    tr.appendChild(montarCelula(item.titulo));
    tr.appendChild(montarCelula(item.codigo_fipe));
    tr.appendChild(montarCelula(item.codigo_ano));
    tr.appendChild(montarCelula(item.pontos));
    tr.appendChild(montarCelula(`${item.periodo_inicial || "-"} a ${item.periodo_final || "-"}`));
    tr.appendChild(montarCelula(item.primeiro_valor ? formatarMoedaBR(item.primeiro_valor) : "-"));
    tr.appendChild(montarCelula(item.ultimo_valor ? formatarMoedaBR(item.ultimo_valor) : "-"));
    tbody.appendChild(tr);
  });
}

function filtrarTabelaCurvas() {
  const filtro = (document.getElementById("filtro_curvas")?.value || "").toLowerCase().trim();
  document.querySelectorAll("#tabela_curvas_corpo tr").forEach(tr => {
    if (!filtro) {
      tr.classList.remove("hidden");
      return;
    }
    tr.classList.toggle("hidden", !(tr.dataset.busca || "").includes(filtro));
  });
}

async function carregarStatusBases() {
  const statusEl = document.getElementById("status_bases");
  const statusConsultaEl = document.getElementById("status_bases_consulta");
  try {
    const resp = await fetch("/api/depreciacao/painel");
    const data = await resp.json();
    painelDepreciacaoDados = data;
    const status = data.status || {};
    atualizarKpisPainel(status);
    renderizarTabelaCurvas([...(data.curvas_combustao || []), ...(data.curvas_eletrico || [])]);
    renderizarTabelaHistoricos([...(data.historico_combustao || []), ...(data.historico_eletrico || [])]);
  } catch (e) {
    if (statusEl) statusEl.textContent = "Não foi possível carregar o painel de bases.";
    if (statusConsultaEl) statusConsultaEl.textContent = "Não foi possível carregar o painel de bases.";
  }
}

function preencherResumo(data) {
  document.getElementById("res_valor_atual").textContent = formatarMoedaBR(data.valor_atual);
  document.getElementById("res_valor_futuro").textContent = data.valor_futuro != null && Number(data.valor_futuro) > 0 ? formatarMoedaBR(data.valor_futuro) : "-";
  document.getElementById("res_depreciacao").textContent = formatarPercentualBR(data.depreciacao_percentual);
  document.getElementById("res_taxa").textContent = data.taxa_anual_percentual != null && Number(data.taxa_anual_percentual) > 0 ? `${Number(data.taxa_anual_percentual).toFixed(2).replace(".", ",")}% a.a.` : "-";
  document.getElementById("res_confianca").textContent = data.confianca || "-";
  document.getElementById("res_origem").textContent = data.origem_curva || "-";
  document.getElementById("res_tipo_usado").textContent = data.detalhes?.tipo_label || data.tipo_curva || "-";
  renderizarGraficosDepreciacao(data);
}

function renderizarGraficosDepreciacao(data) {
  const atual = Number(data?.valor_atual || 0);
  const futuro = Number(data?.valor_futuro || 0);
  const taxa = Number(data?.taxa_anual_percentual || 0);
  const horizonte = Number(data?.horizonte_anos || document.getElementById("horizonte_anos")?.value || 5);

  renderizarGraficoBarras(atual, futuro);
  renderizarGraficoProjecao(atual, taxa, horizonte);
}

function renderizarGraficoBarras(atual, futuro) {
  const el = document.getElementById("grafico_barras");
  if (!el) return;
  el.classList.remove("empty-chart");
  el.innerHTML = "";

  if (!atual || !futuro) {
    el.classList.add("empty-chart");
    el.textContent = "Valor futuro ainda não disponível.";
    return;
  }

  const max = Math.max(atual, futuro, 1);
  [
    { label: "Atual", valor: atual },
    { label: "Futuro", valor: futuro }
  ].forEach(item => {
    const wrap = document.createElement("div");
    wrap.className = "bar-chart-item";
    const value = document.createElement("div");
    value.className = "bar-chart-value";
    value.textContent = formatarMoedaBR(item.valor);
    const bar = document.createElement("div");
    bar.className = "bar-chart-bar";
    bar.style.height = `${Math.max(8, (item.valor / max) * 170)}px`;
    const label = document.createElement("div");
    label.className = "bar-chart-label";
    label.textContent = item.label;
    wrap.appendChild(value);
    wrap.appendChild(bar);
    wrap.appendChild(label);
    el.appendChild(wrap);
  });
}

function renderizarGraficoProjecao(valorAtual, taxaAnual, horizonte) {
  const el = document.getElementById("grafico_projecao");
  if (!el) return;
  el.classList.remove("empty-chart");
  el.innerHTML = "";

  if (!valorAtual || !taxaAnual || !horizonte) {
    el.classList.add("empty-chart");
    el.textContent = "Taxa anual ainda não disponível.";
    return;
  }

  const lista = document.createElement("div");
  lista.className = "proj-list";
  const taxa = taxaAnual / 100.0;
  const valores = [];
  for (let ano = 0; ano <= horizonte; ano += 1) {
    valores.push({ ano, valor: valorAtual * Math.pow(1 - taxa, ano) });
  }
  const max = Math.max(...valores.map(v => v.valor), 1);
  valores.forEach(item => {
    const row = document.createElement("div");
    row.className = "proj-row";
    const label = document.createElement("strong");
    label.textContent = item.ano === 0 ? "Atual" : `Ano ${item.ano}`;
    const track = document.createElement("div");
    track.className = "proj-track";
    const fill = document.createElement("div");
    fill.className = "proj-fill";
    fill.style.width = `${Math.max(4, (item.valor / max) * 100)}%`;
    track.appendChild(fill);
    const value = document.createElement("div");
    value.className = "proj-value";
    value.textContent = formatarMoedaBR(item.valor);
    row.appendChild(label);
    row.appendChild(track);
    row.appendChild(value);
    lista.appendChild(row);
  });
  el.appendChild(lista);
}

function mostrarDetalhes() {
  const box = document.getElementById("detalhes_resultado");
  const corpo = document.getElementById("detalhes_corpo");
  if (!box || !corpo || !ultimoResumoDepreciacao) return;

  const detalhes = ultimoResumoDepreciacao.detalhes || {};
  const curva = detalhes.curva || {};
  const familia = detalhes.familia || {};

  corpo.innerHTML = "";
  corpo.appendChild(montarLinhaDetalhe("Tipo utilizado", detalhes.tipo_label || ultimoResumoDepreciacao.tipo_curva));
  corpo.appendChild(montarLinhaDetalhe("Tipo de match", detalhes.tipo_match || curva.tipo_match));
  corpo.appendChild(montarLinhaDetalhe("Origem", ultimoResumoDepreciacao.origem_curva));
  corpo.appendChild(montarLinhaDetalhe("Confiança", ultimoResumoDepreciacao.confianca));
  corpo.appendChild(montarLinhaDetalhe("Taxa anual", ultimoResumoDepreciacao.taxa_anual_percentual ? `${Number(ultimoResumoDepreciacao.taxa_anual_percentual).toFixed(2).replace(".", ",")}% a.a.` : "-"));
  corpo.appendChild(montarLinhaDetalhe("Pontos históricos", ultimoResumoDepreciacao.pontos_historicos));
  corpo.appendChild(montarLinhaDetalhe("Janela histórica", ultimoResumoDepreciacao.janela_historica_meses ? `${ultimoResumoDepreciacao.janela_historica_meses} meses` : "-"));
  corpo.appendChild(montarLinhaDetalhe("Período inicial", detalhes.periodo_inicial || curva.periodo_inicial));
  corpo.appendChild(montarLinhaDetalhe("Período final", detalhes.periodo_final || curva.periodo_final));
  corpo.appendChild(montarLinhaDetalhe("Família", familia.family_nome || curva.family_nome || familia.family_id || curva.family_id));
  corpo.appendChild(montarLinhaDetalhe("Modelo base", curva.modelo_base_curva || familia.modelo_base_curva || familia.modelo_base_curva_eletrico || familia.modelo_base_curva_combustao));
  corpo.appendChild(montarLinhaDetalhe("Ano base", curva.ano_base_curva || familia.ano_base_curva || familia.ano_base_curva_eletrico || familia.ano_base_curva_combustao));
  corpo.appendChild(montarLinhaDetalhe("Ano usado como proxy", curva.ano_modelo_proxy || "-"));
  corpo.appendChild(montarLinhaDetalhe("Código ano proxy", curva.codigo_ano_proxy || "-"));
  corpo.appendChild(montarLinhaDetalhe("Nome proxy", curva.nome_proxy || "-"));
  corpo.appendChild(montarLinhaDetalhe("Fonte de ajuste", curva.fonte_ajuste));
  corpo.appendChild(montarLinhaDetalhe("Status da curva", curva.status_final || curva.confianca_ev));

  const auditoria = detalhes.auditoria_historico || {};
  if (Object.keys(auditoria).length > 0) {
    corpo.appendChild(montarLinhaDetalhe("Primeiro valor histórico", auditoria.primeiro_valor != null ? formatarMoedaBR(auditoria.primeiro_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Último valor histórico", auditoria.ultimo_valor != null ? formatarMoedaBR(auditoria.ultimo_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Menor valor histórico", auditoria.menor_valor != null ? formatarMoedaBR(auditoria.menor_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Maior valor histórico", auditoria.maior_valor != null ? formatarMoedaBR(auditoria.maior_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Variação total", auditoria.variacao_total_percentual != null ? `${Number(auditoria.variacao_total_percentual).toFixed(2).replace(".", ",")}%` : "-"));
    corpo.appendChild(montarLinhaDetalhe("Método da taxa", auditoria.metodo_taxa));
    corpo.appendChild(montarLinhaDetalhe("Status da série", auditoria.status_serie));
  }

  box.classList.remove("hidden");
  definirAbaAtiva("auditoria");
}

function mostrarRetornoCalculo(data) {
  const box = document.getElementById("detalhes_resultado");
  const corpo = document.getElementById("detalhes_corpo");
  if (!box || !corpo) return;

  const motor = data.motor || {};
  corpo.innerHTML = "";
  corpo.appendChild(montarLinhaDetalhe("Status", data.status || "-"));
  corpo.appendChild(montarLinhaDetalhe("Mensagem", data.mensagem || "-"));
  corpo.appendChild(montarLinhaDetalhe("Tipo detectado", data.tipo_detectado || "-"));
  corpo.appendChild(montarLinhaDetalhe("Tipo utilizado", data.tipo_label || data.tipo_utilizado || "-"));
  corpo.appendChild(montarLinhaDetalhe("Taxa anual calculada", motor.taxa_anual_percentual != null ? `${Number(motor.taxa_anual_percentual).toFixed(2).replace(".", ",")}% a.a.` : "-"));
  corpo.appendChild(montarLinhaDetalhe("Pontos históricos", motor.pontos_historicos));
  corpo.appendChild(montarLinhaDetalhe("Janela histórica", motor.janela_historica_meses ? `${motor.janela_historica_meses} meses` : "-"));
  corpo.appendChild(montarLinhaDetalhe("Período inicial", motor.periodo_inicial));
  corpo.appendChild(montarLinhaDetalhe("Período final", motor.periodo_final));
  const auditoria = motor.auditoria_historico || {};
  if (Object.keys(auditoria).length > 0) {
    corpo.appendChild(montarLinhaDetalhe("Primeiro valor histórico", auditoria.primeiro_valor != null ? formatarMoedaBR(auditoria.primeiro_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Último valor histórico", auditoria.ultimo_valor != null ? formatarMoedaBR(auditoria.ultimo_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Menor valor histórico", auditoria.menor_valor != null ? formatarMoedaBR(auditoria.menor_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Maior valor histórico", auditoria.maior_valor != null ? formatarMoedaBR(auditoria.maior_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Variação total", auditoria.variacao_total_percentual != null ? `${Number(auditoria.variacao_total_percentual).toFixed(2).replace(".", ",")}%` : "-"));
    corpo.appendChild(montarLinhaDetalhe("Zero km detectado", auditoria.zero_km_detectado ? "Sim" : "Não"));
    corpo.appendChild(montarLinhaDetalhe("Proxy aplicado", auditoria.proxy_aplicado ? "Sim" : "Não"));
    corpo.appendChild(montarLinhaDetalhe("Ano usado como proxy", auditoria.ano_modelo_proxy || "-"));
    corpo.appendChild(montarLinhaDetalhe("Código ano proxy", auditoria.codigo_ano_proxy || "-"));
    corpo.appendChild(montarLinhaDetalhe("Nome proxy", auditoria.nome_proxy || "-"));
    corpo.appendChild(montarLinhaDetalhe("Método da taxa", auditoria.metodo_taxa));
    corpo.appendChild(montarLinhaDetalhe("Status da série", auditoria.status_serie));
    corpo.appendChild(montarLinhaDetalhe("Intervalos com queda", auditoria.intervalos_queda));
    corpo.appendChild(montarLinhaDetalhe("Intervalos com alta", auditoria.intervalos_alta));
  }
  corpo.appendChild(montarLinhaDetalhe("Próxima etapa", data.proxima_etapa || "-"));

  if (data.resultado) renderizarGraficosDepreciacao(data.resultado);
  box.classList.remove("hidden");
  definirAbaAtiva("auditoria");
  carregarStatusBases();
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".tab-button").forEach(btn => {
    btn.addEventListener("click", () => definirAbaAtiva(btn.dataset.tab));
  });
  document.getElementById("filtro_curvas")?.addEventListener("input", filtrarTabelaCurvas);
});
