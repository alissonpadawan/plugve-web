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
    const resp = await fetch(`/api/fipe/modelos?codigo_marca=${encodeURIComponent(marca.value)}`);
    const data = await resp.json();
    limparSelect(modelo, "Selecione");
    (data.modelos || []).forEach(item => {
      const opt = document.createElement("option");
      opt.value = item.codigo;
      opt.textContent = item.nome;
      opt.dataset.nome = item.nome;
      modelo.appendChild(opt);
    });
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
    limparSelect(ano, "Selecione");
    anos.forEach(item => {
      const opt = document.createElement("option");
      opt.value = item.codigo;
      opt.textContent = item.nome;
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
      ano_modelo: data.AnoModelo || "",
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

function atualizarCardVeiculo(detalhe) {
  document.getElementById("info_marca").textContent = detalhe.marca || "-";
  document.getElementById("info_modelo").textContent = detalhe.modelo || "-";
  document.getElementById("info_ano").textContent = detalhe.ano_modelo || "-";
  document.getElementById("info_combustivel").textContent = detalhe.combustivel || "-";
  document.getElementById("info_codigo_fipe").textContent = detalhe.codigo_fipe || "-";
  document.getElementById("info_valor").textContent = detalhe.valor_texto || formatarMoedaBR(detalhe.valor_atual);
}

document.addEventListener("DOMContentLoaded", () => {
  carregarMarcasFipe();

  document.getElementById("fipe_marca")?.addEventListener("change", carregarModelosFipe);
  document.getElementById("fipe_modelo")?.addEventListener("change", carregarAnosFipe);
  document.getElementById("fipe_ano")?.addEventListener("change", consultarPrecoFipe);
});
