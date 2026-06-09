let ultimoResumoDepreciacao = null;
let painelDepreciacaoDados = null;
let modelosComCurva = new Set();

function textoSeguro(valor) {
  return valor === null || valor === undefined || valor === "" ? "-" : String(valor);
}

function atualizarStatusResultado(texto, classe) {
  const el = document.getElementById("resultado_status");
  if (!el) return;
  el.textContent = texto;
  el.className = classe || "muted";
}

function mostrarResultadoArea(mostrar = true) {
  document.getElementById("resultado_area")?.classList.toggle("hidden", !mostrar);
}

function mostrarAuditoriaArea(mostrar = true) {
  document.getElementById("auditoria_area")?.classList.toggle("hidden", !mostrar);
}

function atualizarFeedbackCalculo(texto, percentual, mostrar = true) {
  const box = document.getElementById("calculo_feedback");
  const txt = document.getElementById("progress_text");
  const fill = document.getElementById("progress_fill");
  if (box) box.classList.toggle("hidden", !mostrar);
  if (txt) txt.textContent = texto || "";
  if (fill) fill.style.width = `${Math.max(0, Math.min(100, Number(percentual || 0)))}%`;
}

function limparResumo() {
  ["res_valor_atual", "res_valor_futuro", "res_depreciacao", "res_taxa", "res_confianca", "res_origem", "res_tipo_usado"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "-";
  });
  configurarBotoesResultado(false, false);
  mostrarAuditoriaArea(false);
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
    btnCalcular.textContent = "Calcular depreciação";
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
  td.textContent = textoSeguro(valor);
  tr.appendChild(th);
  tr.appendChild(td);
  return tr;
}


function montarRelatorioTextual(data, origem = "curva") {
  const detalhes = data?.detalhes || {};
  const veiculo = detalhes.veiculo || ultimoDetalheFipe || {};
  const modelo = veiculo.modelo || detalhes.modelo || data?.modelo || "veículo selecionado";
  const marca = veiculo.marca || detalhes.marca || data?.marca || "";
  const horizonte = Number(data?.horizonte_anos || document.getElementById("horizonte_anos")?.value || 5);
  const valorAtual = Number(data?.valor_atual || veiculo.valor_atual || 0);
  const valorFuturo = Number(data?.valor_futuro || 0);
  const taxa = Number(data?.taxa_anual_percentual || 0);
  const dep = Number(data?.depreciacao_percentual || 0);
  const confianca = data?.confianca || detalhes.confianca || "-";
  const pontos = data?.pontos_historicos || detalhes.pontos_historicos || "-";
  const janela = data?.janela_historica_meses || detalhes.janela_historica_meses || "-";
  const origemFinal = data?.origem_curva || detalhes.origem_curva || origem || "curva cadastrada";

  const perda = valorAtual && valorFuturo ? valorAtual - valorFuturo : 0;
  const linhas = [];
  linhas.push("RELATÓRIO TÉCNICO DE AUDITORIA DA DEPRECIAÇÃO");
  linhas.push("");
  linhas.push(`Veículo analisado: ${[marca, modelo].filter(Boolean).join(" ") || "veículo selecionado"}.`);
  linhas.push(`Horizonte da análise: ${horizonte} ano(s).`);
  linhas.push(`Valor FIPE inicial: ${valorAtual ? formatarMoedaBR(valorAtual) : "não informado"}.`);
  linhas.push(`Valor estimado ao final do horizonte: ${valorFuturo ? formatarMoedaBR(valorFuturo) : "não disponível"}.`);
  linhas.push(`Perda econômica estimada no período: ${perda > 0 ? formatarMoedaBR(perda) : "não disponível"}.`);
  linhas.push(`Depreciação acumulada: ${dep ? dep.toFixed(2).replace(".", ",") + "%" : "não disponível"}.`);
  linhas.push(`Taxa média anual utilizada: ${taxa ? taxa.toFixed(2).replace(".", ",") + "% a.a." : "não disponível"}.`);
  linhas.push("");
  linhas.push(`Origem técnica da curva: ${origemFinal}.`);
  linhas.push(`Nível de confiança: ${confianca}.`);
  linhas.push(`Pontos históricos considerados: ${pontos}.`);
  linhas.push(`Janela histórica observada: ${janela !== "-" ? janela + " meses" : "não informada"}.`);
  linhas.push("");
  linhas.push("Interpretação: o gráfico de barras compara o valor inicial do veículo com os valores futuros estimados nos cenários base, otimista e pessimista. A curva de depreciação mostra a evolução do valor ao longo do tempo, permitindo validar visualmente a taxa aplicada antes de transportar a informação para o TCO.");
  return linhas.join("\n");
}

function preencherRelatorioTextual(data, origem = "curva") {
  const el = document.getElementById("relatorio_textual");
  if (!el) return;
  el.textContent = montarRelatorioTextual(data, origem);
}

function preencherRelatorio(data, origem = "curva") {
  preencherRelatorioTextual(data, origem);
  const corpo = document.getElementById("detalhes_corpo");
  if (!corpo) return;

  const detalhes = data?.detalhes || {};
  const curva = detalhes.curva || {};
  const familia = detalhes.familia || {};
  const auditoria = detalhes.auditoria_historico || data?.motor?.auditoria_historico || {};

  corpo.innerHTML = "";
  corpo.appendChild(montarLinhaDetalhe("Resultado", data?.mensagem || "Curva carregada."));
  corpo.appendChild(montarLinhaDetalhe("Tipo utilizado", detalhes.tipo_label || data?.tipo_label || data?.tipo_curva));
  corpo.appendChild(montarLinhaDetalhe("Origem", data?.origem_curva || detalhes.origem_curva || origem));
  corpo.appendChild(montarLinhaDetalhe("Confiança", data?.confianca || detalhes.confianca));
  corpo.appendChild(montarLinhaDetalhe("Taxa anual", data?.taxa_anual_percentual ? `${Number(data.taxa_anual_percentual).toFixed(2).replace(".", ",")}% a.a.` : "-"));
  corpo.appendChild(montarLinhaDetalhe("Pontos históricos", data?.pontos_historicos || detalhes.pontos_historicos));
  corpo.appendChild(montarLinhaDetalhe("Janela histórica", data?.janela_historica_meses ? `${data.janela_historica_meses} meses` : detalhes.janela_historica_meses ? `${detalhes.janela_historica_meses} meses` : "-"));
  corpo.appendChild(montarLinhaDetalhe("Período inicial", detalhes.periodo_inicial || curva.periodo_inicial));
  corpo.appendChild(montarLinhaDetalhe("Período final", detalhes.periodo_final || curva.periodo_final));
  corpo.appendChild(montarLinhaDetalhe("Família", familia.family_nome || curva.family_nome || familia.family_id || curva.family_id));
  corpo.appendChild(montarLinhaDetalhe("Modelo base", curva.modelo_base_curva || familia.modelo_base_curva || familia.modelo_base_curva_eletrico || familia.modelo_base_curva_combustao));
  corpo.appendChild(montarLinhaDetalhe("Ano base", curva.ano_base_curva || familia.ano_base_curva || familia.ano_base_curva_eletrico || familia.ano_base_curva_combustao));
  corpo.appendChild(montarLinhaDetalhe("Ano usado como proxy", curva.ano_modelo_proxy || auditoria.ano_modelo_proxy));
  corpo.appendChild(montarLinhaDetalhe("Código ano proxy", curva.codigo_ano_proxy || auditoria.codigo_ano_proxy));
  corpo.appendChild(montarLinhaDetalhe("Nome proxy", curva.nome_proxy || auditoria.nome_proxy));

  if (Object.keys(auditoria).length > 0) {
    corpo.appendChild(montarLinhaDetalhe("Primeiro valor histórico", auditoria.primeiro_valor != null ? formatarMoedaBR(auditoria.primeiro_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Último valor histórico", auditoria.ultimo_valor != null ? formatarMoedaBR(auditoria.ultimo_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Menor valor histórico", auditoria.menor_valor != null ? formatarMoedaBR(auditoria.menor_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Maior valor histórico", auditoria.maior_valor != null ? formatarMoedaBR(auditoria.maior_valor) : "-"));
    corpo.appendChild(montarLinhaDetalhe("Variação total", auditoria.variacao_total_percentual != null ? `${Number(auditoria.variacao_total_percentual).toFixed(2).replace(".", ",")}%` : "-"));
    corpo.appendChild(montarLinhaDetalhe("Zero km detectado", auditoria.zero_km_detectado || auditoria.zero_km_original ? "Sim" : "Não"));
    corpo.appendChild(montarLinhaDetalhe("Proxy aplicado", auditoria.proxy_aplicado ? "Sim" : "Não"));
    corpo.appendChild(montarLinhaDetalhe("Método da taxa", auditoria.metodo_taxa));
    corpo.appendChild(montarLinhaDetalhe("Status da série", auditoria.status_serie));
  }
}

function mostrarDetalhes() {
  if (!ultimoResumoDepreciacao) return;
  mostrarAuditoriaArea(true);
  preencherRelatorio(ultimoResumoDepreciacao, "curva salva");
  renderizarGraficosDepreciacao(ultimoResumoDepreciacao);
  document.getElementById("auditoria_area")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function consultarResumoDepreciacao(detalheFipe) {
  if (!detalheFipe) return;

  mostrarResultadoArea(true);
  mostrarAuditoriaArea(false);
  atualizarFeedbackCalculo("Buscando curva salva na base local...", 25, true);
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
      atualizarFeedbackCalculo("Curva salva encontrada. Gerando relatório técnico...", 100, false);
      atualizarStatusResultado(`✓ ${data.mensagem || "Curva salva encontrada."}`, "encontrado");
      preencherResumo(data);
      configurarBotoesResultado(true, false);
      mostrarAuditoriaArea(true);
      preencherRelatorio(data, "curva salva");
      renderizarGraficosDepreciacao(data);
      if (estaEmModoBridgeTCO()) mostrarDetalhes();
    } else {
      atualizarFeedbackCalculo("Curva não encontrada. Cálculo sob demanda liberado.", 100, false);
      atualizarStatusResultado((data.mensagem || "Curva não encontrada.") + " Clique em Calcular depreciação para gerar e salvar a curva.", "nao-encontrado");
      document.getElementById("res_valor_atual").textContent = formatarMoedaBR(data.valor_atual || detalheFipe.valor_atual);
      document.getElementById("res_tipo_usado").textContent = data.detalhes?.tipo_label || data.tipo_curva || "-";
      configurarBotoesResultado(false, true);
    }
  } catch (e) {
    ultimoResumoDepreciacao = null;
    atualizarFeedbackCalculo("Erro ao consultar depreciação.", 100, false);
    atualizarStatusResultado("Erro ao consultar depreciação.", "erro");
    configurarBotoesResultado(false, false);
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
  if (!temMarca) return atualizarStatusResultado("Não encontrei a marca no seletor FIPE. Faça a seleção manualmente.", "erro");

  document.getElementById("fipe_marca").value = payload.codigo_marca;
  await carregarModelosFipe();

  const temModelo = await aguardarOpcaoSelect("fipe_modelo", payload.codigo_modelo);
  if (!temModelo) return atualizarStatusResultado("Não encontrei o modelo no seletor FIPE. Faça a seleção manualmente.", "erro");

  document.getElementById("fipe_modelo").value = payload.codigo_modelo;
  await carregarAnosFipe();

  const temAno = await aguardarOpcaoSelect("fipe_ano", payload.codigo_ano);
  if (!temAno) return atualizarStatusResultado("Não encontrei o ano/combustível no seletor FIPE. Faça a seleção manualmente.", "erro");

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
    window.opener.postMessage({ tipo: "plugve_depreciacao_validada", prefixo, resultado }, "*");
  }

  window.close();
  atualizarStatusResultado("Resultado enviado ao TCO. Você pode fechar esta aba.", "encontrado");
}

function montarPayloadDepreciacao() {
  if (!ultimoDetalheFipe) return null;
  return {
    ...ultimoDetalheFipe,
    tipo: document.getElementById("tipo_veiculo")?.value || "auto",
    horizonte_anos: document.getElementById("horizonte_anos")?.value || 5
  };
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
    btn.textContent = "Calculando...";
  }

  mostrarResultadoArea(true);
  mostrarAuditoriaArea(false);
  atualizarFeedbackCalculo("Consultando histórico FIPE e preparando cálculo...", 18, true);
  atualizarStatusResultado("Calculando depreciação sob demanda...", "muted");

  try {
    setTimeout(() => atualizarFeedbackCalculo("Buscando série histórica compatível...", 45, true), 350);
    setTimeout(() => atualizarFeedbackCalculo("Calculando taxa anual, valor futuro e confiança...", 72, true), 900);

    const resp = await fetch("/api/depreciacao/calcular", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await resp.json();

    if (data.ok) {
      atualizarFeedbackCalculo("Curva calculada e salva. Montando relatório final...", 100, true);
      if (data.resultado) {
        ultimoResumoDepreciacao = data.resultado;
        atualizarStatusResultado(`✓ ${data.mensagem || "Curva calculada e salva."}`, "encontrado");
        preencherResumo(data.resultado);
        configurarBotoesResultado(true, false);
        mostrarAuditoriaArea(true);
        preencherRelatorio({ ...data.resultado, motor: data.motor }, "cálculo sob demanda");
        renderizarGraficosDepreciacao(data.resultado);
      }
      carregarStatusBases();
      setTimeout(() => atualizarFeedbackCalculo("", 0, false), 1500);
    } else {
      atualizarFeedbackCalculo("Cálculo bloqueado. Verifique o relatório técnico abaixo.", 100, true);
      atualizarStatusResultado(data.mensagem || "Falha ao calcular curva.", "erro");
      mostrarAuditoriaArea(true);
      preencherRelatorio({ ...(data.resultado || {}), mensagem: data.mensagem, detalhes: {}, motor: data.motor }, "cálculo bloqueado");
    }
  } catch (e) {
    atualizarFeedbackCalculo("Erro ao chamar o cálculo sob demanda.", 100, true);
    atualizarStatusResultado("Erro ao chamar o cálculo sob demanda.", "erro");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Calcular depreciação";
    }
  }
}

function formatarPercentualBR(valor, casas = 2) {
  const n = Number(valor || 0);
  if (!Number.isFinite(n) || n <= 0) return "-";
  return `${n.toFixed(casas).replace(".", ",")}%`;
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
  set("side_modelos", status.modelos_cadastrados || 0);
  set("side_marcas", status.marcas_cadastradas || 0);
  set("side_familias", status.familias_cadastradas || 0);
  set("side_curvas", (Number(status.curvas_combustao || 0) + Number(status.curvas_eletrico || 0)));
  set("side_historicos", (Number(status.historico_combustao || 0) + Number(status.historico_eletrico || 0)));

  const texto = `Bases carregadas: ${status.curvas_combustao || 0} curvas combustão, ${status.curvas_eletrico || 0} curvas elétricas, ${status.modelos_cadastrados || 0} modelos cadastrados.`;
  const box = document.getElementById("status_bases");
  if (box) box.textContent = texto;
}

function normalizarBusca(txt) {
  return String(txt || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

function registrarModelosComCurva(lista) {
  modelosComCurva = new Set();
  (lista || []).forEach(item => {
    const modelo = normalizarBusca(item.modelo || item.titulo || "");
    const titulo = normalizarBusca(item.titulo || "");
    if (modelo) modelosComCurva.add(modelo);
    if (titulo) modelosComCurva.add(titulo);
  });
  window.PLUGVE_MODELOS_COM_CURVA = modelosComCurva;
  if (typeof window.aplicarChecksModelosFipe === "function") window.aplicarChecksModelosFipe();
}

function modeloTemCurva(textoModelo) {
  const alvo = normalizarBusca(textoModelo);
  if (!alvo) return false;
  for (const salvo of modelosComCurva) {
    if (alvo.includes(salvo) || salvo.includes(alvo)) return true;
  }
  return false;
}

function renderizarListaCurvasLateral(lista) {
  const box = document.getElementById("lista_curvas_lateral");
  if (!box) return;
  box.innerHTML = "";

  const itens = (lista || []).slice(0, 180);
  if (!itens.length) {
    box.innerHTML = '<div class="muted">Nenhuma curva salva encontrada.</div>';
    return;
  }

  itens.forEach(item => {
    const div = document.createElement("div");
    div.className = "saved-item";
    div.dataset.busca = normalizarBusca(`${item.tipo} ${item.titulo} ${item.codigo_fipe} ${item.confianca} ${item.origem}`);
    div.innerHTML = `
      <strong>✓ ${item.titulo || "Curva salva"}</strong>
      <span>${item.tipo === "eletrico" ? "Elétrico" : "Combustão"} | ${item.ano_modelo || "-"} | ${formatarPercentualBR(item.taxa_anual_percentual)} a.a.</span>
      <small>${item.confianca || "-"} | ${item.pontos_historicos || 0} pontos</small>
    `;
    box.appendChild(div);
  });
}

function filtrarListaCurvasLateral() {
  const filtro = normalizarBusca(document.getElementById("filtro_curvas_lateral")?.value || "");
  document.querySelectorAll("#lista_curvas_lateral .saved-item").forEach(item => {
    item.classList.toggle("hidden", filtro && !(item.dataset.busca || "").includes(filtro));
  });
}

async function carregarStatusBases() {
  const statusEl = document.getElementById("status_bases");
  try {
    const resp = await fetch("/api/depreciacao/painel");
    const data = await resp.json();
    painelDepreciacaoDados = data;
    const status = data.status || {};
    const curvas = [...(data.curvas_combustao || []), ...(data.curvas_eletrico || [])];
    atualizarKpisPainel(status);
    registrarModelosComCurva(curvas);
    renderizarListaCurvasLateral(curvas);
  } catch (e) {
    if (statusEl) statusEl.textContent = "Não foi possível carregar o status das bases.";
  }
}

function renderizarGraficosDepreciacao(data) {
  const atual = Number(data?.valor_atual || 0);
  const futuro = Number(data?.valor_futuro || 0);
  const taxa = Number(data?.taxa_anual_percentual || 0);
  const horizonte = Number(data?.horizonte_anos || document.getElementById("horizonte_anos")?.value || 5);

  renderizarGraficoBarras(atual, futuro);
  renderizarGraficoProjecao(atual, taxa, horizonte);
}


function calcularCenarios(valorAtual, taxaAnual, horizonte) {
  const taxa = Number(taxaAnual || 0) / 100.0;
  const anos = Math.max(1, Number(horizonte || 5));
  const taxaOtimista = Math.max(0, taxa * 0.85);
  const taxaPessimista = taxa * 1.15;
  return {
    atual: valorAtual,
    base: valorAtual * Math.pow(1 - taxa, anos),
    otimista: valorAtual * Math.pow(1 - taxaOtimista, anos),
    pessimista: valorAtual * Math.pow(1 - taxaPessimista, anos),
    taxaBase: taxa,
    taxaOtimista,
    taxaPessimista,
    horizonte: anos
  };
}

function renderizarGraficoBarras(atual, futuro) {
  const el = document.getElementById("grafico_barras");
  if (!el) return;
  el.classList.remove("empty-chart");
  el.innerHTML = "";

  const taxa = Number(ultimoResumoDepreciacao?.taxa_anual_percentual || 0);
  const horizonte = Number(ultimoResumoDepreciacao?.horizonte_anos || document.getElementById("horizonte_anos")?.value || 5);

  if (!atual || !taxa) {
    el.classList.add("empty-chart");
    el.textContent = "Valor futuro ainda não disponível.";
    return;
  }

  const cen = calcularCenarios(atual, taxa, horizonte);
  const itens = [
    { label: "Inicial", valor: cen.atual },
    { label: "Base", valor: futuro || cen.base },
    { label: "Otimista", valor: cen.otimista },
    { label: "Pessimista", valor: cen.pessimista }
  ];
  const max = Math.max(...itens.map(i => i.valor), 1);
  const chart = document.createElement("div");
  chart.className = "bar-chart-grid";

  itens.forEach(item => {
    const wrap = document.createElement("div");
    wrap.className = "bar-chart-item";
    const value = document.createElement("div");
    value.className = "bar-chart-value";
    value.textContent = formatarMoedaBR(item.valor);
    const bar = document.createElement("div");
    bar.className = "bar-chart-bar";
    bar.style.height = `${Math.max(10, (item.valor / max) * 210)}px`;
    const label = document.createElement("div");
    label.className = "bar-chart-label";
    label.textContent = item.label;
    wrap.appendChild(value);
    wrap.appendChild(bar);
    wrap.appendChild(label);
    chart.appendChild(wrap);
  });
  el.appendChild(chart);
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

  const cen = calcularCenarios(valorAtual, taxaAnual, horizonte);
  const anos = Array.from({ length: cen.horizonte + 1 }, (_, i) => i);
  const series = [
    { nome: "Base", taxa: cen.taxaBase, classe: "base" },
    { nome: "Otimista", taxa: cen.taxaOtimista, classe: "otimista" },
    { nome: "Pessimista", taxa: cen.taxaPessimista, classe: "pessimista" }
  ].map(serie => ({
    ...serie,
    pontos: anos.map(ano => ({ ano, valor: valorAtual * Math.pow(1 - serie.taxa, ano) }))
  }));

  const todos = series.flatMap(s => s.pontos.map(p => p.valor));
  const min = Math.min(...todos);
  const max = Math.max(...todos);
  const w = 760, h = 300, padL = 72, padR = 24, padT = 28, padB = 48;
  const x = ano => padL + (ano / Math.max(1, cen.horizonte)) * (w - padL - padR);
  const y = valor => padT + ((max - valor) / Math.max(1, max - min)) * (h - padT - padB);

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "line-chart-svg");

  const axis = document.createElementNS(svgNS, "path");
  axis.setAttribute("d", `M${padL} ${padT} V${h-padB} H${w-padR}`);
  axis.setAttribute("class", "chart-axis");
  svg.appendChild(axis);

  [0, Math.ceil(cen.horizonte / 2), cen.horizonte].forEach(ano => {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", x(ano));
    t.setAttribute("y", h - 18);
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("class", "chart-label-svg");
    t.textContent = ano === 0 ? "Atual" : `${ano}a`;
    svg.appendChild(t);
  });

  [max, min].forEach((valor, idx) => {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", padL - 10);
    t.setAttribute("y", idx === 0 ? padT + 4 : h - padB);
    t.setAttribute("text-anchor", "end");
    t.setAttribute("class", "chart-label-svg");
    t.textContent = formatarMoedaBR(valor).replace(",00", "");
    svg.appendChild(t);
  });

  series.forEach(serie => {
    const d = serie.pontos.map((p, idx) => `${idx === 0 ? "M" : "L"}${x(p.ano).toFixed(1)} ${y(p.valor).toFixed(1)}`).join(" ");
    const path = document.createElementNS(svgNS, "path");
    path.setAttribute("d", d);
    path.setAttribute("class", `line-series ${serie.classe}`);
    svg.appendChild(path);

    const last = serie.pontos[serie.pontos.length - 1];
    const txt = document.createElementNS(svgNS, "text");
    txt.setAttribute("x", x(last.ano) - 4);
    txt.setAttribute("y", y(last.valor) - 8);
    txt.setAttribute("text-anchor", "end");
    txt.setAttribute("class", `chart-label-svg label-${serie.classe}`);
    txt.textContent = serie.nome;
    svg.appendChild(txt);
  });

  const legenda = document.createElement("div");
  legenda.className = "chart-legend";
  legenda.innerHTML = `
    <span><b class="dot base"></b>Base</span>
    <span><b class="dot otimista"></b>Otimista</span>
    <span><b class="dot pessimista"></b>Pessimista</span>
  `;

  const tabela = document.createElement("div");
  tabela.className = "projection-summary";
  tabela.innerHTML = `
    <div><span>Valor inicial</span><strong>${formatarMoedaBR(valorAtual)}</strong></div>
    <div><span>Base final</span><strong>${formatarMoedaBR(cen.base)}</strong></div>
    <div><span>Otimista final</span><strong>${formatarMoedaBR(cen.otimista)}</strong></div>
    <div><span>Pessimista final</span><strong>${formatarMoedaBR(cen.pessimista)}</strong></div>
  `;

  el.appendChild(svg);
  el.appendChild(legenda);
  el.appendChild(tabela);
}

function aplicarChecksModelosFipe() {
  const select = document.getElementById("fipe_modelo");
  if (!select) return;
  Array.from(select.options || []).forEach(opt => {
    if (!opt.value || opt.dataset.checkAplicado === "1") return;
    const nomeOriginal = opt.dataset.nome || opt.textContent || "";
    if (modeloTemCurva(nomeOriginal)) {
      opt.textContent = `✓ ${nomeOriginal}`;
      opt.dataset.checkAplicado = "1";
    }
  });
}
window.aplicarChecksModelosFipe = aplicarChecksModelosFipe;

// Pequeno gancho para reaplicar os checks depois que o fipe.js carrega os modelos.
const carregarModelosOriginalDep = window.carregarModelosFipe;
if (typeof carregarModelosOriginalDep === "function") {
  window.carregarModelosFipe = async function() {
    const retorno = await carregarModelosOriginalDep.apply(this, arguments);
    aplicarChecksModelosFipe();
    return retorno;
  };
}

document.addEventListener("DOMContentLoaded", () => {
  mostrarResultadoArea(false);
  mostrarAuditoriaArea(false);
  carregarStatusBases();

  document.getElementById("tipo_veiculo")?.addEventListener("change", () => {
    if (ultimoDetalheFipe) consultarResumoDepreciacao(ultimoDetalheFipe);
  });

  document.getElementById("horizonte_anos")?.addEventListener("change", () => {
    const el = document.getElementById("horizonte_anos");
    if (el && Number(el.value || 0) < 1) el.value = 1;
    if (ultimoDetalheFipe) consultarResumoDepreciacao(ultimoDetalheFipe);
  });

  document.getElementById("btn_ver_detalhes")?.addEventListener("click", mostrarDetalhes);
  document.getElementById("btn_usar_no_tco")?.addEventListener("click", usarResultadoNoTCOEFechar);
  document.getElementById("btn_calcular_futuro")?.addEventListener("click", solicitarCalculoSobDemanda);
  document.getElementById("filtro_curvas_lateral")?.addEventListener("input", filtrarListaCurvasLateral);

  setTimeout(inicializarBridgeTCO, 500);
});
