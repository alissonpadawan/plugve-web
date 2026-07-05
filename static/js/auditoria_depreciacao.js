(function() {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function esc(v) {
    return String(v ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  function num(v) {
    if (v === null || v === undefined || v === "") return 0;
    if (typeof v === "number") return Number.isFinite(v) ? v : 0;
    let txt = String(v).replace(/R\$|\s/g, "").replace(/[^0-9,.-]/g, "");
    if (!txt) return 0;
    const c = txt.lastIndexOf(",");
    const p = txt.lastIndexOf(".");
    if (c >= 0 && p >= 0) txt = c > p ? txt.replace(/\./g, "").replace(",", ".") : txt.replace(/,/g, "");
    else if (c >= 0) txt = txt.replace(",", ".");
    const n = Number(txt);
    return Number.isFinite(n) ? n : 0;
  }
  function firstNum() {
    for (const v of arguments) {
      const n = num(v);
      if (n > 0) return n;
    }
    return 0;
  }
  function firstText() {
    for (const v of arguments) {
      if (v === null || v === undefined) continue;
      const s = String(v).trim();
      if (s && s !== "-" && s.toLowerCase() !== "undefined" && s.toLowerCase() !== "null" && s.toLowerCase() !== "nan") return s;
    }
    return "";
  }
  function money(v) { return num(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }); }
  function pct(v, casas) {
    const n = num(v);
    if (!Number.isFinite(n)) return "-";
    return `${n.toFixed(casas ?? 2).replace(".", ",")}%`;
  }
  function dec(v, casas) {
    const n = num(v);
    if (!Number.isFinite(n)) return "-";
    return n.toFixed(casas ?? 6).replace(".", ",");
  }
  function readPath(obj, path) {
    return path.split(".").reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : undefined), obj);
  }
  function firstPath(obj, paths, numeric) {
    for (const path of paths) {
      const v = readPath(obj, path);
      if (numeric) {
        const n = num(v);
        if (n > 0) return n;
      } else {
        const s = firstText(v);
        if (s) return s;
      }
    }
    return numeric ? 0 : "";
  }
  function formatYears(anos) {
    const n = Math.max(1, num(anos) || 5);
    return `${Number.isInteger(n) ? n : n.toFixed(1).replace(".", ",")} ${Math.abs(n - 1) < 0.01 ? "ano" : "anos"}`;
  }
  function cleanYear(v) {
    const m = String(v || "").match(/(?:19|20)\d{2}/);
    return m ? m[0] : "";
  }
  function getFinalProjection(data) {
    const serie = Array.isArray(data?.projecao_mensal) ? data.projecao_mensal : (Array.isArray(data?.detalhes?.projecao_mensal) ? data.detalhes.projecao_mensal : []);
    if (!serie.length) return {};
    const last = serie[serie.length - 1] || {};
    return {
      base: firstNum(last.valor_base, last.base, last.valor),
      otimista: firstNum(last.valor_otimista, last.otimista),
      pessimista: firstNum(last.valor_pessimista, last.pessimista)
    };
  }
  function taxaAnual(vi, vf, h) {
    vi = num(vi); vf = num(vf); h = Math.max(1, num(h) || 1);
    if (!(vi > 0) || !(vf > 0)) return 0;
    const t = 1 - Math.pow(vf / vi, 1 / h);
    return Number.isFinite(t) ? Math.max(0, t) : 0;
  }
  function taxaMensal(vi, vf, m) {
    vi = num(vi); vf = num(vf); m = Math.max(1, num(m) || 1);
    if (!(vi > 0) || !(vf > 0)) return 0;
    const t = 1 - Math.pow(vf / vi, 1 / m);
    return Number.isFinite(t) ? Math.max(0, t) : 0;
  }
  function parseReportText(data) {
    return String(data?.relatorio_textual || data?.relatorio_tecnico || data?.detalhes?.relatorio_tecnico || data?.detalhes?.curva?.relatorio_tecnico || "");
  }
  function extractText(text, regex) {
    const m = String(text || "").match(regex);
    return m && m[1] ? String(m[1]).trim() : "";
  }
  function getInfo(data) {
    const d = data || {};
    const detalhes = d.detalhes || {};
    const curva = detalhes.curva || {};
    const veiculo = detalhes.veiculo || {};
    const auditoria = d.auditoria_historico || detalhes.auditoria_historico || {};
    const bruto = parseReportText(d);
    const finalProj = getFinalProjection(d);
    const horizonte = Math.max(1, firstNum(d.horizonte_anos, d.horizonte_relatorio_anos, detalhes.horizonte_anos, 5));
    const meses = Math.max(1, firstNum(d.horizonte_meses, detalhes.horizonte_meses, Math.round(horizonte * 12)));
    const marcaModelo = [firstText(veiculo.marca, detalhes.marca, d.marca), firstText(veiculo.modelo, detalhes.modelo, d.modelo), firstText(veiculo.ano_modelo, veiculo.ano_combustivel, detalhes.ano_modelo, d.ano_modelo)].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
    const vi = firstNum(d.valor_atual, detalhes.valor_atual, veiculo.valor_atual, curva.valor_fipe_atual, extractText(bruto, /Valor FIPE atual(?: selecionado)?:\s*R\$\s*([^\n\r]+)/i));
    const vfBase = firstNum(d.valor_futuro_base, d.valor_futuro, finalProj.base, extractText(bruto, /Valor futuro base:\s*R\$\s*([^\n\r]+)/i));
    const vfOpt = firstNum(d.valor_futuro_otimista, finalProj.otimista, extractText(bruto, /Valor futuro otimista:\s*R\$\s*([^\n\r]+)/i));
    const vfPes = firstNum(d.valor_futuro_pessimista, finalProj.pessimista, extractText(bruto, /Valor futuro pessimista:\s*R\$\s*([^\n\r]+)/i));
    const dep = vi > 0 && vfBase > 0 ? (1 - vfBase / vi) * 100 : firstNum(d.depreciacao_percentual, d.depreciacao_total_percentual);
    const perda = vi > 0 && vfBase > 0 ? vi - vfBase : 0;
    const ia = firstNum(d.taxa_anual_efetiva_percentual, d.taxa_anual_percentual, taxaAnual(vi, vfBase, horizonte) * 100);
    const ref = firstNum(d.taxa_anual_referencia_percentual, detalhes.taxa_anual_referencia_percentual, curva.taxa_anual_referencia_percentual, curva.depreciacao_media_anual_principal_percentual, curva.depreciacao_media_anual_percentual, extractText(bruto, /Taxa anual equivalente de referência(?: da curva)?:\s*([0-9,.]+)/i));
    const tm = firstNum(d.taxa_mensal_hibrida_percentual, detalhes.taxa_mensal_hibrida_percentual, curva.taxa_mensal_hibrida_percentual, curva.taxa_mensal_percentual, extractText(bruto, /Taxa mensal híbrida base(?: da curva)?:\s*([0-9,.]+)/i));
    const modeloReferenciaSimilaridade = firstText(
      d.modelo_referencia_similaridade,
      detalhes.modelo_referencia_similaridade,
      auditoria.modelo_referencia_similaridade,
      curva.modelo_referencia_similaridade,
      d.modelo_referencia,
      detalhes.modelo_referencia,
      auditoria.modelo_referencia,
      curva.modelo_referencia,
      extractText(bruto, /Modelo referência da curva:\s*([^\n\r]+)/i)
    );
    const curvaPorSimilaridade = Boolean(
      d.curva_por_similaridade || detalhes.curva_por_similaridade || auditoria.curva_por_similaridade || curva.curva_por_similaridade ||
      String(d.tipo_curva_aplicada || detalhes.tipo_curva_aplicada || curva.tipo_curva_aplicada || "").toLowerCase() === "similaridade"
    );
    const modeloBase = firstText(
      curvaPorSimilaridade ? modeloReferenciaSimilaridade : "",
      curva.modelo_base_curva,
      detalhes.modelo_base_curva,
      extractText(bruto, /Modelo base usado como referência:\s*([^\n\r]+)/i),
      extractText(bruto, /Modelo-base\/curva de referência:\s*([^\n\r]+)/i),
      marcaModelo
    );
    const anoBase = firstText(cleanYear(curva.ano_base_curva), cleanYear(d.ano_base_curva), cleanYear(extractText(bruto, /Ano(?: âncora\/coorte usada|-base preferencial|\/coorte base):\s*([^\n\r]+)/i)));
    const dataZero = firstText(curva.data_zero_km_base, d.data_zero_km_base, detalhes.data_zero_km_base, extractText(bruto, /Data do zero km base:\s*([^\n\r]+)/i));
    const pontos = firstNum(d.pontos_historicos, detalhes.pontos_historicos, curva.pontos_historicos, extractText(bruto, /Pontos históricos(?: coletados)?:\s*([0-9]+)/i));
    const janela = firstNum(d.janela_historica_meses, detalhes.janela_historica_meses, curva.janela_historica_meses, extractText(bruto, /Janela histórica:\s*([0-9]+)/i));
    const idadeMeses = firstNum(d.idade_entrada_meses, detalhes.idade_entrada_meses, 0);
    const codigoFipe = firstText(veiculo.codigo_fipe, d.codigo_fipe, detalhes.codigo_fipe, curva.codigo_fipe, extractText(bruto, /Código FIPE:\s*([^\n\r]+)/i));
    const refFipe = firstText(d.data_base_fipe, detalhes.data_base_fipe, veiculo.referencia_fipe, veiculo.referencia, extractText(bruto, /Referência\/Data-base FIPE:\s*([^\n\r]+)/i), extractText(bruto, /Data-base da análise:\s*([^\n\r]+)/i));
    const origemSimilaridade = firstText(d.origem_similaridade, detalhes.origem_similaridade, auditoria.origem_similaridade, curva.origem_similaridade, extractText(bruto, /Origem do vínculo:\s*([^\n\r]+)/i));
    const chaveCurvaReferencia = firstText(d.chave_curva_referencia, detalhes.chave_curva_referencia, auditoria.chave_curva_referencia, curva.chave_curva_referencia, extractText(bruto, /Chave da curva referência:\s*([^\n\r]+)/i));
    const tipoCurvaAplicada = curvaPorSimilaridade ? "Curva herdada por similaridade" : "Curva própria";
    return {
      data: d,
      veiculo: marcaModelo || "veículo selecionado",
      codigoFipe,
      refFipe,
      vi,
      vfBase,
      vfOpt,
      vfPes,
      dep,
      perda,
      ia,
      ref,
      tm,
      horizonte,
      meses,
      idadeMeses,
      modeloBase,
      curvaPorSimilaridade,
      tipoCurvaAplicada,
      modeloReferenciaSimilaridade,
      origemSimilaridade,
      chaveCurvaReferencia,
      anoBase,
      dataZero,
      pontos,
      janela,
      confianca: firstText(d.confianca, detalhes.confianca, curva.confianca, "-"),
      categoria: firstText(d.tipo_label, d.tipo_curva, detalhes.tipo_utilizado, detalhes.tipo_label, "-")
    };
  }
  function serieBackend(data) {
    const serie = Array.isArray(data?.projecao_mensal) ? data.projecao_mensal : (Array.isArray(data?.detalhes?.projecao_mensal) ? data.detalhes.projecao_mensal : []);
    return serie.map(p => ({
      mes: Math.round(num(p.mes || 0)),
      idadeMeses: Math.round(num(p.idade_meses ?? p.idadeMeses ?? p.idade_curva_meses ?? p.mes ?? 0)),
      base: firstNum(p.valor_base, p.base, p.valor),
      otimista: firstNum(p.valor_otimista, p.otimista),
      pessimista: firstNum(p.valor_pessimista, p.pessimista),
      fatorBase: firstNum(p.fator_base, p.fatorBase),
      fatorOtimista: firstNum(p.fator_otimista, p.fatorOtimista),
      fatorPessimista: firstNum(p.fator_pessimista, p.fatorPessimista)
    })).filter(p => Number.isFinite(p.mes) && p.mes >= 0 && (p.base > 0 || p.otimista > 0 || p.pessimista > 0));
  }
  function buildMemory(info) {
    const back = serieBackend(info.data);
    const M = Math.max(1, Math.round(info.meses || info.horizonte * 12));
    let linhas = [];
    let fonte = "interpolacao_geometrica";
    if (back.length >= 2) {
      fonte = "serie_mensal_backend";
      linhas = back.sort((a,b) => a.mes-b.mes).map(p => ({
        mes: p.mes,
        idadeMeses: Number.isFinite(p.idadeMeses) ? p.idadeMeses : Math.round(info.idadeMeses + p.mes),
        base: p.base,
        otimista: p.otimista || p.base,
        pessimista: p.pessimista || p.base,
        fatorBase: p.fatorBase || (info.vi > 0 && p.base > 0 ? p.base / info.vi : 0),
        fatorOtimista: p.fatorOtimista || (info.vi > 0 && p.otimista > 0 ? p.otimista / info.vi : 0),
        fatorPessimista: p.fatorPessimista || (info.vi > 0 && p.pessimista > 0 ? p.pessimista / info.vi : 0)
      }));
    } else {
      const tb = taxaMensal(info.vi, info.vfBase, M);
      const to = taxaMensal(info.vi, info.vfOpt || info.vfBase, M);
      const tp = taxaMensal(info.vi, info.vfPes || info.vfBase, M);
      for (let m=0; m<=M; m++) {
        const base = info.vi * Math.pow(1 - tb, m);
        const otimista = info.vi * Math.pow(1 - to, m);
        const pessimista = info.vi * Math.pow(1 - tp, m);
        linhas.push({
          mes: m,
          idadeMeses: Math.round(info.idadeMeses + m),
          base,
          otimista,
          pessimista,
          fatorBase: info.vi > 0 ? base / info.vi : 0,
          fatorOtimista: info.vi > 0 ? otimista / info.vi : 0,
          fatorPessimista: info.vi > 0 ? pessimista / info.vi : 0
        });
      }
    }
    if (linhas.length) {
      const last = linhas[linhas.length - 1];
      if (info.vfBase > 0) last.base = info.vfBase;
      if (info.vfOpt > 0) last.otimista = info.vfOpt;
      if (info.vfPes > 0) last.pessimista = info.vfPes;
      ["Base","Otimista","Pessimista"].forEach(kind => {
        const k = kind.toLowerCase();
        last[`fator${kind}`] = info.vi > 0 && last[k] > 0 ? last[k] / info.vi : last[`fator${kind}`];
      });
    }
    let prev = null;
    linhas.forEach(p => {
      p.perdaBase = info.vi > 0 && p.base > 0 ? Math.max(0, info.vi - p.base) : 0;
      p.depreciacaoBase = info.vi > 0 && p.base > 0 ? Math.max(0, (1 - p.base / info.vi) * 100) : 0;
      p.taxaMesBase = prev && prev > 0 && p.base > 0 ? Math.max(0, (1 - p.base / prev) * 100) : 0;
      if (p.base > 0) prev = p.base;
    });
    return { linhas, fonte, meses: M };
  }
  function historyCandidates(data, corrected) {
    const d = data || {}, det = d.detalhes || {}, cur = det.curva || {};
    const names = corrected
      ? [d.historico_mensal_corrigido, det.historico_mensal_corrigido, d.historico_ipca, det.historico_ipca, cur.historico_mensal_corrigido, cur.historico_ipca, d.serie_historica_ipca, det.serie_historica_ipca]
      : [d.historico_mensal, det.historico_mensal, d.historico_nominal, det.historico_nominal, cur.historico_mensal, cur.historico_nominal, d.serie_historica_nominal, det.serie_historica_nominal];
    return names;
  }
  function normalizeHistoryArray(arr) {
    if (!Array.isArray(arr)) return [];
    return arr.map((p, idx) => {
      if (Array.isArray(p)) return { x: String(p[0] ?? idx), y: num(p[1]) };
      return {
        x: String(p.data_referencia || p.referencia || p.data || p.mes || p.periodo || idx),
        y: firstNum(p.valor_corrigido, p.valor_ipca, p.valor_fipe_corrigido, p.valor, p.preco, p.valor_fipe)
      };
    }).filter(p => p.x && p.y > 0);
  }
  function getHistory(data, corrected) {
    for (const arr of historyCandidates(data, corrected)) {
      const out = normalizeHistoryArray(arr);
      if (out.length >= 2) return out;
    }
    return [];
  }
  function lineChart(containerId, title, series, opts) {
    const el = $(containerId);
    if (!el) return;
    const validSeries = (series || []).map(s => ({...s, data: (s.data || []).filter(p => num(p.y) > 0)})).filter(s => s.data.length >= 2);
    if (!validSeries.length) {
      el.innerHTML = `<pre class="audit-log">plot indisponível: série sem pontos suficientes.</pre>`;
      return;
    }
    const W = 620, H = 330, L = 76, R = 22, T = 18, B = 55;
    const all = validSeries.flatMap(s => s.data);
    const maxX = Math.max(...all.map(p => num(p.xn ?? p.mes ?? 0)), 1);
    const minYRaw = Math.min(...all.map(p => num(p.y)));
    const maxYRaw = Math.max(...all.map(p => num(p.y)));
    const pad = Math.max((maxYRaw - minYRaw) * 0.08, maxYRaw * 0.03, 1);
    const minY = Math.max(0, minYRaw - pad);
    const maxY = maxYRaw + pad;
    const sx = x => L + (num(x) / maxX) * (W - L - R);
    const sy = y => T + (1 - ((num(y) - minY) / Math.max(1, maxY - minY))) * (H - T - B);
    const gridY = Array.from({length: 6}, (_, i) => minY + ((maxY - minY) / 5) * i);
    const gridX = Array.from({length: 6}, (_, i) => (maxX / 5) * i);
    const colors = ["#2563eb", "#ea580c", "#16a34a", "#7c3aed"];
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}">`;
    svg += `<rect x="0" y="0" width="${W}" height="${H}" fill="#fff"/>`;
    gridY.forEach(v => { const y = sy(v); svg += `<line x1="${L}" y1="${y}" x2="${W-R}" y2="${y}" stroke="#e5e7eb"/><text x="${L-8}" y="${y+4}" text-anchor="end" font-size="10">${opts?.percent ? pct(v,0) : money(v).replace("R$", "")}</text>`; });
    gridX.forEach(v => { const x = sx(v); svg += `<line x1="${x}" y1="${T}" x2="${x}" y2="${H-B}" stroke="#e5e7eb"/><text x="${x}" y="${H-28}" text-anchor="middle" font-size="10">${opts?.xLabels ? (opts.xLabels[Math.round(v)] || Math.round(v)) : Math.round(v)}</text>`; });
    svg += `<line x1="${L}" y1="${T}" x2="${L}" y2="${H-B}" stroke="#111827"/><line x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}" stroke="#111827"/>`;
    validSeries.forEach((s, idx) => {
      const color = s.color || colors[idx % colors.length];
      const pts = s.data.map(p => `${sx(p.xn ?? p.mes ?? 0).toFixed(2)},${sy(p.y).toFixed(2)}`).join(" ");
      svg += `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2"/>`;
      s.data.forEach((p, j) => {
        const step = Math.ceil(s.data.length / 24);
        if (j % step === 0 || j === s.data.length - 1) svg += `<circle cx="${sx(p.xn ?? p.mes ?? 0)}" cy="${sy(p.y)}" r="2.4" fill="${color}"/>`;
      });
    });
    svg += `<text x="${W/2}" y="${H-6}" text-anchor="middle" font-size="11">${esc(opts?.xTitle || "Mês")}</text>`;
    svg += `<text x="15" y="${H/2}" transform="rotate(-90 15 ${H/2})" text-anchor="middle" font-size="11">${esc(opts?.yTitle || "Valor")}</text>`;
    svg += `</svg>`;
    el.innerHTML = svg;
  }
  function lineChartHistory(containerId, history, yTitle, color) {
    const data = history.map((p, i) => ({ xn: i, x: p.x, y: p.y }));
    const xLabels = {};
    if (history.length) {
      [0, Math.floor(history.length/2), history.length-1].forEach(i => { if (history[i]) xLabels[i] = history[i].x; });
    }
    lineChart(containerId, yTitle, [{ name: yTitle, data, color }], { xTitle: "Referência FIPE", yTitle, xLabels });
  }
  function renderTable(memory) {
    const rows = memory.linhas.map(p => `<tr>
      <td>${p.mes}</td>
      <td>${p.idadeMeses}</td>
      <td>${dec(p.fatorBase, 6)}</td>
      <td>${pct(p.taxaMesBase, 4)}</td>
      <td>${money(p.base)}</td>
      <td>${money(p.otimista)}</td>
      <td>${money(p.pessimista)}</td>
      <td>${money(p.perdaBase)}</td>
      <td>${pct(p.depreciacaoBase, 2)}</td>
    </tr>`).join("");
    $("audit_month_table").innerHTML = `<div class="audit-table-wrap"><table class="audit-table">
      <thead><tr><th>mês</th><th>idade curva</th><th>fator base</th><th>taxa mês</th><th>V_base</th><th>V_otimista</th><th>V_pessimista</th><th>perda base</th><th>D_base</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }
  function render(data, pkg) {
    const info = getInfo(data);
    const memory = buildMemory(info);
    const im = taxaMensal(info.vi, info.vfBase, memory.meses) * 100;
    const io = taxaMensal(info.vi, info.vfOpt || info.vfBase, memory.meses) * 100;
    const ip = taxaMensal(info.vi, info.vfPes || info.vfBase, memory.meses) * 100;

    $("audit_status").textContent = `>> pacote carregado\n>> emissão: ${new Date().toLocaleString("pt-BR")}\n>> origem: ${pkg?.origem || "CurVE"}\n>> fonte da série mensal: ${memory.fonte}`;
    $("audit_summary").textContent = [
      `veículo                     = ${info.veiculo}`,
      `código FIPE                 = ${info.codigoFipe || "-"}`,
      `referência FIPE             = ${info.refFipe || "-"}`,
      `tipo_curva                  = ${info.tipoCurvaAplicada}`,
      ...(info.curvaPorSimilaridade ? [
        `modelo_referência_herdado  = ${info.modeloReferenciaSimilaridade || info.modeloBase || "-"}`,
        `origem_similaridade        = ${info.origemSimilaridade || "-"}`,
        `chave_curva_referência     = ${info.chaveCurvaReferencia || "-"}`
      ] : []),
      `VI                          = ${money(info.vi)}`,
      `VF_base                     = ${money(info.vfBase)}`,
      `VF_otimista                 = ${money(info.vfOpt)}`,
      `VF_pessimista               = ${money(info.vfPes)}`,
      `perda_base                  = ${money(info.perda)}`,
      `D_total_base                = ${pct(info.dep, 2)}`,
      `i_anual_base                = ${pct(info.ia, 4)} a.a.`,
      `i_mensal_equivalente_base   = ${pct(im, 6)} a.m.`,
      `confiança                   = ${info.confianca}`
    ].join("\n");
    $("audit_inputs").textContent = [
      `horizonte_h                 = ${formatYears(info.horizonte)}`,
      `horizonte_M                 = ${memory.meses} meses`,
      `idade_entrada_I0            = ${Math.round(info.idadeMeses || 0)} meses`,
      `tipo_curva_aplicada         = ${info.tipoCurvaAplicada}`,
      `modelo_referência_curva     = ${info.modeloBase || "-"}`,
      `coorte_ano_base             = ${info.anoBase || "-"}`,
      `data_zero_km_base           = ${info.dataZero || "-"}`,
      `pontos_históricos           = ${info.pontos || "-"}`,
      `janela_histórica            = ${info.janela ? `${info.janela} meses` : "-"}`,
      `categoria                   = ${info.categoria}`,
      `taxa_referência_curva       = ${info.ref ? `${pct(info.ref, 4)} a.a.` : "-"}`,
      `taxa_mensal_calibrada       = ${info.tm ? `${pct(info.tm, 6)} a.m.` : "-"}`
    ].join("\n");
    $("audit_equations").textContent = [
      `VI = valor FIPE inicial`,
      `VF = valor futuro do cenário`,
      `M  = horizonte em meses`,
      `h  = horizonte em anos`,
      `m  = mês da projeção`,
      `I0 = idade de entrada do veículo na curva`,
      ``,
      `Depreciação total:       D_total = 1 - (VF / VI)`,
      `Perda econômica:         P       = VI - VF`,
      `Taxa anual equivalente:  i_a     = 1 - (VF / VI)^(1 / h)`,
      `Taxa mensal equivalente: i_m     = 1 - (VF / VI)^(1 / M)`,
      `Coeficiente mensal:      q       = (VF / VI)^(1 / M)`,
      `Interpolação geométrica: V_m     = VI × q^m = VI × (1 - i_m)^m`,
      `Perda no mês m:          P_m     = VI - V_m`,
      `Depreciação no mês m:    D_m     = 1 - (V_m / VI)`,
      ``,
      `Quando há curva mensal calibrada pelo backend:`,
      `V_m = VI × Π[k=0 até m-1] (1 - r_k)`,
      `r_k = r_base × f_idade(I0 + k)`,
      ``,
      `Cenários:`,
      `V_m(base)       = série central da curva`,
      `V_m(otimista)   = série com menor depreciação relativa`,
      `V_m(pessimista) = série com maior depreciação relativa`
    ].join("\n");

    const projectionSeries = [
      { name: "base", color: "#2563eb", data: memory.linhas.map(p => ({ xn: p.mes, y: p.base })) },
      { name: "otimista", color: "#ea580c", data: memory.linhas.map(p => ({ xn: p.mes, y: p.otimista })) },
      { name: "pessimista", color: "#16a34a", data: memory.linhas.map(p => ({ xn: p.mes, y: p.pessimista })) }
    ];
    lineChart("plot_projection", "Projeção mensal", projectionSeries, { xTitle: "Mês de projeção", yTitle: "Valor projetado (R$)" });
    lineChart("plot_depreciation", "Depreciação acumulada", [{ name: "D_m", color: "#2563eb", data: memory.linhas.map(p => ({ xn: p.mes, y: p.depreciacaoBase })) }], { xTitle: "Mês de projeção", yTitle: "Depreciação (%)", percent: true });
    const histNom = getHistory(data, false);
    const histIpca = getHistory(data, true);
    if (histNom.length >= 2) lineChartHistory("plot_history_nominal", histNom, "Valor FIPE nominal (R$)", "#2563eb");
    else $("plot_history_nominal").innerHTML = `<pre class="audit-log">histórico nominal não disponível no pacote recebido.</pre>`;
    if (histIpca.length >= 2) lineChartHistory("plot_history_ipca", histIpca, "Valor corrigido IPCA (R$)", "#7c3aed");
    else $("plot_history_ipca").innerHTML = `<pre class="audit-log">histórico IPCA não disponível no pacote recebido.</pre>`;
    renderTable(memory);
    $("audit_interpretation").textContent = [
      `O resumo executivo usa o ponto final da memória mensal. Portanto, VF_base = V_${memory.meses}(base).`,
      `A curva de projeção é construída por pares ordenados (m, V_m).`,
      `A tabela mês a mês permite reconstituir o valor apresentado no resultado e validar a transição entre VI e VF.`,
      `Para veículos usados, a idade inicial I0 desloca a janela de aplicação da curva, evitando tratar o veículo usado como zero km.`,
      ...(info.curvaPorSimilaridade ? [`Neste caso, a curva é herdada por similaridade: o valor FIPE inicial é do veículo selecionado e a função/taxa de depreciação vem do modelo referência informado na auditoria.`] : []),
      `O resultado é uma estimativa estatística baseada em FIPE, histórico e curva calibrada; não substitui avaliação comercial individual.`
    ].join("\n");
  }
  function init() {
    const key = new URLSearchParams(window.location.search).get("key") || "";
    const raw = key ? localStorage.getItem(`curve_auditoria_depreciacao_${key}`) : "";
    if (!raw) {
      $("audit_status").textContent = ">> erro: pacote de auditoria não encontrado.\n>> volte à página de depreciação e clique novamente em Auditoria.";
      return;
    }
    try {
      const pkg = JSON.parse(raw);
      const data = pkg.resultado || pkg;
      render(data, pkg);
    } catch (e) {
      $("audit_status").textContent = `>> erro ao carregar auditoria: ${e && e.message ? e.message : e}`;
    }
  }
  document.addEventListener("DOMContentLoaded", init);
})();
