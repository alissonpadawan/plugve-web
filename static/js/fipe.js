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

function setStatusVarredura(texto, classe = "") {
  const el = document.getElementById("status_varredura_marca");
  if (!el) return;
  el.textContent = texto || "";
  el.className = `sweep-status ${classe}`.trim();
}

function nomeMarcaSelecionada() {
  const marca = document.getElementById("fipe_marca");
  return obterTextoSelecionado(marca);
}

function modeloProtegidoContraBloqueioAutomatico(nomeModelo) {
  const n = String(nomeModelo || "").toLowerCase();
  // Lista conservadora de modelos atuais/relevantes que não devem sumir
  // por falha temporária da API ou por variação de nome na FIPE.
  const termos = [
    "pulse", "fastback", "toro", "strada", "mobi", "argo", "cronos",
    "titano", "500e", "500 e", "renegade", "compass", "commander",
    "corolla", "hilux", "sw4", "onix", "tracker", "s10", "montana",
    "hb20", "creta", "hr-v", "city", "civic", "dolphin", "seal",
    "song", "yuan", "ora", "haval", "kwid", "captur", "kicks"
  ];
  return termos.some(t => n.includes(t));
}

function anosVieramValidosDaApi(listaAnos) {
  return Array.isArray(listaAnos) && listaAnos.length > 0 && !listaAnos.erro;
}

async function desbloquearMarcaAtual() {
  const marca = document.getElementById("fipe_marca");
  const modelo = document.getElementById("fipe_modelo");
  const ano = document.getElementById("fipe_ano");
  if (!marca || !marca.value) {
    setStatusVarredura("Selecione uma marca para restaurar os bloqueios.", "error");
    return;
  }
  const nomeMarca = obterTextoSelecionado(marca);
  const codigoMarca = marca.value;
  if (!confirm(`Restaurar bloqueios provisórios da marca ${nomeMarca}? Os modelos antigos podem reaparecer até uma nova varredura segura.`)) return;

  setStatusVarredura(`Restaurando ${nomeMarca}...`, "running");
  try {
    const resp = await fetch("/api/fipe/desbloquear_marca", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codigo_marca: codigoMarca })
    });
    const data = await resp.json();
    await carregarMarcasFipe();
    const marcaNova = document.getElementById("fipe_marca");
    if (marcaNova) marcaNova.value = codigoMarca;
    await carregarModelosFipe();
    limparSelect(ano, "Selecione o modelo primeiro");
    setStatusVarredura(`${nomeMarca} restaurada: ${data.modelos_bloqueados_removidos || 0} modelos desbloqueados. Agora faça nova varredura segura.`, "ok");
  } catch (e) {
    setStatusVarredura("Erro ao restaurar bloqueios da marca.", "error");
  }
}

window.desbloquearMarcaAtual = desbloquearMarcaAtual;

async function marcarModeloZeroKmPorCodigo(codigoMarca, codigoModelo, nomeMarca, nomeModelo, temZero) {
  try {
    await fetch(temZero ? "/api/fipe/marcar_zero_km" : "/api/fipe/desmarcar_zero_km", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        codigo_marca: codigoMarca,
        codigo_modelo: codigoModelo,
        marca: nomeMarca || "",
        modelo: nomeModelo || ""
      })
    });
  } catch (e) {}
}

async function bloquearModeloPorCodigo(codigoMarca, codigoModelo, nomeMarca, nomeModelo, anosOriginais) {
  try {
    await fetch("/api/fipe/bloquear_modelo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        codigo_marca: codigoMarca,
        codigo_modelo: codigoModelo,
        marca: nomeMarca || "",
        modelo: nomeModelo || "",
        motivo: "varredura_sem_ano_2012_ou_zero_km",
        anos_encontrados: (anosOriginais || []).map(a => a.nome || a.codigo).slice(0, 80)
      })
    });
  } catch (e) {}
}

async function marcarMarcaVarrida(codigoMarca, nomeMarca, modelosValidos, modelosBloqueados) {
  try {
    await fetch("/api/fipe/marcar_marca_varrida", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        codigo_marca: codigoMarca,
        marca: nomeMarca || "",
        modelos_validos: modelosValidos || 0,
        modelos_bloqueados: modelosBloqueados || 0
      })
    });
  } catch (e) {}
}

async function bloquearMarcaPorCodigo(codigoMarca, nomeMarca) {
  try {
    await fetch("/api/fipe/bloquear_marca", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        codigo_marca: codigoMarca,
        marca: nomeMarca || "",
        motivo: "varredura_sem_modelos_2012_ou_zero_km"
      })
    });
  } catch (e) {}
}

async function varrerMarcaAtual() {
  const marca = document.getElementById("fipe_marca");
  const modeloSelect = document.getElementById("fipe_modelo");
  const anoSelect = document.getElementById("fipe_ano");
  const botao = document.getElementById("btn_varrer_marca");

  if (!marca || !marca.value) {
    setStatusVarredura("Selecione uma marca antes de varrer.", "error");
    return;
  }

  const codigoMarca = marca.value;
  const nomeMarca = obterTextoSelecionado(marca);

  if (botao) botao.disabled = true;
  setStatusVarredura(`Varrendo ${nomeMarca}... buscando modelos.`, "running");
  limparSelect(anoSelect, "Varredura em andamento...");

  try {
    const tipo = document.getElementById("tipo_veiculo")?.value || "auto";
    const resp = await fetch(`/api/fipe/modelos?codigo_marca=${encodeURIComponent(codigoMarca)}&tipo=${encodeURIComponent(tipo)}`);
    const data = await resp.json();
    const modelos = (data.modelos || []).filter(m => m && m.codigo);

    if (!modelos.length) {
      await bloquearMarcaPorCodigo(codigoMarca, nomeMarca);
      setStatusVarredura(`${nomeMarca} ocultada: não há modelos elegíveis.`, "ok");
      await carregarMarcasFipe();
      limparSelect(modeloSelect, "Marca ocultada");
      limparSelect(anoSelect, "Selecione outra marca");
      return;
    }

    let validos = 0;
    let bloqueados = 0;
    let zeroKm = 0;

    for (let i = 0; i < modelos.length; i++) {
      const modelo = modelos[i];
      const codigoModelo = String(modelo.codigo);
      const nomeModelo = modelo.nome || "";
      setStatusVarredura(`Varrendo ${nomeMarca}: ${i + 1}/${modelos.length} - ${nomeModelo}`, "running");

      let anos = [];
      try {
        const anosResp = await fetch(`/api/fipe/anos?codigo_marca=${encodeURIComponent(codigoMarca)}&codigo_modelo=${encodeURIComponent(codigoModelo)}`);
        anos = await anosResp.json();
      } catch (e) {
        anos = [];
      }

      const listaAnos = Array.isArray(anos) ? anos : [];
      const temZero = listaAnos.some(item => codigoAnoFipeZeroKm(item.codigo));
      const elegiveis = listaAnos.filter(anoPermitidoNaTela);

      if (!elegiveis.length) {
        const podeBloquearComSeguranca = listaAnos.length > 0 && !modeloProtegidoContraBloqueioAutomatico(nomeModelo);
        if (podeBloquearComSeguranca) {
          bloqueados++;
          await bloquearModeloPorCodigo(codigoMarca, codigoModelo, nomeMarca, nomeModelo, listaAnos);
          await marcarModeloZeroKmPorCodigo(codigoMarca, codigoModelo, nomeMarca, nomeModelo, false);
        } else {
          // Não bloqueia modelo relevante/atual ou resposta vazia da API.
          // Mantém na lista para revisão manual e evita sumir com Pulse, Strada, Toro etc.
          validos++;
        }
      } else {
        validos++;
        if (temZero) {
          zeroKm++;
          await marcarModeloZeroKmPorCodigo(codigoMarca, codigoModelo, nomeMarca, nomeModelo, true);
        } else {
          await marcarModeloZeroKmPorCodigo(codigoMarca, codigoModelo, nomeMarca, nomeModelo, false);
        }
      }

      // Respira para a tela atualizar e não parecer travada.
      await new Promise(resolve => setTimeout(resolve, 25));
    }

    if (validos <= 0) {
      await bloquearMarcaPorCodigo(codigoMarca, nomeMarca);
      setStatusVarredura(`${nomeMarca} ocultada: 100% dos modelos são antigos/sem Zero km.`, "ok");
      await carregarMarcasFipe();
      limparSelect(modeloSelect, "Marca ocultada");
      limparSelect(anoSelect, "Selecione outra marca");
      return;
    }

    await marcarMarcaVarrida(codigoMarca, nomeMarca, validos, bloqueados);
    setStatusVarredura(`${nomeMarca} varrida: ${validos} modelos válidos, ${bloqueados} bloqueados, ${zeroKm} com Zero km.`, "ok");
    await carregarMarcasFipe();
    const marcaNova = document.getElementById("fipe_marca");
    if (marcaNova) marcaNova.value = codigoMarca;
    await carregarModelosFipe();
  } catch (e) {
    setStatusVarredura("Erro durante a varredura da marca. Tente novamente.", "error");
  } finally {
    if (botao) botao.disabled = false;
  }
}

window.varrerMarcaAtual = varrerMarcaAtual;

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

  if (!Array.isArray(anosOriginais) || !anosOriginais.length || modeloProtegidoContraBloqueioAutomatico(nomeModelo)) {
    const ano = document.getElementById("fipe_ano");
    limparSelect(ano, "Sem ano elegível; mantido para revisão");
    if (typeof atualizarStatusResultado === "function") {
      atualizarStatusResultado(`Modelo mantido para revisão: não foi bloqueado automaticamente por segurança.`, "muted");
      mostrarResultadoArea(true);
    }
    return;
  }

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
      opt.dataset.varrida = item.marca_varrida ? "1" : "0";
      opt.className = item.marca_varrida ? "marca-varrida" : "marca-pendente-varredura";
      opt.title = item.marca_varrida ? "Marca já varrida" : "Marca ainda não varrida: aparece em vermelho provisoriamente";
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

  document.getElementById("btn_varrer_marca")?.addEventListener("click", varrerMarcaAtual);
  document.getElementById("btn_restaurar_marca")?.addEventListener("click", desbloquearMarcaAtual);

  document.getElementById("fipe_marca")?.addEventListener("change", () => {
    setStatusVarredura("");
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
