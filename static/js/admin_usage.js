(() => {
  "use strict";

  const TOKEN_KEY = "curve_admin_usage_token_v1";
  const state = {
    token: "",
    start: "",
    end: "",
    preset: "30d",
    summary: null,
    visitors: [],
    visitorsOffset: 0,
    visitorsHasMore: false,
    events: [],
    eventsOffset: 0,
    eventsHasMore: false,
    visitorFilter: "",
    moduleFilter: "",
  };

  const $ = (id) => document.getElementById(id);
  const fmt = new Intl.NumberFormat("pt-BR");

  function dateInputValue(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function localDateBoundaryIso(value, endOfDay = false) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
    if (!match) return "";
    const [, y, m, d] = match;
    const date = new Date(
      Number(y), Number(m) - 1, Number(d),
      endOfDay ? 23 : 0,
      endOfDay ? 59 : 0,
      endOfDay ? 59 : 0,
      endOfDay ? 999 : 0
    );
    return date.toISOString();
  }

  function setPreset(preset) {
    const today = new Date();
    let start = "";
    let end = "";
    if (preset === "today") {
      start = end = dateInputValue(today);
    } else if (preset === "7d" || preset === "30d") {
      const back = new Date(today);
      back.setDate(back.getDate() - (preset === "7d" ? 6 : 29));
      start = dateInputValue(back);
      end = dateInputValue(today);
    } else if (preset === "month") {
      start = dateInputValue(new Date(today.getFullYear(), today.getMonth(), 1));
      end = dateInputValue(today);
    }
    state.start = start;
    state.end = end;
    state.preset = preset;
    $("admin_start_date").value = start;
    $("admin_end_date").value = end;
    document.querySelectorAll("#admin_filter_presets button").forEach((button) => {
      button.classList.toggle("active", button.dataset.preset === preset);
    });
  }

  function queryRange(extra = {}) {
    const params = new URLSearchParams();
    if (state.start) params.set("start", localDateBoundaryIso(state.start, false));
    if (state.end) params.set("end", localDateBoundaryIso(state.end, true));
    // O SQLite armazena os eventos em UTC. Este deslocamento permite que os
    // buckets diários do gráfico respeitem o fuso local de quem administra.
    params.set("tz_offset_minutes", String(-new Date().getTimezoneOffset()));
    Object.entries(extra).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
    });
    const text = params.toString();
    return text ? `?${text}` : "";
  }

  async function adminFetch(path) {
    const response = await fetch(path, {
      headers: { "X-PlugVE-Admin-Token": state.token, Accept: "application/json" },
      cache: "no-store",
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      const error = new Error(payload.error || `Falha administrativa (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function showAuth(message = "") {
    $("admin_auth_panel").classList.remove("hidden");
    $("admin_dashboard").classList.add("hidden");
    $("admin_login_error").textContent = message;
  }

  function showDashboard() {
    $("admin_auth_panel").classList.add("hidden");
    $("admin_dashboard").classList.remove("hidden");
  }

  async function login() {
    const token = $("admin_token_input").value.trim();
    if (!token) {
      $("admin_login_error").textContent = "Informe o token administrativo.";
      return;
    }
    state.token = token;
    $("admin_login_button").disabled = true;
    $("admin_login_error").textContent = "";
    try {
      await adminFetch(`/api/site-usage/admin/telemetry/summary${queryRange()}`);
      sessionStorage.setItem(TOKEN_KEY, token);
      showDashboard();
      await loadAll();
    } catch (error) {
      state.token = "";
      sessionStorage.removeItem(TOKEN_KEY);
      $("admin_login_error").textContent = error.status === 401 ? "Token administrativo inválido." : error.message;
    } finally {
      $("admin_login_button").disabled = false;
    }
  }

  function logout() {
    state.token = "";
    sessionStorage.removeItem(TOKEN_KEY);
    $("admin_token_input").value = "";
    showAuth("");
  }

  function setMetric(id, value) { $(id).textContent = fmt.format(Number(value || 0)); }

  function renderMetrics(summary) {
    const c = summary?.counts || {};
    setMetric("metric_visitors", c.visitors);
    setMetric("metric_sessions", c.sessions);
    setMetric("metric_page_views", c.page_views);
    setMetric("metric_tco", c.tco_simulations);
    setMetric("metric_depreciacao", c.depreciation_consultations);
    setMetric("metric_fipe", c.fipe_plus_consultations);
    setMetric("metric_pdf", c.pdf_exports);
  }

  function moduleLabel(module) {
    return ({ tco: "TCO", depreciacao: "Depreciação", fipe_plus: "Fipe+", home: "Início", contato: "Contato", sobre: "Sobre" })[module] || module || "Site";
  }

  function actionLabel(action) {
    return ({
      page_view: "Visualizou a página",
      simulation_completed: "Concluiu uma simulação",
      consultation_completed: "Concluiu uma consulta",
      pdf_exported: "Exportou PDF",
      curve_requested: "Solicitou uma curva",
    })[action] || String(action || "Atividade").replaceAll("_", " ");
  }

  function technologyLabel(value) {
    const key = String(value || "").toLowerCase();
    return ({ ve: "Elétrico", bev: "Elétrico", eletrico: "Elétrico", phev: "PHEV", hibrido: "Híbrido", hev: "Híbrido", icev: "Combustão", combustao: "Combustão", diesel: "Diesel", gasolina: "Gasolina/Flex" })[key] || value || "Não classificado";
  }

  function vehicleName(item) {
    if (!item) return "Veículo";
    const model = String(item.modelo || "").trim();
    const brand = String(item.marca || "").trim();
    return model || brand || "Veículo";
  }

  function aggregate(items, keyFn, mapper) {
    const map = new Map();
    items.forEach((item) => {
      const key = keyFn(item);
      if (!key) return;
      const current = map.get(key) || { ...mapper(item), uses: 0 };
      current.uses += Number(item.uses || 0);
      map.set(key, current);
    });
    return [...map.values()].sort((a, b) => b.uses - a.uses);
  }

  function rankingHTML(items, renderText, emptyText = "Sem dados neste período.", limit = 10) {
    if (!items.length) return `<div class="admin-empty">${emptyText}</div>`;
    return items.slice(0, limit).map((item, index) => {
      const rendered = renderText(item);
      return `<div class="admin-rank-row"><span class="admin-rank-num">${index + 1}</span><div class="admin-rank-main"><strong title="${escapeHtml(rendered.title)}">${escapeHtml(rendered.title)}</strong><small>${escapeHtml(rendered.sub || "")}</small></div><span class="admin-rank-value">${fmt.format(item.uses || 0)}</span></div>`;
    }).join("");
  }

  function renderRankings() {
    const summary = state.summary || {};
    const module = $("admin_vehicle_module_filter").value || "all";
    const vehicleSource = (summary.top_vehicles || []).filter((item) => module === "all" || item.module === module);
    const vehicles = aggregate(vehicleSource, (item) => item.vehicle_key || `${item.marca}|${item.modelo}|${item.ano_modelo}`, (item) => item);
    $("admin_top_vehicles").innerHTML = rankingHTML(vehicles, (item) => ({
      title: vehicleName(item),
      sub: [item.marca, item.ano_modelo, module === "all" ? "vários módulos" : moduleLabel(item.module)].filter(Boolean).join(" · "),
    }));

    $("admin_top_pairs").innerHTML = rankingHTML(summary.top_pairs || [], (item) => ({
      title: `${vehicleName(item.vehicle_1)} × ${vehicleName(item.vehicle_2)}`,
      sub: [item.vehicle_1?.marca, item.vehicle_2?.marca].filter(Boolean).join(" × "),
    }), "Ainda não há comparações TCO neste período.");

    const tech = aggregate(summary.technology_usage || [], (item) => technologyLabel(item.technology), (item) => ({ title: technologyLabel(item.technology), module: item.module }));
    $("admin_technology_usage").innerHTML = rankingHTML(tech, (item) => ({ title: item.title, sub: "veículos registrados" }), "Sem tecnologia classificada.", 8);

    const brands = aggregate(summary.top_brands || [], (item) => item.marca, (item) => ({ marca: item.marca }));
    $("admin_top_brands").innerHTML = rankingHTML(brands, (item) => ({ title: item.marca, sub: "ocorrências em consultas" }), "Sem marcas registradas.", 8);

    $("admin_simulation_locations").innerHTML = rankingHTML(summary.simulation_locations || [], (item) => ({ title: item.city || item.uf || "—", sub: item.uf || "local informado" }), "Sem localizações de simulação.", 8);

    renderDepreciationCurveTypes(summary.depreciation_curve_types || {});

    renderAccessLocations(summary.access_locations || []);
  }

  function renderDepreciationCurveTypes(types) {
    const items = [
      { title: "Curva própria", uses: Number(types.propria || 0), sub: "consultas com curva própria identificada" },
      { title: "Herdada por similaridade", uses: Number(types.similaridade || 0), sub: "consultas com vínculo de similaridade" },
      { title: "Não informado / legado", uses: Number(types.nao_informado || 0), sub: "eventos antigos sem classificação explícita" },
    ].filter((item) => item.uses > 0);
    $("admin_depreciation_curve_types").innerHTML = rankingHTML(
      items,
      (item) => ({ title: item.title, sub: item.sub }),
      "Ainda não há consultas de Depreciação classificadas neste período.",
      3
    );
  }

  function renderAccessLocations(items) {
    const host = $("admin_access_locations");
    if (!items.length) {
      host.innerHTML = '<div class="admin-empty">A hospedagem ainda não forneceu localização aproximada dos acessos.</div>';
      return;
    }
    host.innerHTML = items.slice(0, 12).map((item) => {
      const title = [item.city, item.region].filter(Boolean).join(" / ") || item.country || "Local não identificado";
      const sub = `${fmt.format(item.visitors)} visitante(s) · ${fmt.format(item.events)} evento(s)`;
      return `<div class="admin-location-card"><strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong><span>${escapeHtml(sub)}</span></div>`;
    }).join("");
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[ch]);
  }

  function renderTrend() {
    const data = state.summary?.daily || [];
    const canvas = $("admin_trend_canvas");
    const empty = $("admin_trend_empty");
    if (!data.length) {
      canvas.classList.add("hidden");
      empty.classList.remove("hidden");
      return;
    }
    canvas.classList.remove("hidden");
    empty.classList.add("hidden");
    const rect = canvas.parentElement.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(620, rect.width || 900);
    const height = 270;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    const pad = { l: 42, r: 18, t: 14, b: 34 };
    const innerW = width - pad.l - pad.r;
    const innerH = height - pad.t - pad.b;
    const series = [
      { key: "visitors", color: "#168a4a" },
      { key: "tco", color: "#4a78a6" },
      { key: "depreciacao", color: "#b78645" },
      { key: "fipe_plus", color: "#756c97" },
    ];
    const max = Math.max(1, ...data.flatMap((row) => series.map((s) => Number(row[s.key] || 0))));
    ctx.font = "11px Inter, system-ui, sans-serif";
    ctx.fillStyle = "#728179";
    ctx.strokeStyle = "#e3ebe7";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + innerH * i / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(width - pad.r, y); ctx.stroke();
      const value = Math.round(max * (1 - i / 4));
      ctx.fillText(String(value), 5, y + 4);
    }
    const xAt = (index) => pad.l + (data.length === 1 ? innerW / 2 : innerW * index / (data.length - 1));
    const yAt = (value) => pad.t + innerH - (Number(value || 0) / max) * innerH;
    series.forEach((s) => {
      ctx.strokeStyle = s.color; ctx.lineWidth = 2.4; ctx.beginPath();
      data.forEach((row, index) => { const x = xAt(index), y = yAt(row[s.key]); if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
      ctx.stroke();
      ctx.fillStyle = s.color;
      data.forEach((row, index) => { const x = xAt(index), y = yAt(row[s.key]); ctx.beginPath(); ctx.arc(x, y, 2.3, 0, Math.PI * 2); ctx.fill(); });
    });
    ctx.fillStyle = "#728179";
    const step = Math.max(1, Math.ceil(data.length / 7));
    data.forEach((row, index) => {
      if (index % step !== 0 && index !== data.length - 1) return;
      const date = String(row.day || "");
      const label = date.length >= 10 ? `${date.slice(8,10)}/${date.slice(5,7)}` : date;
      const x = xAt(index);
      ctx.fillText(label, Math.max(pad.l, x - 16), height - 10);
    });
  }

  function formatDateTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  }

  function visitorLocation(item) {
    return [item.city, item.region].filter(Boolean).join(" / ") || item.country || "Não disponível";
  }

  function renderVisitors() {
    const search = $("admin_visitor_search").value.trim().toLowerCase();
    const filtered = state.visitors.filter((item) => {
      if (!search) return true;
      return [item.visitor, item.city, item.region, item.country, item.browser, item.device, item.os].join(" ").toLowerCase().includes(search);
    });
    $("admin_visitors_total").textContent = `${fmt.format(state.visitorsTotal || 0)} visitante(s)`;
    const body = $("admin_visitors_body");
    if (!filtered.length) {
      body.innerHTML = '<tr><td colspan="6"><div class="admin-empty">Nenhum visitante encontrado.</div></td></tr>';
    } else {
      body.innerHTML = filtered.map((item) => {
        const env = [item.device, item.browser, item.os].filter(Boolean).join(" · ") || "—";
        const periodSessions = item.period_sessions ?? item.sessions;
        const periodEvents = item.period_events ?? item.events;
        const last = item.period_last_seen || item.last_seen_at;
        return `<tr data-visitor="${escapeHtml(item.visitor)}"><td><span class="admin-visitor-id">${escapeHtml(item.visitor)}</span><span class="admin-cell-sub">rede ${escapeHtml(item.network || "—")}</span></td><td>${escapeHtml(visitorLocation(item))}<span class="admin-cell-sub">${escapeHtml(item.country || "")}</span></td><td>${fmt.format(periodSessions || 0)}<span class="admin-cell-sub">${fmt.format(item.sessions || 0)} total</span></td><td>${fmt.format(periodEvents || 0)}<span class="admin-cell-sub">${fmt.format(item.events || 0)} total</span></td><td>${escapeHtml(formatDateTime(last))}</td><td>${escapeHtml(env)}</td></tr>`;
      }).join("");
      body.querySelectorAll("tr[data-visitor]").forEach((row) => row.addEventListener("click", () => selectVisitor(row.dataset.visitor)));
    }
    $("admin_visitors_more").classList.toggle("hidden", !state.visitorsHasMore);
  }

  function eventVehicleText(event) {
    const vehicles = event.vehicles || [];
    if (!vehicles.length) return "";
    if (event.module === "tco" && vehicles.length >= 2) return `${vehicleName(vehicles[0])} × ${vehicleName(vehicles[1])}`;
    return vehicles.map(vehicleName).filter(Boolean).join(" · ");
  }

  function eventDetails(event) {
    const parts = [];
    const vehicles = eventVehicleText(event);
    if (vehicles) parts.push(vehicles);
    if (event.simulation_city || event.simulation_uf) parts.push(`simulação: ${[event.simulation_city, event.simulation_uf].filter(Boolean).join("/")}`);
    if (event.horizon_years) parts.push(`${event.horizon_years} ano(s)`);
    if (event.km_year) parts.push(`${fmt.format(event.km_year)} km/ano`);
    if (event.module === "depreciacao" && event.metadata?.tipo_curva) {
      const tipo = String(event.metadata.tipo_curva || "");
      if (tipo === "propria") parts.push("curva própria");
      else if (tipo === "similaridade") parts.push("curva por similaridade");
    }
    return parts.join(" · ");
  }

  function renderEvents() {
    const host = $("admin_events_feed");
    if (!state.events.length) {
      host.innerHTML = '<div class="admin-empty">Nenhuma atividade encontrada neste período.</div>';
    } else {
      host.innerHTML = state.events.map((event) => {
        const access = [event.access_city, event.access_region].filter(Boolean).join("/") || "local não disponível";
        return `<article class="admin-event-item"><div class="admin-event-time">${escapeHtml(formatDateTime(event.occurred_at))}</div><div class="admin-event-module">${escapeHtml(moduleLabel(event.module))}</div><div class="admin-event-main"><strong>${escapeHtml(actionLabel(event.action))}</strong><p>${escapeHtml(eventDetails(event) || event.path || "")}</p></div><div class="admin-event-visitor"><strong>${escapeHtml(event.visitor)}</strong>${escapeHtml(access)}</div></article>`;
      }).join("");
    }
    $("admin_events_more").classList.toggle("hidden", !state.eventsHasMore);
    if (state.visitorFilter) {
      $("admin_events_title").textContent = `Atividade do visitante ${state.visitorFilter}`;
      $("admin_clear_visitor_filter").classList.remove("hidden");
    } else {
      $("admin_events_title").textContent = "Últimas atividades";
      $("admin_clear_visitor_filter").classList.add("hidden");
    }
  }

  async function loadSummary() {
    state.summary = await adminFetch(`/api/site-usage/admin/telemetry/summary${queryRange()}`);
    renderMetrics(state.summary);
    renderRankings();
    renderTrend();
  }

  async function loadVisitors(reset = true) {
    if (reset) { state.visitorsOffset = 0; state.visitors = []; }
    const page = await adminFetch(`/api/site-usage/admin/telemetry/visitors${queryRange({ offset: state.visitorsOffset, limit: 100 })}`);
    state.visitors = state.visitors.concat(page.visitors || []);
    state.visitorsOffset += (page.visitors || []).length;
    state.visitorsHasMore = !!page.has_more;
    state.visitorsTotal = Number(page.total || 0);
    renderVisitors();
  }

  async function loadEvents(reset = true) {
    if (reset) { state.eventsOffset = 0; state.events = []; }
    const page = await adminFetch(`/api/site-usage/admin/telemetry/events${queryRange({ offset: state.eventsOffset, limit: 100, module: state.moduleFilter, visitor: state.visitorFilter })}`);
    state.events = state.events.concat(page.events || []);
    state.eventsOffset += (page.events || []).length;
    state.eventsHasMore = !!page.has_more;
    renderEvents();
  }

  async function loadAll() {
    $("admin_refresh_status").textContent = "Atualizando...";
    try {
      await Promise.all([loadSummary(), loadVisitors(true), loadEvents(true)]);
      $("admin_refresh_status").textContent = `Atualizado ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
    } catch (error) {
      if (error.status === 401) {
        logout();
        showAuth("A sessão administrativa expirou ou o token foi recusado.");
        return;
      }
      $("admin_refresh_status").textContent = "Falha ao atualizar";
      console.error(error);
    }
  }

  async function selectVisitor(visitor) {
    state.visitorFilter = visitor || "";
    state.eventsOffset = 0;
    state.events = [];
    await loadEvents(true);
    $("admin_events_title").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function bind() {
    setPreset("30d");
    $("admin_login_button").addEventListener("click", login);
    $("admin_token_input").addEventListener("keydown", (event) => { if (event.key === "Enter") login(); });
    $("admin_logout_button").addEventListener("click", logout);
    $("admin_refresh_button").addEventListener("click", loadAll);
    document.querySelectorAll("#admin_filter_presets button").forEach((button) => button.addEventListener("click", async () => { setPreset(button.dataset.preset); state.visitorFilter = ""; await loadAll(); }));
    $("admin_apply_dates").addEventListener("click", async () => {
      state.start = $("admin_start_date").value || "";
      state.end = $("admin_end_date").value || "";
      state.preset = "custom";
      document.querySelectorAll("#admin_filter_presets button").forEach((button) => button.classList.remove("active"));
      state.visitorFilter = "";
      await loadAll();
    });
    $("admin_vehicle_module_filter").addEventListener("change", renderRankings);
    $("admin_event_module_filter").addEventListener("change", async (event) => { state.moduleFilter = event.target.value || ""; await loadEvents(true); });
    $("admin_clear_visitor_filter").addEventListener("click", async () => { state.visitorFilter = ""; await loadEvents(true); });
    $("admin_visitor_search").addEventListener("input", renderVisitors);
    $("admin_visitors_more").addEventListener("click", () => loadVisitors(false));
    $("admin_events_more").addEventListener("click", () => loadEvents(false));
    let resizeTimer = null;
    window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderTrend, 120); });
  }

  async function init() {
    bind();
    const saved = sessionStorage.getItem(TOKEN_KEY) || "";
    if (!saved) return showAuth("");
    state.token = saved;
    try {
      await adminFetch(`/api/site-usage/admin/telemetry/summary${queryRange()}`);
      showDashboard();
      await loadAll();
    } catch (_) {
      state.token = "";
      sessionStorage.removeItem(TOKEN_KEY);
      showAuth("Informe novamente o token administrativo.");
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
