let ultimoDetalheFipe = null;

function limparSelect(select, texto) {
  select.innerHTML = "";
  const opt = document.createElement("option");
  opt.value = "";
  opt.textContent = texto || "Selecione";
  select.appendChild(opt);
}

function formatarMoedaBR(valor) {
  const numero = Number(valor || 0);
  return numero.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}


function codigoAnoFipeZeroKm(codigoAno) {
  return String(codigoAno || "").startsWith("32000");
}

function textoAnoFipeParaTela(codigoAno, textoOriginal) {
  if (codigoAnoFipeZeroKm(codigoAno)) {
    const partes = String(textoOriginal || "").replace(/^32000\s*/i, "").replace(/^0\s*km\s*/i, "").trim();
    return `Zero km ${partes}`.trim();
  }
  return textoOriginal || "";
}


function anoNumeroFipe(codigoAno, nomeAno) {
  const bruto = String(codigoAno || nomeAno || "");
  const m = bruto.match(/(19|20)\d{2}/);
  return m ? Number(m[0]) : null;
}

function anoPermitidoNaTela(item) {
  // Regra metodológica do PlugVE: a interface só trabalha com Zero km ou ano/modelo >= 2012.
  // Isso evita poluir a análise com veículos obsoletos e versões sem relevância comparativa atual.
  if (codigoAnoFipeZeroKm(item.codigo)) return true;
  const ano = anoNumeroFipe(item.codigo, item.nome);
  return ano !== null && ano >= 2012;
}

function obterTextoSelecionado(select) {
  if (!select || select.selectedIndex < 0) return "";
  return select.options[select.selectedIndex]?.dataset?.nome || select.options[select.selectedIndex]?.textContent || "";
}

async function salvarModeloZeroKmSeEncontrado(marca, modelo, anosOriginais) {
  if (!marca?.value || !modelo?.value || !Array.isArray(anosOriginais)) return false;
  const temZero = anosOriginais.some(item => codigoAnoFipeZeroKm(item.codigo));
  const nomeModelo = obterTextoSelecionado(modelo);
  const nomeMarca = obterTextoSelecionado(marca);
  const opt = modelo.options[modelo.selectedIndex];

  if (!temZero) {
    // Se a FIPE retornou anos e nenhum é 32000, o modelo não deve mais ficar destacado.
    // Isso corrige marcações antigas salvas por engano no cache permanente.
    if (opt) limparDestaqueModeloZeroKm(opt);
    try {
      await fetch("/api/fipe/desmarcar_zero_km", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          codigo_marca: marca.value,
          codigo_modelo: modelo.value
        })
      });
    } catch (e) {}
    return false;
  }

  if (opt) destacarOpcaoModeloZeroKm(opt);

  try {
    await fetch("/api/fipe/marcar_zero_km", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        codigo_marca: marca.value,
        codigo_modelo: modelo.value,
        marca: nomeMarca,
        modelo: nomeModelo
      })
    });
  } catch (e) {
    // O destaque visual continua mesmo se o salvamento falhar.
  }
  return true;
}

function limparDestaqueModeloZeroKm(opt) {
  if (!opt) return;
  opt.dataset.temZeroKm = "0";
  opt.style.fontWeight = "";
  opt.title = "";
  const nomeOriginal = opt.dataset.nome || (opt.textContent || "").replace(/^0 km\s*•\s*/i, "");
  opt.textContent = nomeOriginal;
}

function destacarOpcaoModeloZeroKm(opt) {
  if (!opt || !opt.value) return;
  opt.dataset.temZeroKm = "1";
  opt.style.fontWeight = "800";
  opt.title = "Este modelo possui versão Zero km na FIPE";
  const nomeOriginal = opt.dataset.nome || (opt.textContent || "").replace(/^0 km\s*•\s*/i, "");
  opt.textContent = nomeOriginal;
}

async function bloquearModeloAntigoSemAnoValido(marca, modelo, anosOriginais) {
  if (!marca?.value || !modelo?.value) return;
  const nomeModelo = obterTextoSelecionado(modelo);
  const nomeMarca = obterTextoSelecionado(marca);
  const indiceBloqueado = modelo.selectedIndex;

  try {
    const resp = await fetch("/api/fipe/bloquear_modelo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        codigo_marca: marca.value,
        codigo_modelo: modelo.value,
        marca: nomeMarca,
        modelo: nomeModelo,
        motivo: "sem_ano_2012_ou_zero_km",
        anos_encontrados: (anosOriginais || []).map(a => a.nome || a.codigo).slice(0, 80)
      })
    });
    const retorno = await resp.json().catch(() => ({}));
    if (retorno.marca_bloqueada) {
      await carregarMarcasFipe();
      limparSelect(modelo, "Marca ocultada: sem modelos elegíveis");
      limparSelect(document.getElementById("fipe_ano"), "Selecione outra marca");
      if (typeof atualizarStatusResultado === "function") {
        atualizarStatusResultado(`Marca ${nomeMarca} ocultada: nenhum modelo possui Zero km ou ano/modelo de 2012 em diante.`, "erro");
        mostrarResultadoArea(true);
      }
      return;
    }
  } catch (e) {
    // Se não conseguir salvar o bloqueio, a tela ainda continua funcionando.
  }

  const opt = modelo.options[indiceBloqueado];
  if (opt) opt.remove();

  ultimoDetalheFipe = null;
  if (typeof window.resetarFluxoDepreciacao === "function") window.resetarFluxoDepreciacao();

  const ano = document.getElementById("fipe_ano");
  const proximoIndice = Math.min(Math.max(indiceBloqueado, 1), modelo.options.length - 1);

  if (modelo.options.length > 1 && proximoIndice >= 1) {
    modelo.selectedIndex = proximoIndice;
    limparSelect(ano, "Verificando próximo modelo...");
    if (typeof atualizarStatusResultado === "function") {
      atualizarStatusResultado(`Modelo ocultado. Avançando automaticamente para o próximo modelo da lista.`, "muted");
      mostrarResultadoArea(true);
    }
    // Pequeno intervalo para a interface mostrar a mudança antes da próxima consulta.
    await new Promise(resolve => setTimeout(resolve, 120));
    await carregarAnosFipe();
    modelo.focus();
    return;
  }

  modelo.value = "";
  limparSelect(ano, "Nenhum modelo elegível restante");
  if (typeof atualizarStatusResultado === "function") {
    atualizarStatusResultado(`Modelo ocultado. Não há outro modelo elegível nesta marca.`, "erro");
    mostrarResultadoArea(true);
  }
}

function limparValorMonetario(valorBruto) {
  if (!valorBruto) return 0;
  let s = String(valorBruto).replace("R$", "").trim();
  s = s.replace(/\./g, "").replace(",", ".");
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}

async function carregarMarcasFipe() {
  const marca = document.getElementById("fipe_marca");
  const modelo = document.getElementById("fipe_modelo");
  const ano = document.getElementById("fipe_ano");

  limparSelect(marca, "Carregando...");
  limparSelect(modelo, "Selecione a marca primeiro");
  limparSelect(ano, "Selecione o modelo primeiro");

  try {
    const resp = await fetch("/api/fipe/marcas");
    const marcas = await resp.json();
    limparSelect(marca, "Selecione");
    marcas.forEach(item => {
      const opt = document.createElement("option");
      opt.value = item.codigo;
      opt.textContent = item.nome;
      opt.dataset.nome = item.nome;
      marca.appendChild(opt);
    });
  } catch (e) {
    limparSelect(marca, "Erro ao carregar marcas");
  }
}

async function carregarModelosFipe() {
  const marca = document.getElementById("fipe_marca");
  const modelo = document.getElementById("fipe_modelo");
  const ano = document.getElementById("fipe_ano");
  limparSelect(modelo, "Carregando...");
  limparSelect(ano, "Selecione o modelo primeiro");

  if (!marca.value) {
    limparSelect(modelo, "Selecione a marca primeiro");
    return;
  }

  try {
    const tipo = document.getElementById("tipo_veiculo")?.value || "auto";
    const resp = await fetch(`/api/fipe/modelos?codigo_marca=${encodeURIComponent(marca.value)}&tipo=${encodeURIComponent(tipo)}`);
    const data = await resp.json();
    if (data.marca_bloqueada) {
      await carregarMarcasFipe();
      limparSelect(modelo, "Marca ocultada: sem modelos elegíveis");
      limparSelect(ano, "Selecione outra marca");
      if (typeof atualizarStatusResultado === "function") {
        atualizarStatusResultado("Marca ocultada: nenhum modelo possui Zero km ou ano/modelo de 2012 em diante.", "erro");
        mostrarResultadoArea(true);
      }
      return;
    }
    limparSelect(modelo, "Selecione");
    (data.modelos || []).forEach(item => {
      const opt = document.createElement("option");
      opt.value = item.codigo;
      opt.textContent = item.nome;
      opt.dataset.nome = item.nome;
      if (item.tem_zero_km) {
        destacarOpcaoModeloZeroKm(opt);
      }
      modelo.appendChild(opt);
    });
    if (!(data.modelos || []).length) {
      limparSelect(modelo, "Nenhum modelo elegível nesta marca");
    }
    ultimoIndiceModeloNavegacao = -1;
    if (typeof window.aplicarChecksModelosFipe === "function") {
      window.aplicarChecksModelosFipe();
    }
  } catch (e) {
    limparSelect(modelo, "Erro ao carregar modelos");
  }
}

async function carregarAnosFipe() {
  const marca = document.getElementById("fipe_marca");
  const modelo = document.getElementById("fipe_modelo");
  const ano = document.getElementById("fipe_ano");
  limparSelect(ano, "Carregando...");

  if (!marca.value || !modelo.value) {
    limparSelect(ano, "Selecione o modelo primeiro");
    return;
  }

  try {
    const url = `/api/fipe/anos?codigo_marca=${encodeURIComponent(marca.value)}&codigo_modelo=${encodeURIComponent(modelo.value)}`;
    const resp = await fetch(url);
    const anos = await resp.json();
    const anosElegiveis = Array.isArray(anos) ? anos.filter(anoPermitidoNaTela) : [];
    await salvarModeloZeroKmSeEncontrado(marca, modelo, Array.isArray(anos) ? anos : []);
    limparSelect(ano, anosElegiveis.length ? "Selecione" : "Sem anos elegíveis");

    if (!anosElegiveis.length) {
      await bloquearModeloAntigoSemAnoValido(marca, modelo, Array.isArray(anos) ? anos : []);
      return;
    }

    anosElegiveis.forEach(item => {
      const opt = document.createElement("option");
      opt.value = item.codigo;
      opt.textContent = textoAnoFipeParaTela(item.codigo, item.nome);
      opt.dataset.nome = item.nome;
      ano.appendChild(opt);
    });
  } catch (e) {
    limparSelect(ano, "Erro ao carregar anos");
  }
}

async function consultarPrecoFipe() {
  const marca = document.getElementById("fipe_marca");
  const modelo = document.getElementById("fipe_modelo");
  const ano = document.getElementById("fipe_ano");
  if (!marca.value || !modelo.value || !ano.value) return;

  try {
    const url = `/api/fipe/preco?codigo_marca=${encodeURIComponent(marca.value)}&codigo_modelo=${encodeURIComponent(modelo.value)}&codigo_ano=${encodeURIComponent(ano.value)}`;
    const resp = await fetch(url);
    const data = await resp.json();

    ultimoDetalheFipe = {
      codigo_marca: marca.value,
      codigo_modelo: modelo.value,
      codigo_ano: ano.value,
      marca: data.Marca || marca.options[marca.selectedIndex].text,
      modelo: data.Modelo || modelo.options[modelo.selectedIndex].text,
      ano_modelo: codigoAnoFipeZeroKm(ano.value) ? "Zero km" : (data.AnoModelo || ""),
      combustivel: data.Combustivel || ano.options[ano.selectedIndex].text,
      codigo_fipe: data.CodigoFipe || "",
      valor_atual: limparValorMonetario(data.Valor),
      valor_texto: data.Valor || ""
    };

    atualizarCardVeiculo(ultimoDetalheFipe);
    await consultarResumoDepreciacao(ultimoDetalheFipe);
  } catch (e) {
    ultimoDetalheFipe = null;
    atualizarStatusResultado("Erro ao consultar preço FIPE.", "erro");
  }
}

function setTextoSeExistir(id, valor) {
  const el = document.getElementById(id);
  if (el) el.textContent = valor;
}

function atualizarCardVeiculo(detalhe) {
  setTextoSeExistir("info_marca", detalhe.marca || "-");
  setTextoSeExistir("info_modelo", detalhe.modelo || "-");
  setTextoSeExistir("info_ano", detalhe.ano_modelo || "-");
  setTextoSeExistir("info_combustivel", detalhe.combustivel || "-");
  setTextoSeExistir("info_codigo_fipe", detalhe.codigo_fipe || "-");
  setTextoSeExistir("info_valor", detalhe.valor_texto || formatarMoedaBR(detalhe.valor_atual));
}


let timerNavegacaoModelo = null;
let ultimoIndiceModeloNavegacao = -1;

function agendarConsultaModeloSelecionado() {
  const modelo = document.getElementById("fipe_modelo");
  if (!modelo || !modelo.value) return;
  const indiceAtual = modelo.selectedIndex;
  if (indiceAtual === ultimoIndiceModeloNavegacao) return;
  ultimoIndiceModeloNavegacao = indiceAtual;
  clearTimeout(timerNavegacaoModelo);
  timerNavegacaoModelo = setTimeout(() => {
    ultimoDetalheFipe = null;
    if (typeof window.resetarFluxoDepreciacao === "function") window.resetarFluxoDepreciacao();
    carregarAnosFipe();
  }, 180);
}

function habilitarNavegacaoPorSetasNoModelo() {
  const modelo = document.getElementById("fipe_modelo");
  if (!modelo) return;

  modelo.addEventListener("keydown", (ev) => {
    if (!["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End"].includes(ev.key)) return;
    setTimeout(agendarConsultaModeloSelecionado, 0);
  });

  modelo.addEventListener("keyup", (ev) => {
    if (!["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End"].includes(ev.key)) return;
    agendarConsultaModeloSelecionado();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  carregarMarcasFipe();

  document.getElementById("fipe_marca")?.addEventListener("change", () => {
    ultimoDetalheFipe = null;
    if (typeof window.resetarFluxoDepreciacao === "function") window.resetarFluxoDepreciacao();
    carregarModelosFipe();
  });
  habilitarNavegacaoPorSetasNoModelo();

  document.getElementById("fipe_modelo")?.addEventListener("change", () => {
    const modelo = document.getElementById("fipe_modelo");
    ultimoIndiceModeloNavegacao = modelo ? modelo.selectedIndex : -1;
    ultimoDetalheFipe = null;
    if (typeof window.resetarFluxoDepreciacao === "function") window.resetarFluxoDepreciacao();
    carregarAnosFipe();
  });
  document.getElementById("fipe_ano")?.addEventListener("change", consultarPrecoFipe);
});
