let ultimoResumoDepreciacao = null;
let ultimoJobDiagnosticoV1917 = null;
let painelDepreciacaoDados = null;
let modelosComCurva = new Set();
let diagnosticoV1917AutoAtivo = false;
let diagnosticoV1917Ciclos = 0;
let terminalV1917Linhas = [];
const DIAGNOSTICO_V1917_MAX_CICLOS = 180;

function textoSeguro(valor) {
  return valor === null || valor === undefined || valor === "" ? "-" : String(valor);
}

function parseMoedaTecnica(valor) {
  if (valor === null || valor === undefined) return 0;
  let txt = String(valor).trim();
  if (!txt) return 0;
  txt = txt.replace(/R\$|\s/g, "").replace(/[^0-9,.-]/g, "");
  if (!txt) return 0;
  const temVirgula = txt.includes(",");
  const temPonto = txt.includes(".");
  if (temVirgula && temPonto) {
    // Aceita tanto 62.452,00 quanto 62,452.00. O último separador indica o decimal.
    if (txt.lastIndexOf(",") > txt.lastIndexOf(".")) {
      txt = txt.replace(/\./g, "").replace(",", ".");
    } else {
      txt = txt.replace(/,/g, "");
    }
  } else if (temVirgula) {
    txt = txt.replace(",", ".");
  }
  const n = Number(txt);
  return Number.isFinite(n) ? n : 0;
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

function mostrarGraficoBarrasArea(mostrar = true) {
  document.getElementById("card_grafico_barras")?.classList.toggle("hidden", !mostrar);
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

function selecionarAbaAuditoriaV1917(aba) {
  const rel = document.getElementById("aba_relatorio_tecnico");
  const term = document.getElementById("aba_terminal_v1917");
  const btnRel = document.getElementById("tab_relatorio_tecnico");
  const btnTerm = document.getElementById("tab_terminal_v1917");
  const terminalAtivo = aba === "terminal";
  if (rel) rel.classList.toggle("hidden", terminalAtivo);
  if (term) term.classList.toggle("hidden", !terminalAtivo);
  if (btnRel) btnRel.classList.toggle("active", !terminalAtivo);
  if (btnTerm) btnTerm.classList.toggle("active", terminalAtivo);
  if (terminalAtivo) rolarTerminalV1917ParaFim();
}

function rolarTerminalV1917ParaFim() {
  const el = document.getElementById("terminal_v1917");
  if (el) el.scrollTop = el.scrollHeight;
}

function limparTerminalV1917Local() {
  terminalV1917Linhas = [];
  const el = document.getElementById("terminal_v1917");
  if (el) el.textContent = "Terminal limpo localmente. O job no Render continua preservado no disco persistente.";
  const meta = document.getElementById("terminal_v1917_meta");
  if (meta) meta.textContent = "0 linha(s) visíveis";
}

function atualizarTerminalV1917(data) {
  const linhas = Array.isArray(data?.terminal_linhas) ? data.terminal_linhas : [];
  const el = document.getElementById("terminal_v1917");
  const meta = document.getElementById("terminal_v1917_meta");
  if (!el) return;
  if (linhas.length) {
    terminalV1917Linhas = linhas;
    el.textContent = linhas.join("\n");
  } else if (!terminalV1917Linhas.length) {
    el.textContent = "Terminal aguardando diagnóstico V24.7...";
  }
  if (meta) {
    const total = data?.terminal_total_linhas || linhas.length || terminalV1917Linhas.length;
    const fase = data?.fase ? `fase: ${data.fase}` : "aguardando fase";
    const job = data?.job_id ? `job: ${data.job_id}` : "sem job";
    meta.textContent = `${total} linha(s) no job; ${fase}; ${job}`;
  }
  rolarTerminalV1917ParaFim();
}

function limparResumo() {
  ["res_valor_atual", "res_valor_futuro", "res_depreciacao", "res_taxa", "res_confianca", "res_origem", "res_tipo_usado", "res_modelo"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "-";
  });
  configurarBotoesResultado(false, false, false);
  atualizarVisibilidadeResumo();
  const linhaModelo = document.getElementById("res_modelo_linha");
  if (linhaModelo) {
    linhaModelo.classList.add("hidden");
    linhaModelo.classList.remove("low-confidence");
  }
  mostrarGraficoBarrasArea(false);
  mostrarAuditoriaArea(false);
}

function resetarFluxoDepreciacao() {
  ultimoResumoDepreciacao = null;
  ultimoJobDiagnosticoV1917 = null;
  mostrarResultadoArea(false);
  mostrarGraficoBarrasArea(false);
  mostrarAuditoriaArea(false);
  atualizarFeedbackCalculo("", 0, false);
  atualizarStatusResultado("Aguardando seleção do veículo.", "muted");
  terminalV1917Linhas = [];
  atualizarTerminalV1917({ terminal_linhas: [] });
  limparResumo();
}
window.resetarFluxoDepreciacao = resetarFluxoDepreciacao;

function confiancaEhBaixaOuExploratoria(conf) {
  const txt = String(conf || "").trim().toLowerCase();
  return txt.includes("explorat") || txt.includes("baixa") || txt.includes("insuf") || txt.includes("sem conf") || txt.includes("pendente");
}

function configurarBotoesResultado(curvaEncontrada, podeCalcularFuturo, permitirApagar = false) {
  const btnDetalhes = document.getElementById("btn_ver_detalhes");
  const btnCalcular = document.getElementById("btn_calcular_futuro");
  const btnUsarTCO = document.getElementById("btn_usar_no_tco");
  const btnApagar = document.getElementById("btn_apagar_curva");
  const btnDiag = document.getElementById("btn_diagnostico_coorte");

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

  if (btnApagar) {
    btnApagar.classList.toggle("hidden", !(curvaEncontrada && permitirApagar));
    btnApagar.disabled = !(curvaEncontrada && permitirApagar);
  }

  if (btnDiag) {
    const mostrarDiag = curvaEncontrada || podeCalcularFuturo;
    btnDiag.classList.toggle("hidden", !mostrarDiag);
    btnDiag.disabled = !mostrarDiag;
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
  const linhaModelo = document.getElementById("res_modelo_linha");
  const elModelo = document.getElementById("res_modelo");
  const veiculo = data.detalhes?.veiculo || {};
  const nomeModelo = [veiculo.marca, veiculo.modelo, veiculo.ano_modelo].filter(Boolean).join(" ").trim();
  if (linhaModelo && elModelo) {
    elModelo.textContent = nomeModelo || "-";
    linhaModelo.classList.toggle("hidden", !nomeModelo);
    linhaModelo.classList.toggle("low-confidence", confiancaEhBaixaOuExploratoria(data.confianca));
  }
  atualizarVisibilidadeResumo();
}

function atualizarVisibilidadeResumo() {
  document.querySelectorAll("#card_resultado .data-list dd").forEach((dd) => {
    const valor = (dd.textContent || "").trim();
    const mostrar = valor !== "" && valor !== "-" && valor.toLowerCase() !== "nan" && valor.toLowerCase() !== "undefined" && valor.toLowerCase() !== "null";
    dd.style.display = mostrar ? "" : "none";
    const dt = dd.previousElementSibling;
    if (dt && dt.tagName && dt.tagName.toLowerCase() === "dt") dt.style.display = mostrar ? "" : "none";
  });
}

function limparResumoParcialApenasValor(valorAtual) {
  ["res_valor_futuro", "res_depreciacao", "res_taxa", "res_confianca", "res_origem", "res_tipo_usado"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "-";
  });
  const atual = document.getElementById("res_valor_atual");
  if (atual) atual.textContent = formatarMoedaBR(valorAtual);
  atualizarVisibilidadeResumo();
}

function valorInformado(valor) {
  if (valor === null || valor === undefined) return false;
  const txt = String(valor).trim();
  return txt !== "" && txt !== "-" && txt.toLowerCase() !== "nan" && txt.toLowerCase() !== "null" && txt.toLowerCase() !== "undefined";
}

function montarLinhaDetalhe(rotulo, valor) {
  if (!valorInformado(valor)) return null;
  const tr = document.createElement("tr");
  const th = document.createElement("th");
  const td = document.createElement("td");
  th.textContent = rotulo;
  td.textContent = String(valor);
  tr.appendChild(th);
  tr.appendChild(td);
  return tr;
}

function adicionarDetalhe(corpo, rotulo, valor) {
  const linha = montarLinhaDetalhe(rotulo, valor);
  if (linha) corpo.appendChild(linha);
}


function montarRelatorioTextual(data, origem = "curva") {
  const relatorioImportado = data?.relatorio_textual || data?.relatorio_tecnico || data?.detalhes?.curva?.relatorio_tecnico || data?.detalhes?.curva?.relatorio_tecnico_texto;
  if (relatorioImportado && String(relatorioImportado).trim()) return String(relatorioImportado).trim();
  const detalhes = data?.detalhes || {};
  const veiculo = detalhes.veiculo || ultimoDetalheFipe || {};
  const modelo = veiculo.modelo || detalhes.modelo || data?.modelo || "veículo selecionado";
  const marca = veiculo.marca || detalhes.marca || data?.marca || "";
  const horizonte = Number(data?.horizonte_anos || document.getElementById("horizonte_anos")?.value || 5);
  const valorAtual = Number(data?.valor_atual || veiculo.valor_atual || 0);
  const valorFuturo = Number(data?.valor_futuro || 0);
  const taxa = Number(data?.taxa_anual_percentual || 0);
  const dep = Number(data?.depreciacao_percentual || 0);
  const confianca = data?.confianca || detalhes.confianca;
  const pontos = data?.pontos_historicos || detalhes.pontos_historicos;
  const janela = data?.janela_historica_meses || detalhes.janela_historica_meses;
  const origemFinal = data?.origem_curva || detalhes.origem_curva || origem || "curva cadastrada";
  const auditoriaInfo = detalhes.auditoria_historico || data?.motor?.auditoria_historico || {};
  const perda = valorAtual && valorFuturo ? valorAtual - valorFuturo : 0;

  const linhas = [];
  linhas.push("RELATÓRIO TÉCNICO DE AUDITORIA DA DEPRECIAÇÃO");
  linhas.push("");
  linhas.push(`Veículo analisado: ${[marca, modelo].filter(Boolean).join(" ") || "veículo selecionado"}.`);
  linhas.push(`Horizonte da análise: ${horizonte} ano(s).`);
  if (valorAtual) linhas.push(`Valor FIPE inicial: ${formatarMoedaBR(valorAtual)}.`);
  if (valorFuturo) linhas.push(`Valor estimado ao final do horizonte: ${formatarMoedaBR(valorFuturo)}.`);
  if (perda > 0) linhas.push(`Perda econômica estimada no período: ${formatarMoedaBR(perda)}.`);
  if (dep) linhas.push(`Depreciação acumulada: ${dep.toFixed(2).replace(".", ",")}%.`);
  if (taxa) linhas.push(`Taxa média anual utilizada: ${taxa.toFixed(2).replace(".", ",")}% a.a.`);
  if (valorInformado(auditoriaInfo.modo_calculo)) {
    if (String(auditoriaInfo.modo_calculo).includes("usado")) {
      linhas.push("Critério de projeção: veículo usado; a projeção parte do valor FIPE atual e continua a curva no ponto de idade observado, em vez de reiniciar a depreciação como zero km.");
    } else if (String(auditoriaInfo.modo_calculo).includes("zero")) {
      linhas.push("Critério de projeção: veículo zero km; a projeção inicia na idade zero da curva de depreciação.");
    }
  }

  const linhasAuditoria = [];
  if (valorInformado(origemFinal)) linhasAuditoria.push(`Origem técnica da curva: ${origemFinal}.`);
  if (valorInformado(confianca)) linhasAuditoria.push(`Nível de confiança: ${confianca}.`);
  if (valorInformado(pontos)) linhasAuditoria.push(`Pontos históricos considerados: ${pontos}.`);
  if (valorInformado(janela)) linhasAuditoria.push(`Janela histórica observada: ${janela} meses.`);
  if (valorInformado(auditoriaInfo.fonte_historico)) linhasAuditoria.push(`Fonte do histórico: ${auditoriaInfo.fonte_historico}.`);
  if (valorInformado(auditoriaInfo.curva_referencia)) linhasAuditoria.push(`Curva/modelo de referência: ${auditoriaInfo.curva_referencia}.`);
  const proxyTxt = String(origemFinal || "").toLowerCase().includes("proxy") || auditoriaInfo.proxy_aplicado;
  linhasAuditoria.push(`Proxy aplicado: ${proxyTxt ? "Sim" : "Não"}.`);
  if (linhasAuditoria.length) {
    linhas.push("");
    linhas.push(...linhasAuditoria);
  }

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
  adicionarDetalhe(corpo, "Resultado", data?.mensagem || "Curva carregada.");
  adicionarDetalhe(corpo, "Tipo utilizado", detalhes.tipo_label || data?.tipo_label || data?.tipo_curva);
  adicionarDetalhe(corpo, "Origem", data?.origem_curva || detalhes.origem_curva || origem);
  adicionarDetalhe(corpo, "Confiança", data?.confianca || detalhes.confianca);
  adicionarDetalhe(corpo, "Taxa anual", data?.taxa_anual_percentual ? `${Number(data.taxa_anual_percentual).toFixed(2).replace(".", ",")}% a.a.` : "-");
  adicionarDetalhe(corpo, "Pontos históricos", data?.pontos_historicos || detalhes.pontos_historicos);
  adicionarDetalhe(corpo, "Janela histórica", data?.janela_historica_meses ? `${data.janela_historica_meses} meses` : detalhes.janela_historica_meses ? `${detalhes.janela_historica_meses} meses` : "-");
  adicionarDetalhe(corpo, "Período inicial", detalhes.periodo_inicial || curva.periodo_inicial);
  adicionarDetalhe(corpo, "Período final", detalhes.periodo_final || curva.periodo_final);
  adicionarDetalhe(corpo, "Família", familia.family_nome || curva.family_nome || familia.family_id || curva.family_id);
  adicionarDetalhe(corpo, "Modelo base", curva.modelo_base_curva || familia.modelo_base_curva || familia.modelo_base_curva_eletrico || familia.modelo_base_curva_combustao);
  adicionarDetalhe(corpo, "Ano base", curva.ano_base_curva || familia.ano_base_curva || familia.ano_base_curva_eletrico || familia.ano_base_curva_combustao);
  adicionarDetalhe(corpo, "Ano usado como proxy", curva.ano_modelo_proxy || auditoria.ano_modelo_proxy);
  adicionarDetalhe(corpo, "Código ano proxy", curva.codigo_ano_proxy || auditoria.codigo_ano_proxy);
  adicionarDetalhe(corpo, "Nome proxy", curva.nome_proxy || auditoria.nome_proxy);

  if (Object.keys(auditoria).length > 0) {
    adicionarDetalhe(corpo, "Primeiro valor histórico", auditoria.primeiro_valor != null ? formatarMoedaBR(auditoria.primeiro_valor) : "-");
    adicionarDetalhe(corpo, "Último valor histórico", auditoria.ultimo_valor != null ? formatarMoedaBR(auditoria.ultimo_valor) : "-");
    adicionarDetalhe(corpo, "Menor valor histórico", auditoria.menor_valor != null ? formatarMoedaBR(auditoria.menor_valor) : "-");
    adicionarDetalhe(corpo, "Maior valor histórico", auditoria.maior_valor != null ? formatarMoedaBR(auditoria.maior_valor) : "-");
    adicionarDetalhe(corpo, "Variação total", auditoria.variacao_total_percentual != null ? `${Number(auditoria.variacao_total_percentual).toFixed(2).replace(".", ",")}%` : "-");
    const origemTexto = String(data?.origem_curva || detalhes.origem_curva || origem || "").toLowerCase();
    const proxyAplicado = Boolean(auditoria.proxy_aplicado) || origemTexto.includes("proxy");
    adicionarDetalhe(corpo, "Zero km detectado", auditoria.zero_km_detectado || auditoria.zero_km_original ? "Sim" : "Não");
    adicionarDetalhe(corpo, "Proxy aplicado", proxyAplicado ? "Sim" : "Não");
    adicionarDetalhe(corpo, "Fonte do histórico", auditoria.fonte_historico || curva.fonte_historico);
    adicionarDetalhe(corpo, "Curva/modelo referência", auditoria.curva_referencia || (auditoria.referencia && (auditoria.referencia.titulo || auditoria.referencia.modelo)));
    adicionarDetalhe(corpo, "Ano usado como proxy", auditoria.ano_modelo_proxy);
    adicionarDetalhe(corpo, "Método da taxa", auditoria.metodo_taxa);
    adicionarDetalhe(corpo, "Status da série", auditoria.status_serie);
  }
}


async function apagarCurvaAtual() {
  if (!ultimoDetalheFipe) return;
  const ok = window.confirm("Apagar a curva calculada deste veículo? A base original será preservada; apenas curva criada pela web será removida.");
  if (!ok) return;
  atualizarFeedbackCalculo("Apagando curva calculada...", 40, true);
  try {
    const payload = {
      ...ultimoDetalheFipe,
      tipo: document.getElementById("tipo_veiculo")?.value || "auto",
      horizonte_anos: document.getElementById("horizonte_anos")?.value || 5
    };
    const resp = await fetch("/api/depreciacao/apagar_curva", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    atualizarFeedbackCalculo(data.mensagem || "Curva apagada.", 100, true);
    setTimeout(() => atualizarFeedbackCalculo("", 0, false), 1200);
    await carregarStatusBases();
    await consultarResumoDepreciacao(ultimoDetalheFipe);
  } catch (e) {
    atualizarFeedbackCalculo("Erro ao apagar curva. Tente novamente.", 100, true);
  }
}

function mostrarDetalhes() {
  if (!ultimoResumoDepreciacao) return;
  mostrarGraficoBarrasArea(true);
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
      configurarBotoesResultado(true, false, confiancaEhBaixaOuExploratoria(data.confianca));
      mostrarGraficoBarrasArea(true);
      mostrarAuditoriaArea(true);
      preencherRelatorio(data, "curva salva");
      renderizarGraficosDepreciacao(data);
      if (estaEmModoBridgeTCO()) mostrarDetalhes();
    } else {
      atualizarFeedbackCalculo("Curva não encontrada. Processamento deve ser feito no painel local.", 100, false);
      atualizarStatusResultado((data.mensagem || "Curva não encontrada.") + " Processe esta curva no painel local e envie para o Render.", "nao-encontrado");
      limparResumoParcialApenasValor(data.valor_atual || detalheFipe.valor_atual);
      mostrarGraficoBarrasArea(false);
      mostrarAuditoriaArea(false);
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

async function solicitarDiagnosticoCoorte(chamadaAutomatica = false) {
  const payload = montarPayloadDepreciacao();
  if (!payload) {
    atualizarStatusResultado("Selecione um veículo antes de diagnosticar.", "erro");
    return;
  }

  if (!chamadaAutomatica) {
    // V24.7: clique manual sempre inicia job novo no modo API PRO.
    // Isso evita continuar jobs antigos V24.5 que ainda usavam FIPE Web pública.
    ultimoJobDiagnosticoV1917 = null;
    diagnosticoV1917AutoAtivo = true;
    diagnosticoV1917Ciclos = 0;
    terminalV1917Linhas = [];
    selecionarAbaAuditoriaV1917("terminal");
    atualizarTerminalV1917({ terminal_linhas: ["[local] Iniciando diagnóstico V24.7 API PRO. O terminal será atualizado a cada lote seguro do Render..."] });
  }
  diagnosticoV1917Ciclos += 1;

  payload.modo_pandemia = payload.modo_pandemia || "Excluir";
  payload.max_referencias_por_chamada = payload.max_referencias_por_chamada || 1;
  if (ultimoJobDiagnosticoV1917) payload.job_id = ultimoJobDiagnosticoV1917;

  const btn = document.getElementById("btn_diagnostico_coorte");
  if (btn) {
    btn.disabled = true;
    btn.textContent = ultimoJobDiagnosticoV1917 ? "Continuando..." : "Diagnosticando...";
  }

  mostrarResultadoArea(true);
  mostrarAuditoriaArea(true);
  mostrarGraficoBarrasArea(false);
  atualizarFeedbackCalculo("Rodando diagnóstico V19.17 em lote seguro...", 40, true);

  let manterContinuar = false;
  let continuarAutomaticamente = false;
  try {
    const resp = await fetch("/api/depreciacao/diagnostico_v1917", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const rawText = await resp.text();
    let data = null;
    try {
      data = JSON.parse(rawText);
    } catch (parseError) {
      const msg = `Resposta não-JSON do servidor no diagnóstico V19.17. HTTP ${resp.status}. ${rawText.slice(0, 300)}`;
      atualizarStatusResultado(msg, "erro");
      atualizarFeedbackCalculo(msg, 100, true);
      return;
    }
    if (!resp.ok) {
      const msg = data.mensagem || data.erro || `Erro HTTP ${resp.status} no diagnóstico V19.17.`;
      atualizarStatusResultado(msg, "erro");
      atualizarFeedbackCalculo(msg, 100, true);
      return;
    }

    atualizarTerminalV1917(data);

    if (data.job_id && data.ok && !data.coleta_concluida) {
      ultimoJobDiagnosticoV1917 = data.job_id;
      manterContinuar = true;
    } else {
      ultimoJobDiagnosticoV1917 = null;
    }

    const rel = document.getElementById("relatorio_textual");
    const corpo = document.getElementById("detalhes_corpo");
    if (rel) rel.textContent = data.relatorio_textual || data.mensagem || "Diagnóstico V19.17 concluído.";
    if (corpo) {
      const am = data.amostragem_referencias || {};
      const primeira = data.primeira_aparicao || {};
      const zero = data.zero_km_base || {};
      corpo.innerHTML = "";
      adicionarDetalhe(corpo, "Motor", data.motor || "V19.17 adapter paralelo");
      adicionarDetalhe(corpo, "Status", data.status || data.fase);
      adicionarDetalhe(corpo, "Job", data.job_id);
      adicionarDetalhe(corpo, "Fase", data.fase);
      adicionarDetalhe(corpo, "Modo pandemia", data.modo_pandemia || "Excluir");
      adicionarDetalhe(corpo, "Fonte histórica", data.fonte_historico || am.fonte_historico || "-");
      adicionarDetalhe(corpo, "API consulta", data.api_consulta || am.api_consulta || "API PRO v2");
      adicionarDetalhe(corpo, "API histórico", data.api_historico || am.api_historico || "API PRO v2 por referência mensal");
      adicionarDetalhe(corpo, "Token", data.token || am.token || "Enviado");
      adicionarDetalhe(corpo, "API paga", data.api_paga || am.api_paga || "Ativada");
      adicionarDetalhe(corpo, "Coleta", data.coleta_concluida ? "Concluída" : "Em andamento automático em lotes seguros");
      adicionarDetalhe(corpo, "Pode salvar curva", data.pode_salvar ? "Sim" : "Não");
      adicionarDetalhe(corpo, "Ano-base preferencial", data.ano_base_preferencial);
      adicionarDetalhe(corpo, "Coorte base", data.coorte_base ? `${data.coorte_base.ano || ""} ${data.coorte_base.nome || ""}`.trim() : "-");
      adicionarDetalhe(corpo, "Primeira aparição", primeira.data_referencia ? `${primeira.data_referencia} ${primeira.valor_formatado || ""}`.trim() : "-");
      adicionarDetalhe(corpo, "Zero km base", zero.data_referencia ? `${zero.data_referencia} ${zero.valor_formatado || ""}`.trim() : "-");
      adicionarDetalhe(corpo, "Referências disponíveis", data.total_referencias_disponiveis || am.total_referencias_disponiveis);
      adicionarDetalhe(corpo, "Busca primeira aparição", data.indice_busca_primeira != null && data.total_referencias_busca != null ? `${data.indice_busca_primeira}/${data.total_referencias_busca}` : "-");
      adicionarDetalhe(corpo, "Referências planejadas", am.pontos_planejados);
      adicionarDetalhe(corpo, "Referências processadas", am.referencias_processadas != null && am.total_referencias_coleta != null ? `${am.referencias_processadas}/${am.total_referencias_coleta}` : "-");
      adicionarDetalhe(corpo, "Pontos válidos", am.pontos_validos);
      adicionarDetalhe(corpo, "Pontos usados", am.pontos_usados_validos || data.pontos_historicos);
      adicionarDetalhe(corpo, "Janela histórica", data.janela_historica_meses != null ? `${data.janela_historica_meses} meses` : "-");
      adicionarDetalhe(corpo, "Qualidade", data.qualidade_estimativa || data.confianca);
      adicionarDetalhe(corpo, "Idade de entrada", data.idade_entrada_curva_meses != null ? `${data.idade_entrada_curva_meses} meses` : "-");
      adicionarDetalhe(corpo, "Taxa para plataforma", data.taxa_para_plataforma_percentual != null ? `${Number(data.taxa_para_plataforma_percentual).toFixed(4).replace(".", ",")}% a.a.` : "-");
      adicionarDetalhe(corpo, "Valor futuro base", data.valor_futuro != null ? formatarMoedaBR(data.valor_futuro) : "-");
      adicionarDetalhe(corpo, "Primeiro ponto", am.primeiro_ponto ? `${am.primeiro_ponto.data_referencia || ""} ${am.primeiro_ponto.valor_formatado || ""}`.trim() : "-");
      adicionarDetalhe(corpo, "Último ponto", am.ultimo_ponto ? `${am.ultimo_ponto.data_referencia || ""} ${am.ultimo_ponto.valor_formatado || ""}`.trim() : "-");
      adicionarDetalhe(corpo, "Falhas controladas", am.falhas_coleta);
      adicionarDetalhe(corpo, "404 ignorados", am.erros_404_ignorados);
      adicionarDetalhe(corpo, "Falha API PRO V24.7", data.falha_api_pro_v1917 || am.falha_api_pro_v1917 || data.falha_fipe_web_v1917 || am.falha_fipe_web_v1917 || "-");
      adicionarDetalhe(corpo, "Ciclos automáticos", `${diagnosticoV1917Ciclos}/${DIAGNOSTICO_V1917_MAX_CICLOS}`);
      adicionarDetalhe(corpo, "Observação", data.criterio_salvamento || "Diagnóstico não salva curva.");
    }
    atualizarStatusResultado(data.mensagem || "Diagnóstico V19.17 executado.", data.ok ? "encontrado" : "erro");
    continuarAutomaticamente = manterContinuar && diagnosticoV1917AutoAtivo && diagnosticoV1917Ciclos < DIAGNOSTICO_V1917_MAX_CICLOS;
    if (continuarAutomaticamente) {
      atualizarFeedbackCalculo(`Lote ${diagnosticoV1917Ciclos} concluído. Continuando automaticamente para evitar timeout do Render...`, 55, true);
      setTimeout(() => solicitarDiagnosticoCoorte(true), 450);
    } else {
      diagnosticoV1917AutoAtivo = false;
      const msgFinal = manterContinuar ? "Diagnóstico pausado no limite de ciclos automáticos. Clique novamente para continuar." : "Diagnóstico concluído. Nenhuma curva foi salva.";
      atualizarFeedbackCalculo(msgFinal, 100, true);
      setTimeout(() => atualizarFeedbackCalculo("", 0, false), manterContinuar ? 2600 : 1800);
    }
  } catch (e) {
    diagnosticoV1917AutoAtivo = false;
    const msg = `Erro ao montar diagnóstico V19.17: ${e && e.message ? e.message : e}`;
    atualizarStatusResultado(msg, "erro");
    atualizarFeedbackCalculo(msg, 100, true);
  } finally {
    if (btn) {
      if (continuarAutomaticamente) {
        btn.disabled = true;
        btn.textContent = "Continuando diagnóstico V19.17...";
      } else {
        btn.disabled = false;
        btn.textContent = manterContinuar ? "Continuar diagnóstico V19.17" : "Diagnóstico técnico";
      }
    }
  }
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
        configurarBotoesResultado(true, false, confiancaEhBaixaOuExploratoria(data.resultado?.confianca));
        mostrarGraficoBarrasArea(true);
        mostrarAuditoriaArea(true);
        preencherRelatorio({ ...data.resultado, motor: data.motor }, "cálculo sob demanda");
        renderizarGraficosDepreciacao(data.resultado);
      }
      carregarStatusBases();
      setTimeout(() => atualizarFeedbackCalculo("", 0, false), 1500);
    } else {
      atualizarFeedbackCalculo("Cálculo não concluído. Ajuste a seleção ou tente outro veículo.", 100, true);
      atualizarStatusResultado(data.mensagem || "Falha ao calcular curva.", "erro");
      mostrarGraficoBarrasArea(false);
      mostrarAuditoriaArea(false);
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
  renderizarGraficoBarrasResultado(data);
  renderizarGraficoProjecaoResultado(data);
  renderizarGraficoHistoricoRender(data);
  renderizarTabelaHistoricoMensal(data);
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


function calcularEscalaAjustada(valores, margemRelativa = 0.12) {
  const nums = (valores || []).map(Number).filter(v => Number.isFinite(v) && v > 0);
  if (!nums.length) return { min: 0, max: 1, range: 1 };
  const minValor = Math.min(...nums);
  const maxValor = Math.max(...nums);
  const bruto = Math.max(1, maxValor - minValor);
  const margem = Math.max(bruto * margemRelativa, maxValor * 0.015, 1);
  let min = minValor - margem;
  let max = maxValor + margem;
  if (min < 0) min = 0;
  if (max <= min) max = min + 1;
  return { min, max, range: max - min };
}

function textoRelatorioCompleto(data) {
  return String(
    data?.relatorio_textual || data?.relatorio_tecnico ||
    data?.detalhes?.curva?.relatorio_tecnico || data?.detalhes?.curva?.relatorio_tecnico_texto || ""
  );
}

function extrairHistoricoDoRelatorio(data) {
  const txt = textoRelatorioCompleto(data);
  if (!txt.trim()) return [];
  const pontos = [];
  // Aceita relatórios do painel em formato BR ou EN:
  // - 2018-03: R$ 62.452,00 (usado)
  // - 2018-03: R$ 62,452.00 (usado)
  const re = /^\s*[-•]\s*(\d{4}-\d{2})\s*:\s*R\$\s*([0-9.,]+)\s*\(([^)]*)\)/gmi;
  let m;
  while ((m = re.exec(txt)) !== null) {
    const dataRef = m[1];
    const valor = parseMoedaTecnica(m[2]);
    const tipo = String(m[3] || "").trim();
    if (Number.isFinite(valor) && valor > 0) pontos.push({ data: dataRef, valor, tipo });
  }
  const vistos = new Set();
  return pontos.filter(p => {
    const k = `${p.data}|${Math.round(p.valor * 100)}|${p.tipo}`;
    if (vistos.has(k)) return false;
    vistos.add(k);
    return true;
  }).sort((a, b) => String(a.data).localeCompare(String(b.data)));
}

function renderizarGraficoHistoricoRender(data) {
  const area = document.getElementById("historico_render_area");
  const el = document.getElementById("grafico_historico_render");
  if (!area || !el) return;
  const pontos = extrairHistoricoDoRelatorio(data);
  if (!pontos.length) {
    area.classList.add("hidden");
    return;
  }
  area.classList.remove("hidden");
  el.classList.remove("empty-chart");
  el.innerHTML = "";
  const valores = pontos.map(p => p.valor);
  const escala = calcularEscalaAjustada(valores, 0.08);
  const w = 980, h = 420, padL = 92, padR = 36, padT = 30, padB = 70;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const x = idx => padL + (idx / Math.max(1, pontos.length - 1)) * plotW;
  const y = valor => padT + ((escala.max - valor) / escala.range) * plotH;
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "line-chart-svg grid-chart-svg");

  const gridY = 5;
  for (let i = 0; i <= gridY; i++) {
    const yy = padT + (i / gridY) * plotH;
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", padL);
    line.setAttribute("x2", w - padR);
    line.setAttribute("y1", yy);
    line.setAttribute("y2", yy);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);
  }
  const gridX = Math.min(8, Math.max(2, Math.floor(pontos.length / 6)));
  for (let i = 0; i <= gridX; i++) {
    const idx = Math.round((i / gridX) * (pontos.length - 1));
    const xx = x(idx);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", xx);
    line.setAttribute("x2", xx);
    line.setAttribute("y1", padT);
    line.setAttribute("y2", h - padB);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);
  }

  const axis = document.createElementNS(svgNS, "path");
  axis.setAttribute("d", `M${padL} ${padT} V${h-padB} H${w-padR}`);
  axis.setAttribute("class", "chart-axis");
  svg.appendChild(axis);

  [escala.max, (escala.max + escala.min) / 2, escala.min].forEach((valor, idx) => {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", padL - 10);
    t.setAttribute("y", idx === 0 ? padT + 4 : idx === 1 ? (padT + h - padB) / 2 : h - padB);
    t.setAttribute("text-anchor", "end");
    t.setAttribute("class", "chart-label-svg");
    t.textContent = formatarMoedaBR(valor).replace(",00", "");
    svg.appendChild(t);
  });

  const ticks = [0, Math.floor((pontos.length - 1) / 4), Math.floor((pontos.length - 1) / 2), Math.floor(3 * (pontos.length - 1) / 4), pontos.length - 1];
  [...new Set(ticks)].forEach(idx => {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", x(idx));
    t.setAttribute("y", h - 32);
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("class", "chart-label-svg");
    t.textContent = pontos[idx]?.data || "";
    svg.appendChild(t);
  });

  const d = pontos.map((p, idx) => `${idx === 0 ? "M" : "L"}${x(idx).toFixed(1)} ${y(p.valor).toFixed(1)}`).join(" ");
  const path = document.createElementNS(svgNS, "path");
  path.setAttribute("d", d);
  path.setAttribute("class", "line-series base");
  svg.appendChild(path);

  const eixoX = document.createElementNS(svgNS, "text");
  eixoX.setAttribute("x", padL + plotW / 2);
  eixoX.setAttribute("y", h - 8);
  eixoX.setAttribute("text-anchor", "middle");
  eixoX.setAttribute("class", "chart-label-svg chart-axis-title");
  eixoX.textContent = "Tempo";
  svg.appendChild(eixoX);

  el.appendChild(svg);
}



// V12 - histórico nominal e histórico corrigido pelo IPCA usando prioritariamente o relatório importado do painel.
function extrairPontosHistoricosDeTextoPlugVE(txt, modo = "nominal") {
  txt = String(txt || "");
  if (!txt.trim()) return [];
  const linhas = txt.split(/\r?\n/);
  const pontos = [];
  let emSecao = false;
  let encontrouSecao = false;
  const ehCorrigido = modo === "corrigido";
  const rePonto = /^\s*[-•]\s*(\d{4}-\d{2})\s*:\s*R\$\s*([0-9.,]+)\s*\(([^)]*)\)/i;

  for (const linha of linhas) {
    const l = String(linha || "").trim();
    const up = l.toUpperCase();
    if (ehCorrigido) {
      if (/HIST[ÓO]RICO.*CORRIGIDO|CORRIGIDO.*IPCA|BASE CORRIGIDA/.test(up)) {
        emSecao = true;
        encontrouSecao = true;
        continue;
      }
    } else {
      if ((/PROGRESS[ÃA]O HIST[ÓO]RICA|HIST[ÓO]RICO FIPE|HIST[ÓO]RICO DA BASE/.test(up)) && !/CORRIGIDO|IPCA/.test(up)) {
        emSecao = true;
        encontrouSecao = true;
        continue;
      }
    }
    if (emSecao && /^\d+\.\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]/.test(up) && !rePonto.test(l)) {
      // Nova seção numerada do relatório.
      if (pontos.length) break;
    }
    const m = rePonto.exec(l);
    if (!m) continue;
    if (encontrouSecao && !emSecao) continue;
    const dataRef = m[1];
    const valor = parseMoedaTecnica(m[2]);
    const tipo = String(m[3] || "").trim();
    if (Number.isFinite(valor) && valor > 0) pontos.push({ data: dataRef, valor, tipo });
  }

  // Fallback: se não achou uma seção nominal explícita, pega os pontos gerais do relatório.
  if (!ehCorrigido && !pontos.length) {
    const re = /^\s*[-•]\s*(\d{4}-\d{2})\s*:\s*R\$\s*([0-9.,]+)\s*\(([^)]*)\)/gmi;
    let m;
    while ((m = re.exec(txt)) !== null) {
      const valor = parseMoedaTecnica(m[2]);
      if (Number.isFinite(valor) && valor > 0) pontos.push({ data: m[1], valor, tipo: String(m[3] || "").trim() });
    }
  }

  const vistos = new Set();
  return pontos.filter(p => {
    const k = `${p.data}|${Math.round(p.valor * 100)}|${p.tipo}`;
    if (vistos.has(k)) return false;
    vistos.add(k);
    return true;
  }).sort((a, b) => String(a.data).localeCompare(String(b.data)));
}

function historicoDiretoPlugVE(data, chaves) {
  for (const chave of chaves) {
    const bruto = chave.split('.').reduce((obj, k) => obj && obj[k], data);
    if (Array.isArray(bruto) && bruto.length) {
      return bruto.map(item => ({
        data: String(item.data || item.referencia || item.data_referencia || "").slice(0, 7),
        valor: parseMoedaTecnica(item.valor ?? item.valor_fipe ?? item.preco ?? item.price ?? 0),
        tipo: String(item.tipo || item.observacao || item.status || "usado").trim()
      })).filter(p => p.data && Number.isFinite(p.valor) && p.valor > 0).sort((a, b) => String(a.data).localeCompare(String(b.data)));
    }
  }
  return [];
}

function extrairHistoricoNominalDoRelatorio(data) {
  const txt = textoRelatorioCompleto(data);
  const doRelatorio = extrairPontosHistoricosDeTextoPlugVE(txt, "nominal");
  if (doRelatorio.length) return doRelatorio;
  return historicoDiretoPlugVE(data, ["historico_mensal", "detalhes.historico_mensal"]);
}

function extrairHistoricoCorrigidoDoRelatorio(data) {
  const txt = textoRelatorioCompleto(data);
  const doRelatorio = extrairPontosHistoricosDeTextoPlugVE(txt, "corrigido");
  if (doRelatorio.length) return doRelatorio;
  return historicoDiretoPlugVE(data, ["historico_mensal_corrigido", "detalhes.historico_mensal_corrigido", "historico_ipca", "detalhes.historico_ipca"]);
}

function extrairHistoricoDoRelatorio(data) {
  return extrairHistoricoNominalDoRelatorio(data);
}

function renderizarLinhaHistoricoPlugVE(el, pontos, vazioTexto = "Histórico não disponível para esta curva.") {
  if (!el) return false;
  el.innerHTML = "";
  if (!pontos.length) {
    el.classList.add("empty-chart");
    el.textContent = vazioTexto;
    return false;
  }
  el.classList.remove("empty-chart");
  const valores = pontos.map(p => p.valor);
  const escala = calcularEscalaAjustada(valores, 0.08);
  const w = 980, h = 420, padL = 92, padR = 36, padT = 30, padB = 70;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const x = idx => padL + (idx / Math.max(1, pontos.length - 1)) * plotW;
  const y = valor => padT + ((escala.max - valor) / escala.range) * plotH;
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "line-chart-svg grid-chart-svg");

  for (let i = 0; i <= 5; i++) {
    const yy = padT + (i / 5) * plotH;
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", padL);
    line.setAttribute("x2", w - padR);
    line.setAttribute("y1", yy);
    line.setAttribute("y2", yy);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);
  }
  const gridX = Math.min(8, Math.max(2, Math.floor(pontos.length / 6)));
  for (let i = 0; i <= gridX; i++) {
    const idx = Math.round((i / gridX) * (pontos.length - 1));
    const xx = x(idx);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", xx);
    line.setAttribute("x2", xx);
    line.setAttribute("y1", padT);
    line.setAttribute("y2", h - padB);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);
  }

  const axis = document.createElementNS(svgNS, "path");
  axis.setAttribute("d", `M${padL} ${padT} V${h-padB} H${w-padR}`);
  axis.setAttribute("class", "chart-axis");
  svg.appendChild(axis);

  [escala.max, (escala.max + escala.min) / 2, escala.min].forEach((valor, idx) => {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", padL - 10);
    t.setAttribute("y", idx === 0 ? padT + 4 : idx === 1 ? (padT + h - padB) / 2 : h - padB);
    t.setAttribute("text-anchor", "end");
    t.setAttribute("class", "chart-label-svg");
    t.textContent = formatarMoedaBR(valor).replace(",00", "");
    svg.appendChild(t);
  });

  const ticks = [0, Math.floor((pontos.length - 1) / 4), Math.floor((pontos.length - 1) / 2), Math.floor(3 * (pontos.length - 1) / 4), pontos.length - 1];
  [...new Set(ticks)].forEach(idx => {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", x(idx));
    t.setAttribute("y", h - 32);
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("class", "chart-label-svg");
    t.textContent = pontos[idx]?.data || "";
    svg.appendChild(t);
  });

  const d = pontos.map((p, idx) => `${idx === 0 ? "M" : "L"}${x(idx).toFixed(1)} ${y(p.valor).toFixed(1)}`).join(" ");
  const path = document.createElementNS(svgNS, "path");
  path.setAttribute("d", d);
  path.setAttribute("class", "line-series base");
  svg.appendChild(path);

  const eixoX = document.createElementNS(svgNS, "text");
  eixoX.setAttribute("x", padL + plotW / 2);
  eixoX.setAttribute("y", h - 8);
  eixoX.setAttribute("text-anchor", "middle");
  eixoX.setAttribute("class", "chart-label-svg chart-axis-title");
  eixoX.textContent = "Tempo";
  svg.appendChild(eixoX);
  el.appendChild(svg);
  return true;
}

function renderizarGraficoHistoricoRender(data) {
  const area = document.getElementById("historico_render_area");
  const elNominal = document.getElementById("grafico_historico_render");
  const elIpca = document.getElementById("grafico_historico_ipca_render");
  if (!area || !elNominal) return;
  const nominal = extrairHistoricoNominalDoRelatorio(data);
  const corrigido = extrairHistoricoCorrigidoDoRelatorio(data);
  const temNominal = renderizarLinhaHistoricoPlugVE(elNominal, nominal, "Histórico nominal não disponível para esta curva.");
  const temCorrigido = renderizarLinhaHistoricoPlugVE(elIpca, corrigido, "Histórico corrigido pelo IPCA não disponível na curva importada.");
  area.classList.toggle("hidden", !(temNominal || temCorrigido));
}

function renderizarTabelaHistoricoMensal(data) {
  const box = document.getElementById("historico_mensal_tabela");
  const corpo = document.getElementById("historico_mensal_corpo");
  if (!box || !corpo) return;
  const pontos = extrairHistoricoDoRelatorio(data);
  corpo.innerHTML = "";
  if (!pontos.length) {
    box.classList.add("hidden");
    return;
  }
  pontos.forEach((p, idx) => {
    const tr = document.createElement("tr");
    const td1 = document.createElement("td");
    const td2 = document.createElement("td");
    const td3 = document.createElement("td");
    td1.textContent = p.data;
    td2.textContent = formatarMoedaBR(p.valor);
    td3.textContent = p.tipo || (idx === 0 ? "zero_km" : "usado");
    tr.appendChild(td1);
    tr.appendChild(td2);
    tr.appendChild(td3);
    corpo.appendChild(tr);
  });
  const resumo = document.getElementById("historico_mensal_resumo");
  if (resumo) resumo.textContent = `${pontos.length} ponto(s) históricos importados do relatório técnico do painel.`;
  box.classList.remove("hidden");
}


function extrairValorCenario(data, nomes) {
  const detalhes = data?.detalhes || {};
  const curva = detalhes.curva || {};
  for (const nome of nomes) {
    const valor = data?.[nome] ?? detalhes?.[nome] ?? curva?.[nome];
    const n = Number(valor);
    if (Number.isFinite(n) && n > 0) return n;
  }
  return 0;
}

function obterCenariosDoResultado(data) {
  const atual = Number(data?.valor_atual || 0);
  const base = Number(data?.valor_futuro || 0);
  const taxa = Number(data?.taxa_anual_percentual || 0);
  const horizonte = Number(data?.horizonte_anos || document.getElementById("horizonte_anos")?.value || 5);
  const calculado = calcularCenarios(atual, taxa, horizonte);
  return {
    atual,
    base: base || calculado.base,
    otimista: extrairValorCenario(data, ["valor_futuro_otimista"]) || calculado.otimista,
    pessimista: extrairValorCenario(data, ["valor_futuro_pessimista"]) || calculado.pessimista,
    taxaBase: calculado.taxaBase,
    taxaOtimista: calculado.taxaOtimista,
    taxaPessimista: calculado.taxaPessimista,
    horizonte
  };
}


function renderizarGraficoBarrasResultado(data) {
  const el = document.getElementById("grafico_barras");
  if (!el) return;
  el.classList.remove("empty-chart");
  el.innerHTML = "";
  const cen = obterCenariosDoResultado(data);
  if (!cen.atual || !cen.base) {
    el.classList.add("empty-chart");
    el.textContent = "Valor futuro ainda não disponível.";
    return;
  }
  const itens = [
    { label: "Inicial", valor: cen.atual },
    { label: "Base", valor: cen.base },
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
    bar.style.height = `${Math.max(12, (item.valor / max) * 250)}px`;
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

function renderizarGraficoProjecaoResultado(data) {
  const el = document.getElementById("grafico_projecao");
  if (!el) return;
  el.classList.remove("empty-chart");
  el.innerHTML = "";
  const cen = obterCenariosDoResultado(data);
  if (!cen.atual || !cen.base || !cen.horizonte) {
    el.classList.add("empty-chart");
    el.textContent = "Curva ainda não disponível.";
    return;
  }
  const anos = Array.from({ length: Math.max(1, Math.round(cen.horizonte)) + 1 }, (_, i) => i);
  const taxaBase = 1 - Math.pow(cen.base / cen.atual, 1 / Math.max(1, cen.horizonte));
  const taxaOt = 1 - Math.pow(cen.otimista / cen.atual, 1 / Math.max(1, cen.horizonte));
  const taxaPe = 1 - Math.pow(cen.pessimista / cen.atual, 1 / Math.max(1, cen.horizonte));
  const series = [
    { nome: "Base", taxa: taxaBase, classe: "base" },
    { nome: "Otimista", taxa: taxaOt, classe: "otimista" },
    { nome: "Pessimista", taxa: taxaPe, classe: "pessimista" }
  ].map(serie => ({
    ...serie,
    pontos: anos.map(ano => ({ ano, valor: cen.atual * Math.pow(1 - serie.taxa, ano) }))
  }));

  const todos = series.flatMap(s => s.pontos.map(p => p.valor)).concat([cen.atual]);
  const escala = calcularEscalaAjustada(todos, 0.12);
  const w = 900, h = 360, padL = 86, padR = 36, padT = 30, padB = 52;
  const x = ano => padL + (ano / Math.max(1, cen.horizonte)) * (w - padL - padR);
  const y = valor => padT + ((escala.max - valor) / escala.range) * (h - padT - padB);

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "line-chart-svg grid-chart-svg");

  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  for (let i = 0; i <= 5; i++) {
    const yy = padT + (i / 5) * plotH;
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", padL);
    line.setAttribute("x2", w - padR);
    line.setAttribute("y1", yy);
    line.setAttribute("y2", yy);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);
  }
  const anosGrade = Math.min(10, Math.max(2, Math.round(cen.horizonte)));
  for (let i = 0; i <= anosGrade; i++) {
    const ano = (i / anosGrade) * cen.horizonte;
    const xx = x(ano);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", xx);
    line.setAttribute("x2", xx);
    line.setAttribute("y1", padT);
    line.setAttribute("y2", h - padB);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);
  }

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
    t.textContent = ano === 0 ? "Hoje" : `${ano} anos`;
    svg.appendChild(t);
  });

  [escala.max, (escala.max + escala.min) / 2, escala.min].forEach((valor, idx) => {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", padL - 12);
    t.setAttribute("y", idx === 0 ? padT + 4 : idx === 1 ? (padT + h - padB) / 2 : h - padB);
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
    <div><span>Valor inicial</span><strong>${formatarMoedaBR(cen.atual)}</strong></div>
    <div><span>Base final</span><strong>${formatarMoedaBR(cen.base)}</strong></div>
    <div><span>Otimista final</span><strong>${formatarMoedaBR(cen.otimista)}</strong></div>
    <div><span>Pessimista final</span><strong>${formatarMoedaBR(cen.pessimista)}</strong></div>
  `;

  el.appendChild(svg);
  el.appendChild(legenda);
  el.appendChild(tabela);
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
    bar.style.height = `${Math.max(12, (item.valor / max) * 250)}px`;
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
  const escala = calcularEscalaAjustada(todos, 0.12);
  const w = 760, h = 300, padL = 72, padR = 24, padT = 28, padB = 48;
  const x = ano => padL + (ano / Math.max(1, cen.horizonte)) * (w - padL - padR);
  const y = valor => padT + ((escala.max - valor) / escala.range) * (h - padT - padB);

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "line-chart-svg grid-chart-svg");

  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  for (let i = 0; i <= 5; i++) {
    const yy = padT + (i / 5) * plotH;
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", padL);
    line.setAttribute("x2", w - padR);
    line.setAttribute("y1", yy);
    line.setAttribute("y2", yy);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);
  }
  const anosGrade = Math.min(10, Math.max(2, Math.round(cen.horizonte)));
  for (let i = 0; i <= anosGrade; i++) {
    const ano = (i / anosGrade) * cen.horizonte;
    const xx = x(ano);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", xx);
    line.setAttribute("x2", xx);
    line.setAttribute("y1", padT);
    line.setAttribute("y2", h - padB);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);
  }

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

  [escala.max, (escala.max + escala.min) / 2, escala.min].forEach((valor, idx) => {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", padL - 10);
    t.setAttribute("y", idx === 0 ? padT + 4 : idx === 1 ? (padT + h - padB) / 2 : h - padB);
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
      opt.style.fontWeight = opt.dataset.temZeroKm === "1" ? "800" : opt.style.fontWeight;
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


function abrirBaseProvisoria() {
  document.getElementById("base_provisoria_drawer")?.classList.remove("hidden-drawer");
  document.getElementById("base_drawer_backdrop")?.classList.remove("hidden");
}

function fecharBaseProvisoria() {
  document.getElementById("base_provisoria_drawer")?.classList.add("hidden-drawer");
  document.getElementById("base_drawer_backdrop")?.classList.add("hidden");
}

document.addEventListener("DOMContentLoaded", () => {
  mostrarResultadoArea(false);
  mostrarGraficoBarrasArea(false);
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
  document.getElementById("btn_diagnostico_coorte")?.addEventListener("click", solicitarDiagnosticoCoorte);
  document.getElementById("btn_apagar_curva")?.addEventListener("click", apagarCurvaAtual);
  document.getElementById("tab_relatorio_tecnico")?.addEventListener("click", () => selecionarAbaAuditoriaV1917("relatorio"));
  document.getElementById("tab_terminal_v1917")?.addEventListener("click", () => selecionarAbaAuditoriaV1917("terminal"));
  document.getElementById("btn_limpar_terminal_v1917")?.addEventListener("click", limparTerminalV1917Local);
  document.getElementById("filtro_curvas_lateral")?.addEventListener("input", filtrarListaCurvasLateral);
  document.getElementById("btn_toggle_base_provisoria")?.addEventListener("click", abrirBaseProvisoria);
  document.getElementById("btn_fechar_base_provisoria")?.addEventListener("click", fecharBaseProvisoria);
  document.getElementById("base_drawer_backdrop")?.addEventListener("click", fecharBaseProvisoria);

  setTimeout(inicializarBridgeTCO, 500);
});
