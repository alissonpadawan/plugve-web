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
    await carregarUsoFipe();
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

async function carregarUsoFipe() {
  try {
    const resp = await fetch("/api/fipe/usage");
    const data = await resp.json();
    const box = document.getElementById("fipe_usage_box");
    if (!box) return data;
    const usado = Number(data.count || 0);
    const limite = Number(data.limit || 500);
    const restante = Math.max(0, limite - usado);
    const token = data.token_ativo ? "token ativo" : "sem token";
    box.innerHTML = `<strong>FIPE</strong><br>${usado}/${limite} requisições nas últimas 24h<br>Restantes: ${restante} • ${token}`;
    return data;
  } catch (e) {
    return null;
  }
}
window.carregarUsoFipe = carregarUsoFipe;

function erroFipeEhLimite(data, resp) {
  return resp?.status === 429 || data?.fipe_limitada || data?.tipo === "limite_requisicoes";
}

function mostrarErroFipe(data, esconderBusca = true) {
  const box = document.getElementById("fipe_error_box");
  const area = document.getElementById("fipe_search_area");
  const msg = data?.erro || "Erro ao consultar a FIPE.";
  if (box) {
    box.classList.remove("hidden");
    box.innerHTML = `${msg}<br><button class="button secondary" type="button" onclick="tentarReativarFipe()">Tentar novamente</button>`;
  }
  if (area && esconderBusca) area.classList.add("hidden");
}

function limparErroFipe() {
  document.getElementById("fipe_error_box")?.classList.add("hidden");
  document.getElementById("fipe_search_area")?.classList.remove("hidden");
}

async function tentarReativarFipe() {
  limparErroFipe();
  await carregarUsoFipe();
  await carregarMarcasFipe();
}
window.tentarReativarFipe = tentarReativarFipe;

async function obterStatusVarredura(codigoMarca) {
  if (!codigoMarca) return {};
  try {
    const resp = await fetch(`/api/fipe/varredura_status?codigo_marca=${encodeURIComponent(codigoMarca)}`);
    return await resp.json();
  } catch (e) {
    return {};
  }
}

async function salvarProgressoVarredura(payload) {
  try {
    await fetch("/api/fipe/salvar_varredura", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  } catch (e) {}
}

async function limparProgressoVarredura(codigoMarca) {
  try {
    await fetch("/api/fipe/limpar_varredura", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codigo_marca: codigoMarca })
    });
  } catch (e) {}
}

async function atualizarBotaoContinuarVarredura() {
  const marca = document.getElementById("fipe_marca");
  const btn = document.getElementById("btn_continuar_varredura");
  if (!btn || !marca?.value) {
    btn?.classList.add("hidden");
    return;
  }
  const st = await obterStatusVarredura(marca.value);
  if (st && st.status && st.status !== "concluida" && Number(st.proximo_indice || 0) > 0) {
    btn.classList.remove("hidden");
    btn.textContent = `Continuar varredura (${Number(st.proximo_indice || 0)}/${Number(st.total || 0)})`;
  } else {
    btn.classList.add("hidden");
  }
}
window.atualizarBotaoContinuarVarredura = atualizarBotaoContinuarVarredura;

async function buscarJsonFipeSeguro(url) {
  const resp = await fetch(url);
  const data = await resp.json().catch(() => ({}));
  await carregarUsoFipe();
  if (!resp.ok || data?.erro) {
    const err = new Error(data?.erro || `Erro FIPE ${resp.status}`);
    err.data = data;
    err.status = resp.status;
    throw err;
  }
  return { data, resp };
}

async function varrerMarcaAtual(opcoes = {}) {
  const marca = document.getElementById("fipe_marca");
  const modeloSelect = document.getElementById("fipe_modelo");
  const anoSelect = document.getElementById("fipe_ano");
  const botao = document.getElementById("btn_varrer_marca");
  const botaoContinuar = document.getElementById("btn_continuar_varredura");

  if (!marca || !marca.value) {
    setStatusVarredura("Selecione uma marca antes de varrer.", "error");
    return;
  }

  limparErroFipe();
  const codigoMarca = marca.value;
  const nomeMarca = obterTextoSelecionado(marca);

  if (botao) botao.disabled = true;
  if (botaoContinuar) botaoContinuar.disabled = true;
  setStatusVarredura(`Varrendo ${nomeMarca}... buscando modelos.`, "running");
  limparSelect(anoSelect, "Varredura em andamento...");

  try {
    const tipo = document.getElementById("tipo_veiculo")?.value || "auto";
    const { data } = await buscarJsonFipeSeguro(`/api/fipe/modelos?codigo_marca=${encodeURIComponent(codigoMarca)}&tipo=${encodeURIComponent(tipo)}`);
    const modelos = (data.modelos || []).filter(m => m && m.codigo);

    if (!modelos.length) {
      await bloquearMarcaPorCodigo(codigoMarca, nomeMarca);
      setStatusVarredura(`${nomeMarca} ocultada: não há modelos elegíveis.`, "ok");
      await carregarMarcasFipe();
      limparSelect(modeloSelect, "Marca ocultada");
      limparSelect(anoSelect, "Selecione outra marca");
      return;
    }

    const progressoAnterior = opcoes.continuar ? await obterStatusVarredura(codigoMarca) : {};
    let inicio = opcoes.continuar ? Number(progressoAnterior.proximo_indice || 0) : 0;
    inicio = Math.max(0, Math.min(inicio, modelos.length - 1));

    let validos = Number(progressoAnterior.modelos_validos || 0);
    let bloqueados = Number(progressoAnterior.modelos_bloqueados || 0);
    let zeroKm = Number(progressoAnterior.modelos_zero_km || 0);
    if (!opcoes.continuar) {
      validos = 0; bloqueados = 0; zeroKm = 0;
    }

    for (let i = inicio; i < modelos.length; i++) {
      const modelo = modelos[i];
      const codigoModelo = String(modelo.codigo);
      const nomeModelo = modelo.nome || "";
      setStatusVarredura(`Varrendo ${nomeMarca}: ${i + 1}/${modelos.length} - ${nomeModelo}`, "running");

      let listaAnos = [];
      try {
        const { data: anos } = await buscarJsonFipeSeguro(`/api/fipe/anos?codigo_marca=${encodeURIComponent(codigoMarca)}&codigo_modelo=${encodeURIComponent(codigoModelo)}`);
        listaAnos = Array.isArray(anos) ? anos : [];
      } catch (err) {
        await salvarProgressoVarredura({
          codigo_marca: codigoMarca,
          marca: nomeMarca,
          status: erroFipeEhLimite(err.data, { status: err.status }) ? "pausada_limite" : "pausada_erro",
          erro: err.message,
          proximo_indice: i,
          total: modelos.length,
          modelos_validos: validos,
          modelos_bloqueados: bloqueados,
          modelos_zero_km: zeroKm,
          ultimo_modelo: nomeModelo,
        });
        setStatusVarredura(`Varredura pausada em ${i + 1}/${modelos.length}: ${err.message}. Amanhã continue do mesmo ponto.`, "error");
        if (erroFipeEhLimite(err.data, { status: err.status })) mostrarErroFipe(err.data || { erro: err.message }, false);
        await atualizarBotaoContinuarVarredura();
        return;
      }

      const temZero = listaAnos.some(item => codigoAnoFipeZeroKm(item.codigo));
      const elegiveis = listaAnos.filter(anoPermitidoNaTela);

      if (!elegiveis.length) {
        const podeBloquearComSeguranca = listaAnos.length > 0 && !modeloProtegidoContraBloqueioAutomatico(nomeModelo);
        if (podeBloquearComSeguranca) {
          bloqueados++;
          await bloquearModeloPorCodigo(codigoMarca, codigoModelo, nomeMarca, nomeModelo, listaAnos);
          await marcarModeloZeroKmPorCodigo(codigoMarca, codigoModelo, nomeMarca, nomeModelo, false);
        } else {
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

      await salvarProgressoVarredura({
        codigo_marca: codigoMarca,
        marca: nomeMarca,
        status: "em_andamento",
        proximo_indice: i + 1,
        total: modelos.length,
        modelos_validos: validos,
        modelos_bloqueados: bloqueados,
        modelos_zero_km: zeroKm,
        ultimo_modelo: nomeModelo,
      });

      await new Promise(resolve => setTimeout(resolve, 120));
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
    await limparProgressoVarredura(codigoMarca);
    setStatusVarredura(`${nomeMarca} varrida: ${validos} modelos válidos, ${bloqueados} bloqueados, ${zeroKm} com Zero km.`, "ok");
    await carregarMarcasFipe();
    const marcaNova = document.getElementById("fipe_marca");
    if (marcaNova) marcaNova.value = codigoMarca;
    await carregarModelosFipe();
    await atualizarBotaoContinuarVarredura();
  } catch (err) {
    setStatusVarredura(`Erro durante a varredura: ${err.message || "tente novamente"}.`, "error");
    if (erroFipeEhLimite(err.data, { status: err.status })) mostrarErroFipe(err.data || { erro: err.message }, false);
  } finally {
    if (botao) botao.disabled = false;
    if (botaoContinuar) botaoContinuar.disabled = false;
    await carregarUsoFipe();
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
    const { data: marcas } = await buscarJsonFipeSeguro("/api/fipe/marcas");
    limparErroFipe();
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
    await carregarUsoFipe();
  } catch (err) {
    limparSelect(marca, "FIPE temporariamente indisponível");
    mostrarErroFipe(err.data || { erro: err.message || "Erro ao carregar marcas FIPE." }, true);
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
    const { data } = await buscarJsonFipeSeguro(`/api/fipe/modelos?codigo_marca=${encodeURIComponent(marca.value)}&tipo=${encodeURIComponent(tipo)}`);
    limparErroFipe();
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
    await atualizarBotaoContinuarVarredura();
  } catch (err) {
    limparSelect(modelo, "FIPE temporariamente indisponível");
    mostrarErroFipe(err.data || { erro: err.message || "Erro ao carregar modelos FIPE." }, true);
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
    const { data: anos } = await buscarJsonFipeSeguro(url);
    limparErroFipe();
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
  } catch (err) {
    limparSelect(ano, "FIPE temporariamente indisponível");
    if (erroFipeEhLimite(err.data, { status: err.status })) {
      mostrarErroFipe(err.data || { erro: err.message }, true);
    } else {
      atualizarStatusResultado?.(err.message || "Erro ao carregar anos FIPE.", "erro");
    }
  }
}
async function consultarPrecoFipe() {
  const marca = document.getElementById("fipe_marca");
  const modelo = document.getElementById("fipe_modelo");
  const ano = document.getElementById("fipe_ano");
  if (!marca.value || !modelo.value || !ano.value) return;

  try {
    const url = `/api/fipe/preco?codigo_marca=${encodeURIComponent(marca.value)}&codigo_modelo=${encodeURIComponent(modelo.value)}&codigo_ano=${encodeURIComponent(ano.value)}`;
    const { data } = await buscarJsonFipeSeguro(url);
    limparErroFipe();

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
    if (erroFipeEhLimite(e.data, { status: e.status })) {
      mostrarErroFipe(e.data || { erro: e.message }, true);
    } else {
      atualizarStatusResultado(e.message || "Erro ao consultar preço FIPE.", "erro");
    }
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

  document.getElementById("btn_varrer_marca")?.addEventListener("click", () => varrerMarcaAtual({ continuar: false }));
  document.getElementById("btn_continuar_varredura")?.addEventListener("click", () => varrerMarcaAtual({ continuar: true }));
  document.getElementById("btn_restaurar_marca")?.addEventListener("click", desbloquearMarcaAtual);

  document.getElementById("fipe_marca")?.addEventListener("change", () => {
    setStatusVarredura("");
    ultimoDetalheFipe = null;
    if (typeof window.resetarFluxoDepreciacao === "function") window.resetarFluxoDepreciacao();
    carregarModelosFipe();
    atualizarBotaoContinuarVarredura();
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
