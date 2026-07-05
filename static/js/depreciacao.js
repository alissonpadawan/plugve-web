let ultimoResumoDepreciacao = null;
let ultimoJobDiagnosticoV1917 = null;
let painelDepreciacaoDados = null;
let modelosComCurva = new Set();
let codigosModelosComCurva = new Set();
let marcadoresCurvasPorNome = new Map();
let marcadoresCurvasPorCodigo = new Map();
let marcadoresCurvasCarregados = false;
let carregamentoMarcadoresCurvasIniciado = false;
const MARCADORES_CURVAS_CACHE_KEY = "curve:depreciacao:marcadores:v35_dep_visual_sem_check_v3";
const MARCADORES_CURVAS_CACHE_TTL = 30 * 60 * 1000;
let diagnosticoV1917AutoAtivo = false;
let diagnosticoV1917Ciclos = 0;
let terminalV1917Linhas = [];
let timerHorizonteDepreciacao = null;
let consultaDepreciacaoSeq = 0;
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

function mostrarAbasDepreciacao(mostrar = true) {
  document.getElementById("depreciacao_abas")?.classList.toggle("hidden", !mostrar);
}

function mostrarAuditoriaCalculoArea(mostrar = true) {
  document.getElementById("auditoria_calculo_area")?.classList.toggle("hidden", !mostrar);
}

function selecionarAbaPrincipalDepreciacao(aba = "resultado") {
  const desejada = aba === "auditoria" ? "auditoria" : "resultado";
  const temResultado = Boolean(ultimoResumoDepreciacao && ultimoResumoDepreciacao.encontrado);
  const tabs = document.getElementById("depreciacao_abas");
  if (tabs) tabs.classList.toggle("hidden", !temResultado);

  const btnResultado = document.getElementById("tab_resultado_depreciacao");
  const btnAuditoria = document.getElementById("tab_auditoria_depreciacao");
  if (btnResultado) {
    btnResultado.classList.toggle("active", desejada === "resultado");
    btnResultado.setAttribute("aria-selected", desejada === "resultado" ? "true" : "false");
  }
  if (btnAuditoria) {
    btnAuditoria.classList.toggle("active", desejada === "auditoria");
    btnAuditoria.setAttribute("aria-selected", desejada === "auditoria" ? "true" : "false");
  }

  if (!temResultado) {
    mostrarResultadoArea(false);
    mostrarGraficoBarrasArea(false);
    mostrarAuditoriaArea(false);
    mostrarAuditoriaCalculoArea(false);
    return;
  }

  if (desejada === "auditoria") {
    mostrarResultadoArea(false);
    mostrarGraficoBarrasArea(false);
    mostrarAuditoriaArea(false);
    mostrarAuditoriaCalculoArea(true);
    renderizarAuditoriaCalculo(ultimoResumoDepreciacao);
    document.getElementById("auditoria_calculo_area")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } else {
    mostrarResultadoArea(true);
    mostrarGraficoBarrasArea(true);
    mostrarAuditoriaArea(true);
    mostrarAuditoriaCalculoArea(false);
  }
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
    el.textContent = "Terminal aguardando diagnóstico técnico...";
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
  ["res_valor_atual", "res_valor_futuro", "res_perda", "res_horizonte", "res_taxa", "res_taxa_total", "res_confianca", "res_origem", "res_tipo_usado", "res_modelo"].forEach(id => {
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
  limparAuditoriaCalculo();
}

function resetarFluxoDepreciacao() {
  consultaDepreciacaoSeq += 1;
  if (timerHorizonteDepreciacao) clearTimeout(timerHorizonteDepreciacao);
  ultimoResumoDepreciacao = null;
  ultimoJobDiagnosticoV1917 = null;
  mostrarResultadoArea(false);
  mostrarGraficoBarrasArea(false);
  mostrarAuditoriaArea(false);
  limparAuditoriaCalculo();
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
  const btnAuditoria = document.getElementById("btn_auditoria");
  const btnCalcular = document.getElementById("btn_calcular_futuro");
  const btnUsarTCO = document.getElementById("btn_usar_no_tco");
  const btnApagar = document.getElementById("btn_apagar_curva");
  const btnPdf = document.getElementById("btn_exportar_pdf");
  const btnNovaConsulta = document.getElementById("btn_nova_consulta");
  const btnDiag = document.getElementById("btn_diagnostico_coorte");

  if (btnAuditoria) {
    btnAuditoria.classList.toggle("hidden", !curvaEncontrada);
    btnAuditoria.disabled = !curvaEncontrada;
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

  if (btnPdf) {
    btnPdf.classList.toggle("hidden", !curvaEncontrada);
    btnPdf.disabled = !curvaEncontrada;
  }

  if (btnNovaConsulta) {
    const mostrarNovaConsulta = Boolean(curvaEncontrada || podeCalcularFuturo || ultimoDetalheFipe || ultimoResumoDepreciacao);
    btnNovaConsulta.classList.toggle("hidden", !mostrarNovaConsulta);
    btnNovaConsulta.disabled = false;
  }

  if (btnDiag) {
    const mostrarDiag = curvaEncontrada || podeCalcularFuturo;
    btnDiag.classList.toggle("hidden", !mostrarDiag);
    btnDiag.disabled = !mostrarDiag;
  }
}

function preencherResumo(data) {
  const info = montarDadosRelatorioProfissional(data || {});
  setTextoElemento("res_valor_atual", info.valorAtual > 0 ? formatarMoedaBR(info.valorAtual) : "-");
  setTextoElemento("res_valor_futuro", info.valorFuturo > 0 ? formatarMoedaBR(info.valorFuturo) : "-");
  setTextoElemento("res_perda", info.perda > 0 ? formatarMoedaBR(info.perda) : "-");
  setTextoElemento("res_horizonte", info.horizonteLabel);
  setTextoElemento("res_taxa", info.taxaAnual > 0 ? `${info.taxaAnual.toFixed(2).replace(".", ",")}% a.a.` : "-");
  setTextoElemento("res_taxa_total", info.depreciacaoTotal > 0 ? `${info.depreciacaoTotal.toFixed(2).replace(".", ",")}%` : "-");
  setTextoElemento("res_confianca", info.confianca || "-");
  setTextoElemento("res_origem", info.baseTecnicaResumo || "-");
  setTextoElemento("res_tipo_usado", info.tipoLabel || "-");
  atualizarStatusResultado(statusProfissional(data, info), data?.encontrado ? "encontrado" : "muted");

  const linhaModelo = document.getElementById("res_modelo_linha");
  const elModelo = document.getElementById("res_modelo");
  if (linhaModelo && elModelo) {
    elModelo.textContent = info.veiculoDescricao || "-";
    linhaModelo.classList.toggle("hidden", !info.veiculoDescricao);
    linhaModelo.classList.toggle("low-confidence", confiancaEhBaixaOuExploratoria(info.confianca));
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
  ["res_valor_futuro", "res_perda", "res_horizonte", "res_taxa", "res_taxa_total", "res_confianca", "res_origem", "res_tipo_usado"].forEach(id => {
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


function setTextoElemento(id, valor) {
  const el = document.getElementById(id);
  if (el) el.textContent = valor === null || valor === undefined || valor === "" ? "-" : String(valor);
}

function escaparHtml(valor) {
  return String(valor ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function primeiroTextoValido(...valores) {
  for (const valor of valores) {
    if (valorInformado(valor)) return String(valor).trim();
  }
  return "";
}

function textoRelatorioBruto(data) {
  return String(
    data?.relatorio_textual ||
    data?.relatorio_tecnico ||
    data?.detalhes?.relatorio_tecnico ||
    data?.detalhes?.curva?.relatorio_tecnico ||
    data?.detalhes?.curva?.relatorio_tecnico_texto ||
    ""
  );
}

function extrairTextoPorPadroes(texto, padroes) {
  const fonte = String(texto || "");
  for (const padrao of padroes) {
    const m = fonte.match(padrao);
    if (m && valorInformado(m[1])) return String(m[1]).trim();
  }
  return "";
}

function limparTextoInternoRelatorio(texto) {
  let saida = String(texto || "").trim();
  if (!saida) return "";
  saida = saida.replace(/\bV\d+(?:\.\d+)+\b/gi, "").replace(/\s{2,}/g, " ").trim();
  saida = saida.replace(/cache local/gi, "base técnica local");
  saida = saida.replace(/coleta FIPE sob demanda/gi, "histórico FIPE coletado");
  saida = saida.replace(/taper mensal/gi, "ajuste progressivo por idade");
  saida = saida.replace(/taxa para a plataforma principal/gi, "taxa anual equivalente aplicada");
  saida = saida.replace(/plataforma principal/gi, "simulação");
  saida = saida.replace(/site aplicou/gi, "a projeção aplica");
  saida = saida.replace(/resultado salvo carregado/gi, "curva disponível");
  return saida.trim();
}

function limparAnoBaseProfissional(valor) {
  const txt = String(valor || "").trim();
  if (!txt) return "";
  const ano = txt.match(/(?:19|20)\d{2}/);
  if (!ano) return "";
  const n = Number(ano[0]);
  if (!Number.isFinite(n) || n < 1990 || n > 2100) return "";
  return String(n);
}

function formatarMesesProfissional(meses) {
  const n = Number(meses || 0);
  if (!Number.isFinite(n) || n <= 0) return "";
  const anos = n / 12;
  if (n < 12) return `${Math.round(n)} meses`;
  if (Math.abs(anos - Math.round(anos)) < 0.05) return `${Math.round(anos)} ano${Math.round(anos) === 1 ? "" : "s"} (${Math.round(n)} meses)`;
  return `${anos.toFixed(1).replace(".", ",")} anos (${Math.round(n)} meses)`;
}

function valorPercentualTexto(valor, casas = 2, sufixo = "%") {
  const n = Number(valor || 0);
  if (!Number.isFinite(n) || n <= 0) return "-";
  return `${n.toFixed(casas).replace(".", ",")}${sufixo}`;
}

function obterVeiculoDescricaoProfissional(data) {
  const detalhes = data?.detalhes || {};
  const veiculo = detalhes.veiculo || ultimoDetalheFipe || {};
  const marca = primeiroTextoValido(veiculo.marca, detalhes.marca, data?.marca);
  const modelo = primeiroTextoValido(veiculo.modelo, detalhes.modelo, data?.modelo);
  const ano = primeiroTextoValido(veiculo.ano_modelo, veiculo.ano_combustivel, detalhes.ano_modelo, data?.ano_modelo);
  return [marca, modelo, ano].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
}

function obterCodigoFipeProfissional(data) {
  const detalhes = data?.detalhes || {};
  const veiculo = detalhes.veiculo || ultimoDetalheFipe || {};
  const bruto = textoRelatorioBruto(data);
  return primeiroTextoValido(
    veiculo.codigo_fipe,
    data?.codigo_fipe,
    detalhes.codigo_fipe,
    detalhes.curva?.codigo_fipe,
    extrairTextoPorPadroes(bruto, [/Código FIPE:\s*([^\n\r]+)/i])
  );
}

function obterDataBaseFipeProfissional(data) {
  const detalhes = data?.detalhes || {};
  const veiculo = detalhes.veiculo || ultimoDetalheFipe || {};
  const bruto = textoRelatorioBruto(data);
  return primeiroTextoValido(
    data?.data_base_fipe,
    detalhes.data_base_fipe,
    veiculo.referencia_fipe,
    veiculo.referencia,
    extrairTextoPorPadroes(bruto, [/Referência\/Data-base FIPE:\s*([^\n\r]+)/i, /Data-base da análise:\s*([^\n\r]+)/i])
  );
}

function obterSimilaridadeProfissional(data) {
  const detalhes = data?.detalhes || {};
  const curva = detalhes.curva || {};
  const auditoria = detalhes.auditoria_historico || data?.auditoria_historico || {};
  const bruto = textoRelatorioBruto(data);
  const curvaPorSimilaridade = Boolean(
    data?.curva_por_similaridade || detalhes.curva_por_similaridade || curva.curva_por_similaridade || auditoria.curva_por_similaridade ||
    String(data?.tipo_curva_aplicada || detalhes.tipo_curva_aplicada || curva.tipo_curva_aplicada || "").toLowerCase() === "similaridade"
  );
  return {
    curvaPorSimilaridade,
    modeloReferencia: limparTextoInternoRelatorio(primeiroTextoValido(
      data?.modelo_referencia_similaridade,
      detalhes.modelo_referencia_similaridade,
      curva.modelo_referencia_similaridade,
      auditoria.modelo_referencia_similaridade,
      data?.modelo_referencia,
      detalhes.modelo_referencia,
      curva.modelo_referencia,
      auditoria.modelo_referencia,
      extrairTextoPorPadroes(bruto, [/Modelo referência da curva:\s*([^\n\r]+)/i])
    )),
    origem: limparTextoInternoRelatorio(primeiroTextoValido(
      data?.origem_similaridade,
      detalhes.origem_similaridade,
      curva.origem_similaridade,
      auditoria.origem_similaridade,
      extrairTextoPorPadroes(bruto, [/Origem do vínculo:\s*([^\n\r]+)/i])
    )),
    chave: limparTextoInternoRelatorio(primeiroTextoValido(
      data?.chave_curva_referencia,
      detalhes.chave_curva_referencia,
      curva.chave_curva_referencia,
      auditoria.chave_curva_referencia,
      extrairTextoPorPadroes(bruto, [/Chave da curva referência:\s*([^\n\r]+)/i])
    ))
  };
}

function obterModeloBaseProfissional(data) {
  const detalhes = data?.detalhes || {};
  const curva = detalhes.curva || {};
  const familia = detalhes.familia || {};
  const auditoria = detalhes.auditoria_historico || data?.motor?.auditoria_historico || {};
  const bruto = textoRelatorioBruto(data);
  const sim = obterSimilaridadeProfissional(data);
  return limparTextoInternoRelatorio(primeiroTextoValido(
    sim.curvaPorSimilaridade ? sim.modeloReferencia : "",
    extrairTextoPorPadroes(bruto, [/Modelo base usado como referência:\s*([^\n\r]+)/i, /Modelo-base\/curva de referência:\s*([^\n\r]+)/i, /Curva\/modelo referência:\s*([^\n\r]+)/i]),
    curva.modelo_base_curva,
    familia.modelo_base_curva,
    familia.modelo_base_curva_eletrico,
    familia.modelo_base_curva_combustao,
    auditoria.curva_referencia,
    auditoria.referencia?.titulo,
    auditoria.referencia?.modelo,
    obterVeiculoDescricaoProfissional(data)
  ));
}

function obterAnoBaseProfissional(data) {
  const detalhes = data?.detalhes || {};
  const curva = detalhes.curva || {};
  const familia = detalhes.familia || {};
  const bruto = textoRelatorioBruto(data);
  return primeiroTextoValido(
    limparAnoBaseProfissional(extrairTextoPorPadroes(bruto, [/Ano âncora\/coorte usada:\s*([^\n\r]+)/i, /Ano-base preferencial:\s*([^\n\r]+)/i, /Ano base usado como referência:\s*([^\n\r]+)/i])),
    limparAnoBaseProfissional(curva.ano_base_curva),
    limparAnoBaseProfissional(familia.ano_base_curva),
    limparAnoBaseProfissional(familia.ano_base_curva_eletrico),
    limparAnoBaseProfissional(familia.ano_base_curva_combustao)
  );
}

function obterDataZeroKmBaseProfissional(data) {
  const detalhes = data?.detalhes || {};
  const curva = detalhes.curva || {};
  const bruto = textoRelatorioBruto(data);
  return primeiroTextoValido(
    data?.data_zero_km_base,
    detalhes.data_zero_km_base,
    curva.data_zero_km_base,
    extrairTextoPorPadroes(bruto, [/Data do zero km base:\s*([^\n\r]+)/i, /Data-base zero km:\s*([^\n\r]+)/i])
  );
}

function obterTipoCurvaProfissional(data) {
  const detalhes = data?.detalhes || {};
  const sim = obterSimilaridadeProfissional(data);
  if (sim.curvaPorSimilaridade) return "Curva herdada por similaridade";
  const origem = String(data?.origem_curva || detalhes.origem_curva || "").toLowerCase();
  if (origem.includes("proxy")) return "Curva por proxy técnico";
  if (origem.includes("fam") || origem.includes("familiar")) return "Curva familiar";
  if (origem.includes("explorat")) return "Curva exploratória";
  if (origem.includes("coorte") || origem.includes("própria") || origem.includes("propria")) return "Curva própria do modelo";
  return primeiroTextoValido(data?.origem_curva, detalhes.origem_curva, "Curva histórica disponível");
}

function tipoMotorizacaoProfissional(data) {
  const detalhes = data?.detalhes || {};
  const txt = String(detalhes.tipo_label || data?.tipo_label || data?.tipo_curva || detalhes.tipo_utilizado || "").toLowerCase();
  if (txt.includes("eletr") || txt.includes("híbr") || txt.includes("hibr")) return "Elétrico ou híbrido";
  if (txt.includes("comb")) return "Combustão";
  return primeiroTextoValido(detalhes.tipo_label, data?.tipo_label, data?.tipo_curva, "Veículo");
}

function statusProfissional(data, info = null) {
  if (!data?.encontrado) return "Selecione um veículo para gerar a estimativa.";
  const dados = info || montarDadosRelatorioProfissional(data);
  if (confiancaEhBaixaOuExploratoria(dados.confianca)) {
    return "Estimativa disponível, com cautela metodológica por limitação da base histórica.";
  }
  return "Estimativa gerada a partir da curva histórica disponível para o veículo selecionado.";
}

function obterBaseTecnicaResumoProfissional(info) {
  const partes = [];
  if (info.modeloBase) partes.push(info.modeloBase);
  if (info.anoBase) partes.push(`coorte ${info.anoBase}`);
  if (info.dataZeroKmBase) partes.push(`base zero km ${info.dataZeroKmBase}`);
  const detalhe = [];
  if (info.pontosHistoricos > 0) detalhe.push(`${info.pontosHistoricos} pontos históricos FIPE`);
  if (info.janelaHistoricaMeses > 0) detalhe.push(`janela de ${info.janelaHistoricaMeses} meses`);
  let texto = partes.filter(Boolean).join(" - ");
  if (!texto) texto = "Base histórica FIPE disponível";
  if (detalhe.length) texto += `, com ${detalhe.join(" e ")}`;
  if (info.curvaPorSimilaridade) {
    const ref = info.modeloReferenciaSimilaridade || info.modeloBase || "modelo referência";
    texto += `. Curva herdada por similaridade manual do ${ref}; o valor FIPE inicial é do veículo selecionado`;
  }
  return `${texto}.`;
}

function montarDadosRelatorioProfissional(data) {
  const detalhes = data?.detalhes || {};
  const curva = detalhes.curva || {};
  const auditoria = detalhes.auditoria_historico || data?.motor?.auditoria_historico || {};
  const cen = obterCenariosDoResultado(data || {});
  const valorAtual = Number(cen.atual || data?.valor_atual || detalhes?.veiculo?.valor_atual || 0);
  const valorFuturo = Number(cen.base || data?.valor_futuro || data?.valor_futuro_base || 0);
  const valorOtimista = Number(cen.otimista || data?.valor_futuro_otimista || 0);
  const valorPessimista = Number(cen.pessimista || data?.valor_futuro_pessimista || 0);
  const horizonte = Math.max(1, Number(cen.horizonte || data?.horizonte_anos || document.getElementById("horizonte_anos")?.value || 5));
  const horizonteMeses = Number(data?.horizonte_meses || detalhes.horizonte_meses || Math.round(horizonte * 12));
  const perda = valorAtual > 0 && valorFuturo > 0 ? Math.max(0, valorAtual - valorFuturo) : 0;
  const depreciacaoTotal = valorAtual > 0 && valorFuturo > 0 ? ((valorAtual - valorFuturo) / valorAtual) * 100 : Number(data?.depreciacao_percentual || 0);
  const taxaAnual = Number(cen.taxaBase || 0) * 100 || Number(data?.taxa_anual_efetiva_percentual || data?.taxa_anual_percentual || 0);
  const taxaReferencia = primeiroValorPositivo(data?.taxa_anual_referencia_percentual, detalhes.taxa_anual_referencia_percentual, curva.taxa_anual_referencia_percentual, curva.depreciacao_media_anual_principal_percentual, curva.depreciacao_media_anual_percentual);
  const taxaMensal = primeiroValorPositivo(data?.taxa_mensal_hibrida_percentual, detalhes.taxa_mensal_hibrida_percentual, curva.taxa_mensal_hibrida_percentual, curva.taxa_mensal_percentual);
  const idadeMeses = Number(data?.idade_entrada_meses || detalhes.idade_entrada_meses || 0);
  const idadeAnos = Number(data?.idade_entrada_anos || detalhes.idade_entrada_anos || (idadeMeses / 12) || 0);
  const similaridade = obterSimilaridadeProfissional(data);
  const inicioCurvaMeses = Number(data?.inicio_curva_meses ?? detalhes.inicio_curva_meses ?? idadeMeses);
  const fimCurvaMeses = Number(data?.fim_curva_meses ?? detalhes.fim_curva_meses ?? (idadeMeses + horizonteMeses));
  const pontosHistoricos = Number(data?.pontos_historicos || detalhes.pontos_historicos || curva.pontos_historicos || auditoria.pontos || auditoria.pontos_historicos || 0);
  const janelaHistoricaMeses = Number(data?.janela_historica_meses || detalhes.janela_historica_meses || curva.janela_historica_meses || auditoria.janela_meses || 0);
  const info = {
    veiculoDescricao: obterVeiculoDescricaoProfissional(data),
    codigoFipe: obterCodigoFipeProfissional(data),
    dataBaseFipe: obterDataBaseFipeProfissional(data),
    valorAtual,
    valorFuturo,
    valorOtimista,
    valorPessimista,
    perda,
    depreciacaoTotal,
    taxaAnual,
    taxaReferencia,
    taxaMensal,
    horizonte,
    horizonteLabel: formatarHorizonteLabel(horizonte),
    horizonteMeses,
    idadeMeses,
    idadeAnos,
    inicioCurvaMeses,
    fimCurvaMeses,
    confianca: primeiroTextoValido(data?.confianca, detalhes.confianca, curva.confianca),
    tipoLabel: tipoMotorizacaoProfissional(data),
    tipoCurva: obterTipoCurvaProfissional(data),
    curvaPorSimilaridade: similaridade.curvaPorSimilaridade,
    modeloReferenciaSimilaridade: similaridade.modeloReferencia,
    origemSimilaridade: similaridade.origem,
    chaveCurvaReferencia: similaridade.chave,
    modeloBase: obterModeloBaseProfissional(data),
    anoBase: obterAnoBaseProfissional(data),
    dataZeroKmBase: obterDataZeroKmBaseProfissional(data),
    pontosHistoricos,
    janelaHistoricaMeses,
    modoPandemia: primeiroTextoValido(data?.modo_pandemia, detalhes.modo_pandemia, curva.modo_pandemia, extrairTextoPorPadroes(textoRelatorioBruto(data), [/Modo pandemia:\s*([^\n\r]+)/i])),
    origemOriginal: limparTextoInternoRelatorio(primeiroTextoValido(data?.origem_curva, detalhes.origem_curva, curva.origem_curva))
  };
  info.baseTecnicaResumo = obterBaseTecnicaResumoProfissional(info);
  return info;
}

function valorLinhaHTML(rotulo, valor, destaque = false) {
  if (!valorInformado(valor)) return "";
  return `<div class="report-metric ${destaque ? "report-metric-highlight" : ""}"><span>${escaparHtml(rotulo)}</span><strong>${escaparHtml(valor)}</strong></div>`;
}

function linhaTabelaProfissional(rotulo, valor) {
  if (!valorInformado(valor)) return "";
  return `<tr><th>${escaparHtml(rotulo)}</th><td>${escaparHtml(valor)}</td></tr>`;
}

function cardCenarioProfissional(nome, valor, texto, classe) {
  if (!(Number(valor) > 0)) return "";
  return `<div class="scenario-card ${classe || ""}"><span>${escaparHtml(nome)}</span><strong>${escaparHtml(formatarMoedaBR(valor))}</strong><small>${escaparHtml(texto || "")}</small></div>`;
}

function montarRelatorioHTMLProfissional(data) {
  const info = montarDadosRelatorioProfissional(data || {});
  const perdaTexto = info.perda > 0 ? formatarMoedaBR(info.perda) : "-";
  const depTexto = valorPercentualTexto(info.depreciacaoTotal);
  const taxaTexto = valorPercentualTexto(info.taxaAnual, 2, "% a.a.");
  const valorAtualTexto = info.valorAtual > 0 ? formatarMoedaBR(info.valorAtual) : "-";
  const valorFuturoTexto = info.valorFuturo > 0 ? formatarMoedaBR(info.valorFuturo) : "-";
  const idadeTexto = info.idadeMeses > 0 ? `${info.idadeMeses} meses (${info.idadeAnos.toFixed(2).replace(".", ",")} anos)` : "0 meses; projeção iniciada como zero km";
  const janelaAplicada = Number.isFinite(info.inicioCurvaMeses) && Number.isFinite(info.fimCurvaMeses) ? `${info.inicioCurvaMeses} a ${info.fimCurvaMeses} meses de idade` : "-";

  const tabelaBase = [
    linhaTabelaProfissional("Tipo de curva", info.tipoCurva),
    linhaTabelaProfissional("Modelo de referência", info.modeloBase),
    linhaTabelaProfissional("Origem da similaridade", info.curvaPorSimilaridade ? info.origemSimilaridade : ""),
    linhaTabelaProfissional("Chave da curva referência", info.curvaPorSimilaridade ? info.chaveCurvaReferencia : ""),
    linhaTabelaProfissional("Coorte ou ano-base", info.anoBase),
    linhaTabelaProfissional("Base zero km da coorte", info.dataZeroKmBase),
    linhaTabelaProfissional("Pontos históricos FIPE", info.pontosHistoricos > 0 ? `${info.pontosHistoricos}` : ""),
    linhaTabelaProfissional("Janela histórica observada", info.janelaHistoricaMeses > 0 ? `${info.janelaHistoricaMeses} meses` : ""),
    linhaTabelaProfissional("Tratamento da pandemia", limparTextoInternoRelatorio(info.modoPandemia))
  ].join("");

  const tabelaAuditoria = [
    linhaTabelaProfissional("Código FIPE", info.codigoFipe),
    linhaTabelaProfissional("Referência FIPE", info.dataBaseFipe),
    linhaTabelaProfissional("Horizonte projetado", `${info.horizonteLabel}${info.horizonteMeses ? ` (${info.horizonteMeses} meses)` : ""}`),
    linhaTabelaProfissional("Idade considerada na curva", idadeTexto),
    linhaTabelaProfissional("Janela aplicada da curva", janelaAplicada),
    linhaTabelaProfissional("Taxa mensal calibrada da curva", info.taxaMensal > 0 ? `${info.taxaMensal.toFixed(4).replace(".", ",")}% a.m.` : ""),
    linhaTabelaProfissional("Taxa anual de referência da curva", info.taxaReferencia > 0 ? `${info.taxaReferencia.toFixed(2).replace(".", ",")}% a.a.` : ""),
    linhaTabelaProfissional("Taxa anual equivalente aplicada", taxaTexto),
    linhaTabelaProfissional("Depreciação total no horizonte", depTexto)
  ].join("");

  return `<div class="professional-report">
    <section class="report-section report-executive">
      <p class="report-kicker">Resumo executivo</p>
      <h3>Resultado aplicado ao veículo consultado</h3>
      <p class="report-lead">A estimativa considera o valor FIPE do veículo selecionado, o horizonte informado e a curva histórica disponível para a base técnica correspondente.</p>
      <div class="report-metric-grid">
        ${valorLinhaHTML("Veículo analisado", info.veiculoDescricao || "Veículo selecionado", true)}
        ${valorLinhaHTML("Valor FIPE atual", valorAtualTexto)}
        ${valorLinhaHTML(`Valor estimado em ${info.horizonteLabel}`, valorFuturoTexto, true)}
        ${valorLinhaHTML("Perda estimada no período", perdaTexto)}
        ${valorLinhaHTML("Depreciação total", depTexto)}
        ${valorLinhaHTML("Taxa anual equivalente", taxaTexto)}
        ${valorLinhaHTML("Confiança", info.confianca || "-")}
        ${valorLinhaHTML("Categoria", info.tipoLabel || "-")}
      </div>
    </section>

    <section class="report-section">
      <p class="report-kicker">Cenários de valor futuro</p>
      <h3>Faixa estimada de depreciação</h3>
      <p class="report-lead">O cenário base é a referência da simulação. Os cenários otimista e pessimista formam uma faixa de sensibilidade para apoiar a decisão econômica.</p>
      <div class="scenario-grid">
        ${cardCenarioProfissional("Base", info.valorFuturo, "Referência principal da análise", "scenario-base")}
        ${cardCenarioProfissional("Otimista", info.valorOtimista, "Menor perda relativa no período", "scenario-optimistic")}
        ${cardCenarioProfissional("Pessimista", info.valorPessimista, "Maior perda relativa no período", "scenario-pessimistic")}
      </div>
    </section>

    <section class="report-section">
      <p class="report-kicker">Base técnica</p>
      <h3>Curva utilizada na estimativa</h3>
      <div class="reference-card">${escaparHtml(info.baseTecnicaResumo)}</div>
      <table class="professional-report-table"><tbody>${tabelaBase || linhaTabelaProfissional("Base técnica", info.baseTecnicaResumo)}</tbody></table>
    </section>

    <section class="report-section methodology-box">
      <p class="report-kicker">Metodologia</p>
      <h3>Como a estimativa é construída</h3>
      <p>O valor de entrada vem da FIPE para o ano e combustível selecionados. A curva de depreciação é calibrada com histórico do próprio modelo ou de uma base técnica de referência, usando a série nominal e a série corrigida pelo IPCA para leitura econômica da trajetória.</p>
      ${info.curvaPorSimilaridade ? `<p><strong>Curva por similaridade:</strong> o veículo analisado mantém seu próprio valor FIPE atual, mas a função/taxa de depreciação é herdada do modelo referência ${escaparHtml(info.modeloReferenciaSimilaridade || info.modeloBase || "informado pelo painel local")}.</p>` : ""}
      <p>Em veículos usados, a projeção considera a idade já percorrida dentro da curva e estima apenas a depreciação futura. Isso evita tratar um veículo usado como se fosse zero km.</p>
      <p>O resultado deve ser interpretado como estimativa estatística de valor futuro, não como avaliação comercial individual. Estado de conservação, quilometragem, versão, região e negociação podem alterar o preço final de mercado.</p>
    </section>

    <section class="report-section">
      <p class="report-kicker">Auditoria técnica</p>
      <h3>Parâmetros técnicos usados</h3>
      <p class="report-lead">A memória técnica abaixo resume os parâmetros necessários para auditar o cálculo sem expor mensagens internas do sistema.</p>
      <table class="professional-report-table"><tbody>${tabelaAuditoria}</tbody></table>
    </section>
  </div>`;
}

function montarRelatorioTextual(data, origem = "curva") {
  const info = montarDadosRelatorioProfissional(data || {});
  return [
    "Relatório profissional de depreciação veicular",
    `Veículo analisado: ${info.veiculoDescricao || "veículo selecionado"}`,
    `Valor FIPE atual: ${info.valorAtual > 0 ? formatarMoedaBR(info.valorAtual) : "não disponível"}`,
    `Valor estimado no horizonte: ${info.valorFuturo > 0 ? formatarMoedaBR(info.valorFuturo) : "não disponível"}`,
    `Horizonte de análise: ${info.horizonteLabel}`,
    `Depreciação total: ${valorPercentualTexto(info.depreciacaoTotal)}`,
    `Taxa anual equivalente: ${valorPercentualTexto(info.taxaAnual, 2, "% a.a.")}`,
    `Base técnica utilizada: ${info.baseTecnicaResumo}`,
    ...(info.curvaPorSimilaridade ? [
      `Tipo de curva: curva herdada por similaridade`,
      `Modelo referência: ${info.modeloReferenciaSimilaridade || info.modeloBase || "não informado"}`,
      `Origem da similaridade: ${info.origemSimilaridade || "não informada"}`,
      `Chave da curva referência: ${info.chaveCurvaReferencia || "não informada"}`
    ] : [])
  ].join("\n");
}


function preencherRelatorioTextual(data, origem = "curva") {
  const el = document.getElementById("relatorio_textual");
  if (!el) return;
  el.classList.add("professional-report-shell");
  el.innerHTML = montarRelatorioHTMLProfissional(data || {});
}

function preencherRelatorio(data, origem = "curva") {
  preencherRelatorioTextual(data, origem);
  const corpo = document.getElementById("detalhes_corpo");
  if (corpo) corpo.innerHTML = "";
  const tabela = document.querySelector("#aba_relatorio_tecnico .details-table");
  if (tabela) tabela.classList.add("hidden");
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
  const seqConsulta = ++consultaDepreciacaoSeq;

  mostrarResultadoArea(true);
  mostrarAuditoriaArea(false);
  mostrarAuditoriaCalculoArea(false);
  mostrarAbasDepreciacao(false);
  atualizarFeedbackCalculo("Buscando curva histórica na base local...", 25, true);
  atualizarStatusResultado("Buscando curva histórica...", "muted");
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
    if (seqConsulta !== consultaDepreciacaoSeq) return;
    ultimoResumoDepreciacao = data;

    if (data.encontrado) {
      atualizarFeedbackCalculo("Curva localizada. Gerando relatório profissional...", 100, false);
      atualizarStatusResultado("Estimativa gerada com base FIPE, curva histórica e horizonte selecionado.", "encontrado");
      preencherResumo(data);
      configurarBotoesResultado(true, false, confiancaEhBaixaOuExploratoria(data.confianca));
      mostrarGraficoBarrasArea(true);
      mostrarAuditoriaArea(true);
      preencherRelatorio(data, "curva salva");
      renderizarGraficosDepreciacao(data);
      renderizarAuditoriaCalculo(data);
      mostrarAbasDepreciacao(true);
      selecionarAbaPrincipalDepreciacao("resultado");
      if (estaEmModoBridgeTCO()) mostrarDetalhes();
    } else {
      atualizarFeedbackCalculo("Curva não encontrada. Processamento deve ser feito no painel local.", 100, false);
      atualizarStatusResultado((data.mensagem || "Curva não encontrada.") + " Processe esta curva no painel local e envie para o Render.", "nao-encontrado");
      limparResumoParcialApenasValor(data.valor_atual || detalheFipe.valor_atual);
      mostrarGraficoBarrasArea(false);
      mostrarAuditoriaArea(false);
      limparAuditoriaCalculo();
      limparAuditoriaCalculo();
      configurarBotoesResultado(false, true);
    }
  } catch (e) {
    if (seqConsulta !== consultaDepreciacaoSeq) return;
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
    atualizarTerminalV1917({ terminal_linhas: ["[local] Iniciando diagnóstico técnico. O terminal será atualizado a cada lote seguro do Render..."] });
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
  atualizarFeedbackCalculo("Rodando diagnóstico técnico em lote seguro...", 40, true);

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
      const msg = `Resposta inválida do servidor no diagnóstico técnico. HTTP ${resp.status}. ${rawText.slice(0, 300)}`;
      atualizarStatusResultado(msg, "erro");
      atualizarFeedbackCalculo(msg, 100, true);
      return;
    }
    if (!resp.ok) {
      const msg = data.mensagem || data.erro || `Erro HTTP ${resp.status} no diagnóstico técnico.`;
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
    if (rel) {
      rel.classList.remove("professional-report-shell");
      rel.textContent = data.relatorio_textual || data.mensagem || "Diagnóstico técnico concluído.";
    }
    if (corpo) {
      corpo.closest("table")?.classList.remove("hidden");
      const am = data.amostragem_referencias || {};
      const primeira = data.primeira_aparicao || {};
      const zero = data.zero_km_base || {};
      corpo.innerHTML = "";
      adicionarDetalhe(corpo, "Motor", data.motor || "Rotina técnica paralela");
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
    atualizarStatusResultado(data.mensagem || "Diagnóstico técnico executado.", data.ok ? "encontrado" : "erro");
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
    const msg = `Erro ao montar diagnóstico técnico: ${e && e.message ? e.message : e}`;
    atualizarStatusResultado(msg, "erro");
    atualizarFeedbackCalculo(msg, 100, true);
  } finally {
    if (btn) {
      if (continuarAutomaticamente) {
        btn.disabled = true;
        btn.textContent = "Continuando diagnóstico técnico...";
      } else {
        btn.disabled = false;
        btn.textContent = manterContinuar ? "Continuar diagnóstico técnico" : "Diagnóstico técnico";
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
      atualizarFeedbackCalculo("Curva calculada. Montando relatório profissional...", 100, true);
      if (data.resultado) {
        ultimoResumoDepreciacao = data.resultado;
        atualizarStatusResultado("Estimativa calculada e registrada com base técnica para o veículo selecionado.", "encontrado");
        preencherResumo(data.resultado);
        configurarBotoesResultado(true, false, confiancaEhBaixaOuExploratoria(data.resultado?.confianca));
        mostrarGraficoBarrasArea(true);
        mostrarAuditoriaArea(true);
        preencherRelatorio({ ...data.resultado, motor: data.motor }, "cálculo sob demanda");
        renderizarGraficosDepreciacao(data.resultado);
        renderizarAuditoriaCalculo(data.resultado);
        mostrarAbasDepreciacao(true);
        selecionarAbaPrincipalDepreciacao("resultado");
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
  return String(txt || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function registrarModelosComCurva(lista) {
  modelosComCurva = new Set();
  codigosModelosComCurva = new Set();
  marcadoresCurvasPorNome = new Map();
  marcadoresCurvasPorCodigo = new Map();

  const registrarChave = (chave, marcador) => {
    const normalizada = normalizarBusca(chave);
    if (!normalizada) return;
    modelosComCurva.add(normalizada);
    marcadoresCurvasPorNome.set(normalizada, marcador);
  };

  (lista || []).forEach(item => {
    const tipoCurva = String(item.tipo_curva || item.tipo_curva_aplicada || (item.curva_por_similaridade ? "similaridade" : "propria")).toLowerCase();
    const marcador = {
      ...item,
      tipo_curva: tipoCurva === "similaridade" ? "similaridade" : "propria",
      simbolo: tipoCurva === "similaridade" ? "" : "✓",
    };
    const modelo = item.modelo || item.titulo || "";
    const titulo = item.titulo || "";
    const marcaModelo = `${item.marca || ""} ${item.modelo || ""}`;
    const codigoModelo = String(item.codigo_modelo || item.modelo_id || "").trim();
    registrarChave(modelo, marcador);
    registrarChave(titulo, marcador);
    registrarChave(marcaModelo, marcador);
    if (codigoModelo) {
      codigosModelosComCurva.add(codigoModelo);
      marcadoresCurvasPorCodigo.set(codigoModelo, marcador);
    }
  });
  marcadoresCurvasCarregados = true;
  window.PLUGVE_MODELOS_COM_CURVA = modelosComCurva;
  window.PLUGVE_MARCADORES_CURVAS = marcadoresCurvasPorNome;
  window.PLUGVE_MARCADORES_CURVAS_CODIGO = marcadoresCurvasPorCodigo;
  if (typeof window.aplicarChecksModelosFipe === "function") {
    window.aplicarChecksModelosFipe();
    setTimeout(() => window.aplicarChecksModelosFipe?.(), 80);
    setTimeout(() => window.aplicarChecksModelosFipe?.(), 250);
  }
}

function obterMarcadorCurva(textoModelo, codigoModelo = "") {
  const codigo = String(codigoModelo || "").trim();
  if (codigo && marcadoresCurvasPorCodigo.has(codigo)) return marcadoresCurvasPorCodigo.get(codigo);
  const alvo = normalizarBusca(textoModelo);
  if (!alvo) return null;
  if (marcadoresCurvasPorNome.has(alvo)) return marcadoresCurvasPorNome.get(alvo);
  return null;
}

function modeloTemCurva(textoModelo, codigoModelo = "") {
  return Boolean(obterMarcadorCurva(textoModelo, codigoModelo));
}


function limparCachesMarcadoresCurvasAntigos() {
  try {
    const prefixo = "curve:depreciacao:marcadores:";
    Object.keys(localStorage || {}).forEach((chave) => {
      if (chave.startsWith(prefixo) && chave !== MARCADORES_CURVAS_CACHE_KEY) {
        localStorage.removeItem(chave);
      }
    });
  } catch (e) {}
}

function lerCacheMarcadoresCurvas() {
  limparCachesMarcadoresCurvasAntigos();
  try {
    const bruto = localStorage.getItem(MARCADORES_CURVAS_CACHE_KEY);
    if (!bruto) return null;
    const item = JSON.parse(bruto);
    if (!item?.salvoEm || (Date.now() - item.salvoEm) > MARCADORES_CURVAS_CACHE_TTL) {
      localStorage.removeItem(MARCADORES_CURVAS_CACHE_KEY);
      return null;
    }
    return item.dados || null;
  } catch (e) {
    return null;
  }
}

function salvarCacheMarcadoresCurvas(dados) {
  try {
    localStorage.setItem(MARCADORES_CURVAS_CACHE_KEY, JSON.stringify({ salvoEm: Date.now(), dados }));
  } catch (e) {}
}

function aplicarMarcadoresCurvasData(data) {
  const itens = Array.isArray(data?.modelos)
    ? data.modelos
    : [...(data?.curvas_combustao || []), ...(data?.curvas_eletrico || [])];
  registrarModelosComCurva(itens);
}

function carregarMarcadoresCurvasSalvas() {
  const cache = lerCacheMarcadoresCurvas();
  if (cache) aplicarMarcadoresCurvasData(cache);
  if (carregamentoMarcadoresCurvasIniciado) return;
  carregamentoMarcadoresCurvasIniciado = true;
  fetch("/api/depreciacao/marcadores_curvas?v=20260705_dep_visual_sem_check_v3", { cache: "no-store", headers: { Accept: "application/json", "Cache-Control": "no-cache", "Pragma": "no-cache" } })
    .then(resp => resp.ok ? resp.json() : {})
    .then(data => {
      if (!data || data.ok === false) return;
      salvarCacheMarcadoresCurvas(data);
      aplicarMarcadoresCurvasData(data);
    })
    .catch(() => {});
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

function calcularEscalaLinearPainel(valores, divisoes = 5) {
  const nums = (valores || []).map(Number).filter(v => Number.isFinite(v) && v > 0);
  if (!nums.length) return { min: 0, max: 1, range: 1, ticks: [1, 0.5, 0] };
  const minValor = Math.min(...nums);
  const maxValor = Math.max(...nums);
  const bruto = Math.max(1, maxValor - minValor);
  const alvoStep = bruto / Math.max(1, divisoes);
  const potencia = Math.pow(10, Math.floor(Math.log10(alvoStep)));
  const fracao = alvoStep / potencia;
  let niceFracao = 1;
  if (fracao <= 1) niceFracao = 1;
  else if (fracao <= 2) niceFracao = 2;
  else if (fracao <= 2.5) niceFracao = 2.5;
  else if (fracao <= 5) niceFracao = 5;
  else niceFracao = 10;
  const step = niceFracao * potencia;
  const margem = Math.max(bruto * 0.04, step * 0.15);
  let min = Math.floor((minValor - margem) / step) * step;
  let max = Math.ceil((maxValor + margem) / step) * step;
  if (min < 0 && minValor > step) min = 0;
  if (max <= min) max = min + step;
  const ticks = [];
  for (let v = max; v >= min - step * 0.001; v -= step) {
    ticks.push(Math.max(0, Math.round(v * 100) / 100));
    if (ticks.length > 12) break;
  }
  return { min, max, range: max - min, step, ticks };
}

function valorNumericoPositivo(valor) {
  const n = parseMoedaTecnica(valor);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function extrairNumeroPorPadroes(texto, padroes) {
  const txt = String(texto || "");
  for (const padrao of padroes) {
    const m = padrao.exec(txt);
    if (m && m[1]) {
      const n = valorNumericoPositivo(m[1]);
      if (n > 0) return n;
    }
  }
  return 0;
}

function extrairCenariosDoRelatorioTecnico(data) {
  const txt = textoRelatorioCompleto(data);
  if (!txt.trim()) return {};
  const valorAtual = extrairNumeroPorPadroes(txt, [
    /Valor\s+FIPE\s+atual\s*:\s*R\$\s*([0-9.,]+)/i,
    /Valor\s+atual\s+FIPE\s*:\s*R\$\s*([0-9.,]+)/i,
    /Preço\s+FIPE\s+real\s+atual\s*:\s*R\$\s*([0-9.,]+)/i,
    /Valor\s+FIPE\s+inicial\s*:\s*R\$\s*([0-9.,]+)/i
  ]);
  const base = extrairNumeroPorPadroes(txt, [
    /Valor\s+futuro\s+base\s*:\s*R\$\s*([0-9.,]+)/i,
    /Valor\s+futuro\s+estimado(?:\s*\([^)]*\))?\s*:\s*R\$\s*([0-9.,]+)/i,
    /Valor\s+estimado\s+ao\s+final\s+do\s+horizonte\s*:\s*R\$\s*([0-9.,]+)/i
  ]);
  const otimista = extrairNumeroPorPadroes(txt, [
    /Valor\s+futuro\s+otimista\s*:\s*R\$\s*([0-9.,]+)/i,
    /Otimista\s+final\s*:?\s*R\$\s*([0-9.,]+)/i
  ]);
  const pessimista = extrairNumeroPorPadroes(txt, [
    /Valor\s+futuro\s+pessimista\s*:\s*R\$\s*([0-9.,]+)/i,
    /Pessimista\s+final\s*:?\s*R\$\s*([0-9.,]+)/i
  ]);
  let horizonte = extrairNumeroPorPadroes(txt, [
    /Horizonte(?:\s+selecionado|\s+da\s+análise)?\s*:?\s*([0-9]+(?:[,.][0-9]+)?)\s*anos?/i
  ]);
  if (!horizonte) {
    const m = /Valor\s+futuro\s+estimado\s*\((\d+)\s*meses\)/i.exec(txt) || /Horizonte[^\n]*(\d+)\s*meses/i.exec(txt);
    if (m && m[1]) horizonte = Math.max(1, Number(m[1]) / 12);
  }
  return { valorAtual, base, otimista, pessimista, horizonte };
}

function horizonteRelatorioDoResultado(data) {
  const curva = data?.detalhes?.curva || {};
  const rel = extrairCenariosDoRelatorioTecnico(data);
  const candidatos = [
    data?.horizonte_anos,
    document.getElementById("horizonte_anos")?.value,
    data?.horizonte_relatorio_anos,
    curva.horizonte_relatorio_anos,
    rel.horizonte
  ];
  for (const valor of candidatos) {
    const n = parseMoedaTecnica(valor);
    if (Number.isFinite(n) && n > 0) return n;
  }
  return 5;
}

function valorCurvaPorHorizonte(curva, horizonte, tipo = "base") {
  const h = Math.max(1, Math.round(Number(horizonte || 0)));
  const mapa = tipo === "base"
    ? [`valor_${h}ano`, "valor_futuro_base", "valor_futuro", "valor_estimado_futuro_principal"]
    : tipo === "otimista"
      ? [`valor_${h}ano_otimista`, "valor_futuro_otimista", "valor_otimista_final"]
      : [`valor_${h}ano_pessimista`, "valor_futuro_pessimista", "valor_pessimista_final"];
  for (const chave of mapa) {
    const n = valorNumericoPositivo(curva?.[chave]);
    if (n > 0) return n;
  }
  return 0;
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
  const escala = calcularEscalaLinearPainel(valores, 5);
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
    const ehTituloSecao = !/^[-•]/.test(l) && (/^\d+\.\s+/.test(l) || /^[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9 ._-]+$/.test(l));
    if (ehCorrigido) {
      if (ehTituloSecao && (/HIST[ÓO]RICO.*CORRIGIDO.*IPCA|HIST[ÓO]RICO.*IPCA|BASE CORRIGIDA.*IPCA|CORRIGIDO PELO IPCA/.test(up))) {
        emSecao = true;
        encontrouSecao = true;
        continue;
      }
    } else {
      if (ehTituloSecao && (/PROGRESS[ÃA]O HIST[ÓO]RICA|HIST[ÓO]RICO FIPE|HIST[ÓO]RICO DA BASE/.test(up)) && !/CORRIGIDO|IPCA/.test(up)) {
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
    if (ehCorrigido && !emSecao) continue;
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

function historicoDiretoPlugVE(data, chaves, camposPreferenciais = []) {
  const camposPadrao = [
    ...camposPreferenciais,
    "valor", "valor_fipe", "preco", "price", "preco_nominal", "preco_corrigido"
  ];
  const vistosCampos = [];
  camposPadrao.forEach(campo => {
    if (campo && !vistosCampos.includes(campo)) vistosCampos.push(campo);
  });

  for (const chave of chaves) {
    const bruto = chave.split('.').reduce((obj, k) => obj && obj[k], data);
    if (Array.isArray(bruto) && bruto.length) {
      const pontos = bruto.map(item => {
        let valor = 0;
        for (const campo of vistosCampos) {
          valor = parseMoedaTecnica(item?.[campo]);
          if (Number.isFinite(valor) && valor > 0) break;
        }
        return {
          data: String(item.data || item.referencia || item.data_referencia || item.mes_referencia || item.mes || "").slice(0, 7),
          valor,
          tipo: String(item.tipo || item.observacao || item.status || "usado").trim()
        };
      }).filter(p => p.data && Number.isFinite(p.valor) && p.valor > 0).sort((a, b) => String(a.data).localeCompare(String(b.data)));
      if (pontos.length) return pontos;
    }
  }
  return [];
}

function seriesHistoricasSaoIguais(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || !a.length || a.length !== b.length) return false;
  let iguais = 0;
  for (let i = 0; i < a.length; i += 1) {
    if (String(a[i]?.data || "") !== String(b[i]?.data || "")) return false;
    const va = Number(a[i]?.valor || 0);
    const vb = Number(b[i]?.valor || 0);
    if (va > 0 && vb > 0 && Math.abs(va - vb) <= Math.max(1, va * 0.002)) iguais += 1;
  }
  return iguais >= Math.max(3, Math.floor(a.length * 0.92));
}

function extrairHistoricoNominalDoRelatorio(data) {
  const direto = historicoDiretoPlugVE(data, ["historico_mensal", "detalhes.historico_mensal"], ["preco_nominal", "valor_fipe", "valor", "preco"]);
  if (direto.length) return direto;
  const txt = textoRelatorioCompleto(data);
  const doRelatorio = extrairPontosHistoricosDeTextoPlugVE(txt, "nominal");
  if (doRelatorio.length) return doRelatorio;
  return [];
}

function extrairHistoricoCorrigidoDoRelatorio(data) {
  const direto = historicoDiretoPlugVE(data, [
    "historico_mensal_corrigido",
    "detalhes.historico_mensal_corrigido",
    "historico_ipca",
    "detalhes.historico_ipca"
  ], ["preco_corrigido", "valor", "valor_corrigido", "preco_real"]);
  const nominal = extrairHistoricoNominalDoRelatorio(data);
  if (direto.length && !seriesHistoricasSaoIguais(direto, nominal)) return direto;

  const txt = textoRelatorioCompleto(data);
  const doRelatorio = extrairPontosHistoricosDeTextoPlugVE(txt, "corrigido");
  if (doRelatorio.length && !seriesHistoricasSaoIguais(doRelatorio, nominal)) return doRelatorio;

  // Se não houver série IPCA real, não desenha a nominal de novo como se fosse corrigida.
  return [];
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
  const escala = calcularEscalaLinearPainel(valores, 5);
  const w = 980, h = 420, padL = 92, padR = 36, padT = 30, padB = 70;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const x = idx => padL + (idx / Math.max(1, pontos.length - 1)) * plotW;
  const y = valor => padT + ((escala.max - valor) / escala.range) * plotH;
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "line-chart-svg grid-chart-svg");

  (escala.ticks || []).forEach(valor => {
    const yy = y(valor);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", padL);
    line.setAttribute("x2", w - padR);
    line.setAttribute("y1", yy);
    line.setAttribute("y2", yy);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);

    const label = document.createElementNS(svgNS, "text");
    label.setAttribute("x", padL - 10);
    label.setAttribute("y", yy + 4);
    label.setAttribute("text-anchor", "end");
    label.setAttribute("class", "chart-label-svg");
    label.textContent = formatarMoedaBR(valor).replace(",00", "");
    svg.appendChild(label);
  });
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

function taxaAnualAPartirDoValorFinal(valorAtual, valorFinal, horizonte) {
  const atual = Number(valorAtual || 0);
  const final = Number(valorFinal || 0);
  const anos = Math.max(1, Number(horizonte || 1));
  if (!(atual > 0) || !(final > 0)) return 0;
  const taxa = 1 - Math.pow(final / atual, 1 / anos);
  return Number.isFinite(taxa) ? Math.max(0, taxa) : 0;
}

function primeiroValorPositivo(...valores) {
  for (const valor of valores) {
    const n = valorNumericoPositivo(valor);
    if (n > 0) return n;
  }
  return 0;
}

function horizonteSelecionadoDaTela(data = null) {
  const el = document.getElementById("horizonte_anos");
  const candidatos = [el?.value, data?.horizonte_anos, data?.horizonte_relatorio_anos, 5];
  for (const valor of candidatos) {
    const n = parseMoedaTecnica(valor);
    if (Number.isFinite(n) && n > 0) {
      const limitado = Math.max(1, Math.min(20, n));
      return limitado;
    }
  }
  return 5;
}

function valorCurvaHorizonteExato(curva, horizonte, tipo = "base") {
  const h = Math.max(1, Math.round(Number(horizonte || 0)));
  const chaves = tipo === "base"
    ? [`valor_${h}ano`, `valor_${h}_anos`, `valor_${h}anos`, `valor_${h}ano_base`, `valor_${h}_anos_base`]
    : tipo === "otimista"
      ? [`valor_${h}ano_otimista`, `valor_${h}_anos_otimista`, `valor_${h}anos_otimista`]
      : [`valor_${h}ano_pessimista`, `valor_${h}_anos_pessimista`, `valor_${h}anos_pessimista`];
  for (const chave of chaves) {
    const n = valorNumericoPositivo(curva?.[chave]);
    if (n > 0) return n;
  }
  return 0;
}

function projetarValorPorTaxa(valorAtual, taxaDecimal, horizonte) {
  const atual = Number(valorAtual || 0);
  const taxa = Number(taxaDecimal || 0);
  const anos = Math.max(1, Number(horizonte || 1));
  if (!(atual > 0) || !(taxa >= 0)) return 0;
  return atual * Math.pow(1 - taxa, anos);
}

function obterFinalProjecaoBackend(data) {
  const serie = Array.isArray(data?.projecao_mensal)
    ? data.projecao_mensal
    : (Array.isArray(data?.detalhes?.projecao_mensal) ? data.detalhes.projecao_mensal : []);
  if (!serie.length) return {};
  const ultimo = serie[serie.length - 1] || {};
  return {
    base: primeiroValorPositivo(ultimo.valor_base, ultimo.base, ultimo.valor),
    otimista: primeiroValorPositivo(ultimo.valor_otimista, ultimo.otimista),
    pessimista: primeiroValorPositivo(ultimo.valor_pessimista, ultimo.pessimista)
  };
}

function obterCenariosDoResultado(data) {
  const detalhes = data?.detalhes || {};
  const curva = detalhes.curva || {};
  const rel = extrairCenariosDoRelatorioTecnico(data);
  const horizonteSelecionado = horizonteSelecionadoDaTela(data);
  const horizonteReferencia = Math.max(1, Number(horizonteRelatorioDoResultado(data) || data?.horizonte_anos || horizonteSelecionado || 5));
  const projFinal = obterFinalProjecaoBackend(data);

  // Prioridade máxima: resultado aplicado pelo backend para a seleção atual
  // (valor FIPE escolhido + horizonte escolhido + offset de idade). O relatório
  // técnico importado pode descrever a curva base, mas não pode sobrescrever a
  // aplicação atual de um veículo usado.
  const atual = primeiroValorPositivo(
    data?.valor_atual,
    detalhes?.veiculo?.valor_atual,
    curva.valor_fipe_atual,
    curva.preco_atual_real,
    rel.valorAtual
  );

  const baseBackend = primeiroValorPositivo(data?.valor_futuro_base, data?.valor_futuro, projFinal.base);
  const otimistaBackend = primeiroValorPositivo(data?.valor_futuro_otimista, projFinal.otimista);
  const pessimistaBackend = primeiroValorPositivo(data?.valor_futuro_pessimista, projFinal.pessimista);

  const taxaBaseBackend = primeiroValorPositivo(
    data?.taxa_anual_base_efetiva_percentual,
    data?.taxa_anual_efetiva_percentual,
    data?.taxa_anual_percentual
  ) / 100;
  const taxaOtimistaBackend = primeiroValorPositivo(data?.taxa_anual_otimista_efetiva_percentual) / 100;
  const taxaPessimistaBackend = primeiroValorPositivo(data?.taxa_anual_pessimista_efetiva_percentual) / 100;

  const taxaFallbackPercent = primeiroValorPositivo(
    data?.taxa_anual_referencia_percentual,
    curva.taxa_para_plataforma_percentual,
    curva.depreciacao_media_anual_principal_percentual,
    curva.depreciacao_media_anual_percentual
  );
  const calculadoFallback = calcularCenarios(atual, taxaFallbackPercent, horizonteSelecionado);

  const baseRelatorio = primeiroValorPositivo(rel.base, valorCurvaPorHorizonte(curva, horizonteReferencia, "base"));
  const otimistaRelatorio = primeiroValorPositivo(rel.otimista, valorCurvaPorHorizonte(curva, horizonteReferencia, "otimista"));
  const pessimistaRelatorio = primeiroValorPositivo(rel.pessimista, valorCurvaPorHorizonte(curva, horizonteReferencia, "pessimista"));

  const baseExata = valorCurvaHorizonteExato(curva, horizonteSelecionado, "base");
  const otimistaExata = valorCurvaHorizonteExato(curva, horizonteSelecionado, "otimista");
  const pessimistaExata = valorCurvaHorizonteExato(curva, horizonteSelecionado, "pessimista");

  const horizonteDados = Number(data?.horizonte_anos || horizonteSelecionado);
  const mesmoHorizonteBackend = Math.abs(horizonteDados - horizonteSelecionado) < 0.01;
  const mesmoHorizonteRelatorio = Math.abs(horizonteSelecionado - horizonteReferencia) < 0.01;

  const base = primeiroValorPositivo(
    mesmoHorizonteBackend ? baseBackend : 0,
    baseExata,
    mesmoHorizonteRelatorio ? baseRelatorio : 0,
    taxaBaseBackend ? projetarValorPorTaxa(atual, taxaBaseBackend, horizonteSelecionado) : 0,
    calculadoFallback.base
  );
  const otimista = primeiroValorPositivo(
    mesmoHorizonteBackend ? otimistaBackend : 0,
    otimistaExata,
    mesmoHorizonteRelatorio ? otimistaRelatorio : 0,
    taxaOtimistaBackend ? projetarValorPorTaxa(atual, taxaOtimistaBackend, horizonteSelecionado) : 0,
    calculadoFallback.otimista
  );
  const pessimista = primeiroValorPositivo(
    mesmoHorizonteBackend ? pessimistaBackend : 0,
    pessimistaExata,
    mesmoHorizonteRelatorio ? pessimistaRelatorio : 0,
    taxaPessimistaBackend ? projetarValorPorTaxa(atual, taxaPessimistaBackend, horizonteSelecionado) : 0,
    calculadoFallback.pessimista
  );

  return {
    atual,
    base,
    otimista,
    pessimista,
    taxaBase: taxaAnualAPartirDoValorFinal(atual, base, horizonteSelecionado) || taxaBaseBackend || calculadoFallback.taxaBase,
    taxaOtimista: taxaAnualAPartirDoValorFinal(atual, otimista, horizonteSelecionado) || taxaOtimistaBackend || calculadoFallback.taxaOtimista,
    taxaPessimista: taxaAnualAPartirDoValorFinal(atual, pessimista, horizonteSelecionado) || taxaPessimistaBackend || calculadoFallback.taxaPessimista,
    horizonte: horizonteSelecionado,
    horizonteReferencia
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
    bar.className = `bar-chart-bar ${String(item.label || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")}`;
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

function formatarHorizonteLabel(anos) {
  const n = Number(anos || 0);
  if (!Number.isFinite(n) || n <= 0) return "-";
  if (n < 1) return `${Math.round(n * 12)} meses`;
  const inteiro = Math.abs(n - Math.round(n)) < 0.01;
  const texto = inteiro ? String(Math.round(n)) : n.toFixed(1).replace(".", ",");
  return `${texto} ${Math.abs(n - 1) < 0.01 ? "ano" : "anos"}`;
}

function serieProjecaoBackend(data) {
  const serie = Array.isArray(data?.projecao_mensal)
    ? data.projecao_mensal
    : (Array.isArray(data?.detalhes?.projecao_mensal) ? data.detalhes.projecao_mensal : []);
  return serie
    .map(p => ({
      mes: Number(p.mes || 0),
      idadeMeses: Number(p.idade_meses ?? p.idadeMeses ?? p.idade_curva_meses ?? p.mes ?? 0),
      base: Number(p.valor_base || p.base || 0),
      otimista: Number(p.valor_otimista || p.otimista || 0),
      pessimista: Number(p.valor_pessimista || p.pessimista || 0),
      fatorBase: Number(p.fator_base || p.fatorBase || 0),
      fatorOtimista: Number(p.fator_otimista || p.fatorOtimista || 0),
      fatorPessimista: Number(p.fator_pessimista || p.fatorPessimista || 0)
    }))
    .filter(p => Number.isFinite(p.mes) && p.mes >= 0 && (p.base > 0 || p.otimista > 0 || p.pessimista > 0));
}

function calcularTaxaMensalEquivalente(valorInicial, valorFinal, meses) {
  const vi = Number(valorInicial || 0);
  const vf = Number(valorFinal || 0);
  const m = Math.max(1, Number(meses || 1));
  if (!(vi > 0) || !(vf > 0)) return 0;
  const taxa = 1 - Math.pow(vf / vi, 1 / m);
  return Number.isFinite(taxa) ? Math.max(0, taxa) : 0;
}

function construirSeriesProjecaoCalculo(data) {
  const cen = obterCenariosDoResultado(data || {});
  const info = montarDadosRelatorioProfissional(data || {});
  const horizonte = Math.max(1, Number(cen.horizonte || info.horizonte || 5));
  let meses = Math.max(1, Number(info.horizonteMeses || Math.round(horizonte * 12)));
  const serieBackend = serieProjecaoBackend(data || {});
  let fonte = "equivalencia_exponencial";
  let linhas = [];

  if (serieBackend.length >= 2) {
    fonte = "serie_mensal_backend";
    meses = Math.max(meses, ...serieBackend.map(ponto => Number(ponto.mes || 0)));
    linhas = serieBackend
      .filter(ponto => Number.isFinite(ponto.mes) && ponto.mes >= 0)
      .sort((a, b) => a.mes - b.mes)
      .map(ponto => {
        const base = ponto.base || 0;
        const otimista = ponto.otimista || 0;
        const pessimista = ponto.pessimista || 0;
        return {
          mes: Math.round(ponto.mes),
          idadeMeses: Number.isFinite(ponto.idadeMeses) ? Math.round(ponto.idadeMeses) : Math.round(info.idadeMeses + ponto.mes),
          base,
          otimista,
          pessimista,
          fatorBase: ponto.fatorBase || (info.valorAtual > 0 && base > 0 ? base / info.valorAtual : 0),
          fatorOtimista: ponto.fatorOtimista || (info.valorAtual > 0 && otimista > 0 ? otimista / info.valorAtual : 0),
          fatorPessimista: ponto.fatorPessimista || (info.valorAtual > 0 && pessimista > 0 ? pessimista / info.valorAtual : 0),
          perdaBase: info.valorAtual > 0 && base > 0 ? Math.max(0, info.valorAtual - base) : 0,
          depreciacaoBase: info.valorAtual > 0 && base > 0 ? Math.max(0, (1 - base / info.valorAtual) * 100) : 0
        };
      });
  } else {
    const taxaBaseMensal = calcularTaxaMensalEquivalente(info.valorAtual, cen.base, meses);
    const taxaOtimistaMensal = calcularTaxaMensalEquivalente(info.valorAtual, cen.otimista, meses);
    const taxaPessimistaMensal = calcularTaxaMensalEquivalente(info.valorAtual, cen.pessimista, meses);
    linhas = Array.from({ length: meses + 1 }, (_, mes) => {
      const base = info.valorAtual * Math.pow(1 - taxaBaseMensal, mes);
      const otimista = info.valorAtual * Math.pow(1 - taxaOtimistaMensal, mes);
      const pessimista = info.valorAtual * Math.pow(1 - taxaPessimistaMensal, mes);
      return {
        mes,
        idadeMeses: Math.round(info.idadeMeses + mes),
        base,
        otimista,
        pessimista,
        fatorBase: info.valorAtual > 0 ? base / info.valorAtual : 0,
        fatorOtimista: info.valorAtual > 0 ? otimista / info.valorAtual : 0,
        fatorPessimista: info.valorAtual > 0 ? pessimista / info.valorAtual : 0,
        perdaBase: info.valorAtual > 0 ? Math.max(0, info.valorAtual - base) : 0,
        depreciacaoBase: info.valorAtual > 0 ? Math.max(0, (1 - base / info.valorAtual) * 100) : 0
      };
    });
  }

  if (linhas.length) {
    const ultima = linhas[linhas.length - 1];
    if (cen.base > 0) ultima.base = cen.base;
    if (cen.otimista > 0) ultima.otimista = cen.otimista;
    if (cen.pessimista > 0) ultima.pessimista = cen.pessimista;
    ultima.fatorBase = info.valorAtual > 0 && ultima.base > 0 ? ultima.base / info.valorAtual : ultima.fatorBase;
    ultima.fatorOtimista = info.valorAtual > 0 && ultima.otimista > 0 ? ultima.otimista / info.valorAtual : ultima.fatorOtimista;
    ultima.fatorPessimista = info.valorAtual > 0 && ultima.pessimista > 0 ? ultima.pessimista / info.valorAtual : ultima.fatorPessimista;
    ultima.perdaBase = info.valorAtual > 0 && ultima.base > 0 ? Math.max(0, info.valorAtual - ultima.base) : ultima.perdaBase;
    ultima.depreciacaoBase = info.valorAtual > 0 && ultima.base > 0 ? Math.max(0, (1 - ultima.base / info.valorAtual) * 100) : ultima.depreciacaoBase;
  }

  let baseAnterior = null;
  linhas.forEach((linha) => {
    const baseAtual = Number(linha.base || 0);
    linha.taxaMesBase = baseAnterior && baseAnterior > 0 && baseAtual > 0
      ? Math.max(0, (1 - baseAtual / baseAnterior) * 100)
      : 0;
    if (baseAtual > 0) baseAnterior = baseAtual;
  });

  return { info, cen, horizonte, meses, fonte, linhas };
}

function formatarDecimalAuditoria(valor, casas = 6) {
  const n = Number(valor || 0);
  if (!Number.isFinite(n)) return "-";
  return n.toFixed(casas).replace(".", ",");
}

function formatarPercentualAuditoria(valor, casas = 4) {
  const n = Number(valor || 0);
  if (!Number.isFinite(n)) return "-";
  return `${n.toFixed(casas).replace(".", ",")}%`;
}

function linhaAuditoriaKV(rotulo, valor) {
  if (!valorInformado(valor)) return "";
  return `<div class="audit-kv"><span>${escaparHtml(rotulo)}</span><strong>${escaparHtml(valor)}</strong></div>`;
}

function montarTabelaMemoriaMensalHTML(memoria) {
  const linhas = memoria.linhas || [];
  if (!linhas.length) return `<p class="muted">Série mensal não disponível para esta consulta.</p>`;
  const corpo = linhas.map(p => `
    <tr>
      <td>${p.mes}</td>
      <td>${p.idadeMeses}</td>
      <td>${formatarDecimalAuditoria(p.fatorBase, 6)}</td>
      <td>${formatarPercentualAuditoria(p.taxaMesBase || 0, 4)}</td>
      <td>${formatarMoedaBR(p.base)}</td>
      <td>${formatarMoedaBR(p.otimista)}</td>
      <td>${formatarMoedaBR(p.pessimista)}</td>
      <td>${formatarMoedaBR(p.perdaBase)}</td>
      <td>${formatarPercentualAuditoria(p.depreciacaoBase, 2)}</td>
    </tr>`).join("");
  return `<div class="audit-table-wrap">
    <table class="audit-table">
      <thead>
        <tr>
          <th>Mês</th>
          <th>Idade na curva</th>
          <th>Fator base</th>
          <th>Taxa mês base</th>
          <th>Valor base</th>
          <th>Otimista</th>
          <th>Pessimista</th>
          <th>Perda base</th>
          <th>Deprec. base</th>
        </tr>
      </thead>
      <tbody>${corpo}</tbody>
    </table>
  </div>`;
}

function montarAuditoriaCalculoHTML(data) {
  const memoria = construirSeriesProjecaoCalculo(data || {});
  const info = memoria.info;
  const cen = memoria.cen;
  const taxaMensalBase = calcularTaxaMensalEquivalente(info.valorAtual, cen.base, memoria.meses);
  const taxaMensalOtimista = calcularTaxaMensalEquivalente(info.valorAtual, cen.otimista, memoria.meses);
  const taxaMensalPessimista = calcularTaxaMensalEquivalente(info.valorAtual, cen.pessimista, memoria.meses);
  const fonteTexto = memoria.fonte === "serie_mensal_backend"
    ? "Série mensal aplicada pelo backend a partir da curva salva; o gráfico é desenhado a partir destes pontos."
    : "Série mensal reconstruída por interpolação geométrica/exponencial entre o valor inicial e os valores finais dos cenários; o gráfico é desenhado a partir destes pontos.";

  return `<div class="audit-terminal-inner">
    <section class="audit-block">
      <h3>1. Dados de entrada</h3>
      <div class="audit-kv-grid">
        ${linhaAuditoriaKV("Veículo analisado", info.veiculoDescricao || "-")}
        ${linhaAuditoriaKV("Código FIPE", info.codigoFipe || "-")}
        ${linhaAuditoriaKV("Referência FIPE", info.dataBaseFipe || "-")}
        ${linhaAuditoriaKV("Valor FIPE inicial (VI)", info.valorAtual > 0 ? formatarMoedaBR(info.valorAtual) : "-")}
        ${linhaAuditoriaKV("Horizonte", `${memoria.horizonte} ano(s) / ${memoria.meses} mês(es)`)}
        ${linhaAuditoriaKV("Idade de entrada", `${Math.round(info.idadeMeses || 0)} mês(es)`)}
        ${linhaAuditoriaKV("Modelo/base da curva", info.modeloBase || "-")}
        ${linhaAuditoriaKV("Coorte ou ano-base", info.anoBase || "-")}
        ${linhaAuditoriaKV("Pontos históricos", info.pontosHistoricos > 0 ? String(info.pontosHistoricos) : "-")}
        ${linhaAuditoriaKV("Janela histórica", info.janelaHistoricaMeses > 0 ? `${info.janelaHistoricaMeses} meses` : "-")}
        ${linhaAuditoriaKV("Janela aplicada na curva", `${Math.round(info.inicioCurvaMeses || 0)} a ${Math.round(info.fimCurvaMeses || memoria.meses)} meses de idade`)}
      </div>
    </section>

    <section class="audit-block">
      <h3>2. Equações aplicadas</h3>
      <pre class="audit-code">VI = valor FIPE inicial
VF = valor futuro do cenário
M  = horizonte em meses
h  = horizonte em anos
m  = mês da projeção

Depreciação total:       D_total = 1 - (VF / VI)
Perda econômica:         P       = VI - VF
Taxa anual equivalente:  i_a     = 1 - (VF / VI)^(1 / h)
Taxa mensal equivalente: i_m     = 1 - (VF / VI)^(1 / M)
Coeficiente mensal:      q       = (VF / VI)^(1 / M)
Interpolação geométrica: V_m     = VI × q^m = VI × (1 - i_m)^m
Perda no mês m:          P_m     = VI - V_m
Depreciação no mês m:    D_m     = 1 - (V_m / VI)

Quando há curva mensal calibrada:
V_m = VI × Π[k=0 até m-1] (1 - r_k)
r_k = r_base × f_idade(I0 + k)

Cenários:
V_m(base)       = série central da curva
V_m(otimista)   = série com menor depreciação relativa
V_m(pessimista) = série com maior depreciação relativa</pre>
      <p class="audit-note">Para curvas com série mensal enviada pelo backend, os fatores mensais preservam a aplicação técnica já feita sobre a curva salva. Para séries sem vetor mensal exportado, a memória usa interpolação geométrica/exponencial para reproduzir exatamente o mesmo ponto final exibido no resultado.</p>
      <p class="audit-note"><strong>Interpolação visual:</strong> o gráfico é construído pelos pares ordenados (mês, valor estimado). A linha entre dois meses consecutivos é apenas interpolação linear visual; os valores auditáveis são os pontos mensais listados na memória de cálculo.</p>
    </section>

    <section class="audit-block">
      <h3>3. Parâmetros calculados</h3>
      <div class="audit-kv-grid">
        ${linhaAuditoriaKV("Valor futuro base", info.valorFuturo > 0 ? formatarMoedaBR(info.valorFuturo) : "-")}
        ${linhaAuditoriaKV("Valor futuro otimista", info.valorOtimista > 0 ? formatarMoedaBR(info.valorOtimista) : "-")}
        ${linhaAuditoriaKV("Valor futuro pessimista", info.valorPessimista > 0 ? formatarMoedaBR(info.valorPessimista) : "-")}
        ${linhaAuditoriaKV("Perda base no período", info.perda > 0 ? formatarMoedaBR(info.perda) : "-")}
        ${linhaAuditoriaKV("Depreciação total base", valorPercentualTexto(info.depreciacaoTotal))}
        ${linhaAuditoriaKV("Taxa anual base", valorPercentualTexto(info.taxaAnual, 4, "% a.a."))}
        ${linhaAuditoriaKV("Taxa anual de referência", info.taxaReferencia > 0 ? valorPercentualTexto(info.taxaReferencia, 4, "% a.a.") : "-")}
        ${linhaAuditoriaKV("Taxa mensal calibrada", info.taxaMensal > 0 ? `${formatarPercentualAuditoria(info.taxaMensal, 6)} a.m.` : "-")}
        ${linhaAuditoriaKV("Taxa mensal equivalente base", `${formatarPercentualAuditoria(taxaMensalBase * 100, 6)} a.m.`)}
        ${linhaAuditoriaKV("Taxa mensal otimista", `${formatarPercentualAuditoria(taxaMensalOtimista * 100, 6)} a.m.`)}
        ${linhaAuditoriaKV("Taxa mensal pessimista", `${formatarPercentualAuditoria(taxaMensalPessimista * 100, 6)} a.m.`)}
        ${linhaAuditoriaKV("Fonte da série mensal", fonteTexto)}
      </div>
    </section>

    <section class="audit-block">
      <h3>4. Construção do gráfico de projeção</h3>
      <p class="audit-note">Cada linha da memória mensal abaixo corresponde a um ponto da curva. O ponto do mês 0 é o valor FIPE inicial; o último ponto do mês ${memoria.meses} é o valor futuro apresentado no resumo e nos cenários.</p>
      ${montarTabelaMemoriaMensalHTML(memoria)}
    </section>
  </div>`;
}

function renderizarAuditoriaCalculo(data) {
  const el = document.getElementById("auditoria_calculo_texto");
  if (!el) return;
  if (!data || !data.encontrado) {
    el.textContent = "Aguardando seleção do veículo.";
    return;
  }
  el.innerHTML = montarAuditoriaCalculoHTML(data);
}

function limparAuditoriaCalculo() {
  const el = document.getElementById("auditoria_calculo_texto");
  if (el) el.textContent = "Aguardando seleção do veículo.";
  mostrarAbasDepreciacao(false);
  mostrarAuditoriaCalculoArea(false);
}

function renderizarGraficoProjecaoResultado(data) {
  const el = document.getElementById("grafico_projecao");
  if (!el) return;
  el.classList.remove("empty-chart");
  el.innerHTML = "";
  const cen = obterCenariosDoResultado(data);
  const horizonte = Math.max(1, Number(cen.horizonte || 5));
  if (!cen.atual || !cen.base || !horizonte) {
    el.classList.add("empty-chart");
    el.textContent = "Curva ainda não disponível.";
    return;
  }

  const serieBackend = serieProjecaoBackend(data);
  let meses = Math.max(1, Math.round(horizonte * 12));
  let series;
  if (serieBackend.length >= 2) {
    meses = Math.max(...serieBackend.map(p => p.mes), meses);
    series = [
      { nome: "Base", classe: "base", final: cen.base, chave: "base" },
      { nome: "Otimista", classe: "otimista", final: cen.otimista, chave: "otimista" },
      { nome: "Pessimista", classe: "pessimista", final: cen.pessimista, chave: "pessimista" }
    ].map(serie => ({
      ...serie,
      pontos: serieBackend.map(p => ({ mes: p.mes, ano: (p.mes / Math.max(1, meses)) * horizonte, valor: p[serie.chave] || 0 })).filter(p => p.valor > 0)
    }));
  } else {
    const mesesSerie = Array.from({ length: meses + 1 }, (_, i) => i);
    series = [
      { nome: "Base", taxa: cen.taxaBase, classe: "base", final: cen.base },
      { nome: "Otimista", taxa: cen.taxaOtimista, classe: "otimista", final: cen.otimista },
      { nome: "Pessimista", taxa: cen.taxaPessimista, classe: "pessimista", final: cen.pessimista }
    ].map(serie => ({
      ...serie,
      pontos: mesesSerie.map(mes => {
        const ano = (mes / meses) * horizonte;
        return { mes, ano, valor: cen.atual * Math.pow(1 - serie.taxa, ano) };
      })
    }));
  }

  // Garante que o último ponto visual bata exatamente com os valores finais exibidos no relatório do painel.
  series.forEach(serie => {
    if (serie.pontos.length && Number.isFinite(serie.final) && serie.final > 0) {
      serie.pontos[serie.pontos.length - 1].valor = serie.final;
    }
  });

  const todos = series.flatMap(s => s.pontos.map(p => p.valor)).concat([cen.atual, cen.base, cen.otimista, cen.pessimista]);
  const escala = calcularEscalaLinearPainel(todos, 5);
  const w = 900, h = 360, padL = 92, padR = 36, padT = 30, padB = 56;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const x = mes => padL + (mes / Math.max(1, meses)) * plotW;
  const y = valor => padT + ((escala.max - valor) / escala.range) * plotH;

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "line-chart-svg grid-chart-svg");

  (escala.ticks || []).forEach(valor => {
    const yy = y(valor);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", padL);
    line.setAttribute("x2", w - padR);
    line.setAttribute("y1", yy);
    line.setAttribute("y2", yy);
    line.setAttribute("class", "chart-grid-line");
    svg.appendChild(line);

    const label = document.createElementNS(svgNS, "text");
    label.setAttribute("x", padL - 12);
    label.setAttribute("y", yy + 4);
    label.setAttribute("text-anchor", "end");
    label.setAttribute("class", "chart-label-svg");
    label.textContent = formatarMoedaBR(valor).replace(",00", "");
    svg.appendChild(label);
  });

  const anosGrade = Math.min(10, Math.max(2, Math.round(horizonte)));
  for (let i = 0; i <= anosGrade; i++) {
    const mes = (i / anosGrade) * meses;
    const xx = x(mes);
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

  const rotulosX = [0, meses / 2, meses];
  rotulosX.forEach((mesRotulo, idx) => {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", x(mesRotulo));
    t.setAttribute("y", h - 20);
    t.setAttribute("text-anchor", idx === 0 ? "start" : idx === 2 ? "end" : "middle");
    t.setAttribute("class", "chart-label-svg");
    const anos = (mesRotulo / Math.max(1, meses)) * horizonte;
    t.textContent = idx === 0 ? "Hoje" : formatarHorizonteLabel(anos);
    svg.appendChild(t);
  });

  series.forEach(serie => {
    const pontosValidos = serie.pontos.filter(p => Number.isFinite(p.valor) && p.valor > 0);
    if (!pontosValidos.length) return;
    const d = pontosValidos.map((p, idx) => `${idx === 0 ? "M" : "L"}${x(p.mes).toFixed(1)} ${y(p.valor).toFixed(1)}`).join(" ");
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
    bar.className = `bar-chart-bar ${String(item.label || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")}`;
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

function normalizarCampoHorizonte() {
  const el = document.getElementById("horizonte_anos");
  if (!el) return 5;
  let n = Number(el.value || 5);
  if (!Number.isFinite(n) || n < 1) n = 1;
  if (n > 20) n = 20;
  n = Math.round(n);
  el.value = String(n);
  return n;
}

function reaplicarHorizonteAtual() {
  const el = document.getElementById("horizonte_anos");
  if (el) {
    let n = Number(el.value || 5);
    if (!Number.isFinite(n) || n < 1) n = 1;
    if (n > 20) n = 20;
    el.value = String(Math.round(n));
  }
  if (!ultimoResumoDepreciacao || !ultimoResumoDepreciacao.encontrado || !ultimoDetalheFipe) return;
  if (timerHorizonteDepreciacao) clearTimeout(timerHorizonteDepreciacao);
  mostrarResultadoArea(true);
  mostrarGraficoBarrasArea(true);
  atualizarFeedbackCalculo("Atualizando horizonte da análise...", 45, true);
  timerHorizonteDepreciacao = setTimeout(() => {
    consultarResumoDepreciacao(ultimoDetalheFipe);
  }, 300);
}

function novaConsultaDepreciacao() {
  ultimoResumoDepreciacao = null;
  ultimoJobDiagnosticoV1917 = null;
  diagnosticoV1917AutoAtivo = false;
  diagnosticoV1917Ciclos = 0;
  terminalV1917Linhas = [];
  try { ultimoDetalheFipe = null; } catch (e) {}

  const horizonte = document.getElementById("horizonte_anos");
  if (horizonte) horizonte.value = "5";

  const marca = document.getElementById("fipe_marca");
  const modelo = document.getElementById("fipe_modelo");
  const ano = document.getElementById("fipe_ano");
  if (marca) marca.value = "";
  if (modelo && typeof limparSelect === "function") limparSelect(modelo, "Selecione a marca primeiro");
  if (ano && typeof limparSelect === "function") limparSelect(ano, "Selecione o modelo primeiro");

  const rel = document.getElementById("relatorio_textual");
  if (rel) {
    rel.classList.remove("professional-report-shell");
    rel.textContent = "Aguardando seleção do veículo.";
  }
  const detalhes = document.getElementById("detalhes_corpo");
  if (detalhes) detalhes.innerHTML = "";
  const grafBarras = document.getElementById("grafico_barras");
  if (grafBarras) {
    grafBarras.classList.add("empty-chart");
    grafBarras.textContent = "Selecione um veículo com curva pronta.";
  }
  const grafProj = document.getElementById("grafico_projecao");
  if (grafProj) {
    grafProj.classList.add("empty-chart");
    grafProj.textContent = "Selecione um veículo com curva pronta.";
  }
  const grafHist = document.getElementById("grafico_historico_render");
  if (grafHist) {
    grafHist.classList.add("empty-chart");
    grafHist.textContent = "Histórico nominal não disponível para esta curva.";
  }
  const grafIpca = document.getElementById("grafico_historico_ipca_render");
  if (grafIpca) {
    grafIpca.classList.add("empty-chart");
    grafIpca.textContent = "Histórico corrigido pelo IPCA não disponível para esta curva.";
  }

  limparAuditoriaCalculo();
  resetarFluxoDepreciacao();
  atualizarStatusResultado("Aguardando seleção do veículo.", "muted");
  document.getElementById("fipe_marca")?.focus();
}

function atualizarCabecalhoPDFDepreciacao() {
  const dataEl = document.getElementById("pdf_data_emissao");
  if (dataEl) {
    dataEl.textContent = `Data de emissão: ${new Date().toLocaleString("pt-BR")}`;
  }
}

function exportarPDFDepreciacao() {
  if (!ultimoResumoDepreciacao || !ultimoResumoDepreciacao.encontrado) {
    window.alert("Selecione primeiro um veículo com curva de depreciação pronta.");
    return;
  }
  document.body.classList.remove("print-audit-mode");
  selecionarAbaPrincipalDepreciacao("resultado");
  mostrarResultadoArea(true);
  mostrarGraficoBarrasArea(true);
  mostrarAuditoriaArea(true);
  mostrarAuditoriaCalculoArea(false);
  preencherResumo(ultimoResumoDepreciacao);
  preencherRelatorio(ultimoResumoDepreciacao, "curva salva");
  renderizarGraficosDepreciacao(ultimoResumoDepreciacao);
  atualizarCabecalhoPDFDepreciacao();
  setTimeout(() => window.print(), 150);
}

function abrirAuditoriaDepreciacao() {
  if (!ultimoResumoDepreciacao || !ultimoResumoDepreciacao.encontrado) {
    window.alert("Selecione primeiro um veículo com curva de depreciação pronta.");
    return;
  }
  try {
    const chave = `aud_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    const pacote = {
      gerado_em: new Date().toISOString(),
      origem: "CurVE - depreciação veicular",
      resultado: ultimoResumoDepreciacao
    };
    localStorage.setItem(`curve_auditoria_depreciacao_${chave}`, JSON.stringify(pacote));
    window.open(`/depreciacao/auditoria?key=${encodeURIComponent(chave)}`, "_blank");
  } catch (erro) {
    console.error(erro);
    window.alert("Não consegui abrir a auditoria técnica. Tente novamente.");
  }
}

function exportarAuditoriaMatematica() {
  if (!ultimoResumoDepreciacao || !ultimoResumoDepreciacao.encontrado) {
    window.alert("Selecione primeiro um veículo com curva de depreciação pronta.");
    return;
  }
  renderizarAuditoriaCalculo(ultimoResumoDepreciacao);
  mostrarAbasDepreciacao(true);
  selecionarAbaPrincipalDepreciacao("auditoria");
  atualizarCabecalhoPDFDepreciacao();
  document.body.classList.add("print-audit-mode");
  setTimeout(() => {
    window.print();
    setTimeout(() => document.body.classList.remove("print-audit-mode"), 500);
  }, 150);
}

let timerReaplicarChecksModelosFipe = null;

function agendarReaplicarChecksModelosFipe(atraso = 0) {
  clearTimeout(timerReaplicarChecksModelosFipe);
  timerReaplicarChecksModelosFipe = setTimeout(() => {
    if (marcadoresCurvasCarregados && typeof window.aplicarChecksModelosFipe === "function") {
      window.aplicarChecksModelosFipe();
    }
  }, atraso);
}

function observarSelectModeloDepreciacaoParaChecks() {
  const select = document.getElementById("fipe_modelo");
  if (!select || select.dataset.curveChecksObserver === "1") return;
  select.dataset.curveChecksObserver = "1";
  const observer = new MutationObserver(() => agendarReaplicarChecksModelosFipe(0));
  observer.observe(select, { childList: true });
}

function aplicarChecksModelosFipe() {
  const select = document.getElementById("fipe_modelo");
  if (!select) return;
  Array.from(select.options || []).forEach(opt => {
    if (!opt.value) return;
    const nomeOriginal = String(opt.dataset.nome || opt.textContent || "").replace(/^\s*[✓✔≈]\s*/u, "").trim();
    opt.dataset.nome = nomeOriginal;
    const marcador = obterMarcadorCurva(nomeOriginal, opt.value);
    const temCurva = Boolean(marcador);
    const tipoCurva = marcador?.tipo_curva === "similaridade" ? "similaridade" : (temCurva ? "propria" : "");
    const simbolo = tipoCurva === "similaridade" ? "" : (temCurva ? "✓" : "");
    opt.dataset.curvaSalva = temCurva ? "1" : "0";
    opt.dataset.tipoCurva = tipoCurva;
    opt.dataset.modeloReferencia = marcador?.modelo_referencia || marcador?.modelo_referencia_similaridade || "";
    opt.dataset.chaveCurvaReferencia = marcador?.chave_curva_referencia || "";
    opt.textContent = `${simbolo ? `${simbolo} ` : ""}${nomeOriginal}`;
    if (temCurva && opt.dataset.temZeroKm === "1") opt.style.fontWeight = "800";
  });
  if (typeof window.atualizarComboboxesFipeCurVE === "function") window.atualizarComboboxesFipeCurVE();
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
  carregarStatusBases();
}

function fecharBaseProvisoria() {
  document.getElementById("base_provisoria_drawer")?.classList.add("hidden-drawer");
  document.getElementById("base_drawer_backdrop")?.classList.add("hidden");
}

document.addEventListener("DOMContentLoaded", () => {
  mostrarResultadoArea(false);
  mostrarGraficoBarrasArea(false);
  mostrarAuditoriaArea(false);
  mostrarAuditoriaCalculoArea(false);
  mostrarAbasDepreciacao(false);
  observarSelectModeloDepreciacaoParaChecks();
  carregarMarcadoresCurvasSalvas();
  if ("requestIdleCallback" in window) {
    requestIdleCallback(() => carregarStatusBases(), { timeout: 4500 });
  } else {
    setTimeout(() => carregarStatusBases(), 3500);
  }

  document.getElementById("tipo_veiculo")?.addEventListener("change", () => {
    if (ultimoDetalheFipe) consultarResumoDepreciacao(ultimoDetalheFipe);
  });

  document.getElementById("horizonte_anos")?.addEventListener("input", reaplicarHorizonteAtual);
  document.getElementById("horizonte_anos")?.addEventListener("change", reaplicarHorizonteAtual);

  document.getElementById("btn_auditoria")?.addEventListener("click", abrirAuditoriaDepreciacao);
  document.getElementById("tab_resultado_depreciacao")?.addEventListener("click", () => selecionarAbaPrincipalDepreciacao("resultado"));
  document.getElementById("tab_auditoria_depreciacao")?.addEventListener("click", () => selecionarAbaPrincipalDepreciacao("auditoria"));
  document.getElementById("btn_voltar_resultado")?.addEventListener("click", () => selecionarAbaPrincipalDepreciacao("resultado"));
  document.getElementById("btn_exportar_auditoria_pdf")?.addEventListener("click", exportarAuditoriaMatematica);
  document.getElementById("btn_exportar_pdf")?.addEventListener("click", exportarPDFDepreciacao);
  document.getElementById("btn_nova_consulta")?.addEventListener("click", novaConsultaDepreciacao);
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
