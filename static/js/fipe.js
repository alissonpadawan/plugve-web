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

async function bloquearModeloAntigoSemAnoValido(marca, modelo, anosOriginais) {
  if (!marca?.value || !modelo?.value) return;
  const nomeModelo = obterTextoSelecionado(modelo);
  const nomeMarca = obterTextoSelecionado(marca);
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

  const opt = modelo.options[modelo.selectedIndex];
  if (opt) opt.remove();
  modelo.value = "";
  limparSelect(document.getElementById("fipe_ano"), "Selecione outro modelo");
  ultimoDetalheFipe = null;
  if (typeof window.resetarFluxoDepreciacao === "function") window.resetarFluxoDepreciacao();
  if (typeof atualizarStatusResultado === "function") {
    atualizarStatusResultado(`Modelo ocultado: não possui versão Zero km nem ano/modelo de 2012 em diante.`, "erro");
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
      modelo.appendChild(opt);
    });
    if (!(data.modelos || []).length) {
      limparSelect(modelo, "Nenhum modelo elegível nesta marca");
    }
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

document.addEventListener("DOMContentLoaded", () => {
  carregarMarcasFipe();

  document.getElementById("fipe_marca")?.addEventListener("change", () => {
    ultimoDetalheFipe = null;
    if (typeof window.resetarFluxoDepreciacao === "function") window.resetarFluxoDepreciacao();
    carregarModelosFipe();
  });
  document.getElementById("fipe_modelo")?.addEventListener("change", () => {
    ultimoDetalheFipe = null;
    if (typeof window.resetarFluxoDepreciacao === "function") window.resetarFluxoDepreciacao();
    carregarAnosFipe();
  });
  document.getElementById("fipe_ano")?.addEventListener("change", consultarPrecoFipe);
});
