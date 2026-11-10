/* Shared helpers: API, formatting, multi-select filters, chart defaults */
(function () {
  "use strict";
  const csrf = () => document.querySelector('meta[name="csrf-token"]').content;

  // Sidebar toggle (mobile)
  const nt = document.getElementById("navToggle");
  if (nt) {
    nt.addEventListener("click", () => document.body.classList.toggle("nav-open"));
    document.addEventListener("click", (e) => {
      if (document.body.classList.contains("nav-open") && !e.target.closest("#sidebar") && !e.target.closest("#navToggle"))
        document.body.classList.remove("nav-open");
    });
  }

  async function api(url, opts) {
    opts = opts || {};
    const init = { method: opts.method || "GET", headers: { "X-CSRF-Token": csrf() }, credentials: "same-origin" };
    if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
    const r = await fetch(url, init);
    if (r.status === 401) { location.href = "/login"; throw new Error("Session expired"); }
    let data = {};
    try { data = await r.json(); } catch (e) { /* ignore */ }
    if (!r.ok) { const err = new Error(data.error || ("Request failed (" + r.status + ")")); err.data = data; throw err; }
    return data;
  }

  // ---------- number / date formatting (Indian grouping)
  const UNITS = { full: { div: 1, suf: "", dec: 0 }, lakh: { div: 1e5, suf: " L", dec: 2 }, crore: { div: 1e7, suf: " Cr", dec: 2 } };
  function getUnit() { try { return localStorage.getItem("it_unit") || "full"; } catch (e) { return "full"; } }
  function setUnit(u) { try { localStorage.setItem("it_unit", u); } catch (e) { /* ignore */ } }
  const inr = (v, dec) => Number(v).toLocaleString("en-IN", { minimumFractionDigits: dec || 0, maximumFractionDigits: dec || 0 });

  function amt(v, o) {
    o = o || {};
    if (v === null || v === undefined || Number.isNaN(v)) return "–";
    const u = UNITS[o.unit || getUnit()];
    const dec = o.dec !== undefined ? o.dec : u.dec;
    const s = inr(v / u.div, dec) + u.suf;
    return (o.sym === false ? "" : "₹ ") + s;
  }
  const full = (v) => (v === null || v === undefined ? "–" : "₹ " + inr(v, 0));
  function compact(v) { // axis ticks: Indian Cr / L with up to 2 decimals
    const a = Math.abs(v), t = (x) => String(parseFloat(x.toFixed(2)));
    if (a >= 1e7) return "₹" + t(v / 1e7) + " Cr";
    if (a >= 1e5) return "₹" + t(v / 1e5) + " L";
    if (a >= 1e3) return "₹" + t(v / 1e3) + "k";
    return "₹" + v;
  }
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function dmy(s) { if (!s) return "–"; const p = s.slice(0, 10).split("-"); return p[2] + "-" + MON[+p[1] - 1] + "-" + p[0]; }
  function mon(s) { const p = s.slice(0, 10).split("-"); return MON[+p[1] - 1] + " " + p[0].slice(2); }
  function pct(v, withSign) {
    if (v === null || v === undefined) return "–";
    return (withSign && v > 0 ? "+" : "") + v.toFixed(2) + "%";
  }
  function deltaHTML(change, p) {
    if (change === null || change === undefined) return '<span class="muted">–</span>';
    const cls = change > 0 ? "pos" : change < 0 ? "neg" : "muted";
    const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "•";
    return '<span class="' + cls + '">' + arrow + " " + amt(Math.abs(change)) + (p !== null && p !== undefined ? " (" + pct(Math.abs(p)) + ")" : "") + "</span>";
  }
  const esc = (s) => String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- unit toggle (renders into #unitToggle)
  function mountUnitToggle(onChange) {
    const el = document.getElementById("unitToggle");
    if (!el) return;
    el.innerHTML = '<div class="seg" role="group" aria-label="Amount units"><button data-u="full">₹</button><button data-u="lakh">Lakhs</button><button data-u="crore">Crores</button></div>';
    const sync = () => el.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.u === getUnit()));
    el.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; setUnit(b.dataset.u); sync(); onChange && onChange(); });
    sync();
  }

  // ---------- palette (validated: blue/red first; see README)
  const PALETTE = ["#2a78d6", "#e34948", "#6250d6", "#eda100", "#008300", "#e87ba4", "#1baf7a"];
  const OTHER = "#8a94a6";
  const POS = "#2a78d6", NEG = "#e34948";
  function seqBlues(n) { // light -> dark, last (latest period) darkest
    const a = [200, 222, 247], b = [23, 60, 130];
    return Array.from({ length: n }, (_, i) => {
      const t = n === 1 ? 1 : 0.18 + 0.82 * (i / (n - 1));
      return "rgb(" + a.map((x, k) => Math.round(x + (b[k] - x) * t)).join(",") + ")";
    });
  }

  let META = null;
  async function loadMeta() { if (!META) META = await api("/api/meta"); return META; }
  function colorFor(dim, label) {
    const order = (META.color_order && META.color_order[dim]) || [];
    const i = order.indexOf(label);
    return i >= 0 && i < PALETTE.length ? PALETTE[i] : OTHER;
  }
  /* fold rows [{label,value}] -> keep those that own a palette colour, merge the rest into "Other" */
  function foldOthers(dim, items, valueKey) {
    const keep = [], rest = [];
    items.forEach((it) => (colorFor(dim, it.label) !== OTHER ? keep : rest).push(it));
    if (rest.length) {
      const o = { label: "Other (" + rest.length + ")", members: rest.map((r) => r.label), _other: true };
      (Array.isArray(valueKey) ? valueKey : [valueKey]).forEach((k) => (o[k] = rest.reduce((s, r) => s + (r[k] || 0), 0)));
      keep.push(o);
    }
    return keep;
  }

  // ---------- Chart.js defaults
  function setupCharts() {
    if (!window.Chart) return;
    const C = Chart;
    C.defaults.font.family = '"Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif';
    C.defaults.font.size = 12;
    C.defaults.color = "#4a5568";
    C.defaults.maintainAspectRatio = false;
    C.defaults.animation.duration = 350;
    C.defaults.plugins.legend.display = false; // we render HTML legends
    C.defaults.plugins.tooltip.backgroundColor = "#16202e";
    C.defaults.plugins.tooltip.padding = 10;
    C.defaults.plugins.tooltip.cornerRadius = 8;
    C.defaults.plugins.tooltip.titleFont = { weight: "600" };
    C.defaults.plugins.tooltip.boxPadding = 4;
    C.defaults.elements.bar.borderRadius = 4;
    C.defaults.elements.line.borderWidth = 2;
    C.defaults.elements.point.radius = 3;
    C.defaults.elements.point.hoverRadius = 6;
    C.defaults.datasets.bar.maxBarThickness = 44;
  }
  setupCharts();
  const GRID = { color: "#eef1f6", drawBorder: false, borderDash: [] };
  const moneyTip = { callbacks: { label: (c) => " " + (c.dataset.label ? c.dataset.label + ": " : "") + full(c.parsed.y !== undefined && c.chart.options.indexAxis !== "y" ? c.parsed.y : c.parsed.x) } };

  const charts = {};
  function drawChart(id, cfg) {
    if (charts[id]) charts[id].destroy();
    const el = document.getElementById(id);
    if (!el) return null;
    charts[id] = new Chart(el.getContext("2d"), cfg);
    return charts[id];
  }
  function legendHTML(el, items) {
    el.innerHTML = items.map((i) => '<span><i style="background:' + i.color + '"></i>' + esc(i.label) + (i.extra ? ' <b style="color:#16202e">' + i.extra + "</b>" : "") + "</span>").join("");
  }

  // ---------- multi-select dropdown
  function makeMS(host, label, options, onChange) {
    const state = { sel: new Set() };
    host.classList.add("field");
    host.innerHTML = "<label>" + esc(label) + '</label><div class="ms"><button type="button"></button><div class="panel"></div></div>';
    const ms = host.querySelector(".ms"), btn = ms.querySelector("button"), panel = ms.querySelector(".panel");
    function renderBtn() {
      if (!state.sel.size) btn.textContent = "All";
      else if (state.sel.size <= 2) btn.textContent = options.filter((o) => state.sel.has(String(o.value))).map((o) => o.label).join(", ");
      else btn.textContent = state.sel.size + " selected";
    }
    function renderPanel() {
      panel.innerHTML = '<div class="actions"><a data-a="all">Select all</a><a data-a="none">Clear</a></div>' +
        options.map((o) => '<label><input type="checkbox" value="' + esc(o.value) + '"' + (state.sel.has(String(o.value)) ? " checked" : "") + "> " + esc(o.label) + "</label>").join("");
    }
    btn.addEventListener("click", (e) => { e.stopPropagation(); document.querySelectorAll(".ms.open").forEach((m) => m !== ms && m.classList.remove("open")); ms.classList.toggle("open"); });
    panel.addEventListener("click", (e) => e.stopPropagation());
    panel.addEventListener("change", (e) => {
      const cb = e.target; if (cb.type !== "checkbox") return;
      cb.checked ? state.sel.add(cb.value) : state.sel.delete(cb.value);
      renderBtn(); onChange && onChange();
    });
    panel.addEventListener("click", (e) => {
      const a = e.target.closest("a[data-a]"); if (!a) return;
      state.sel = a.dataset.a === "all" ? new Set(options.map((o) => String(o.value))) : new Set();
      if (a.dataset.a === "all" && state.sel.size === options.length) state.sel = new Set(options.map((o) => String(o.value)));
      renderPanel(); renderBtn(); onChange && onChange();
    });
    document.addEventListener("click", () => ms.classList.remove("open"));
    renderPanel(); renderBtn();
    return {
      get: () => Array.from(state.sel),
      set: (vals) => { state.sel = new Set(vals.map(String)); renderPanel(); renderBtn(); },
    };
  }

  /* Filter bar: builds Entity / Group / Type / Bank / Fund filters inside `host` */
  function buildFilters(host, fields, onChange) {
    const defs = {
      entity: ["Entity", META.entities], group: ["Investment Group", META.groups], type: ["Investment Type", META.types],
      bank: ["Bank / Institution", META.banks], fund: ["Fund / Security", META.funds],
    };
    const ctrl = {};
    fields.forEach((f) => {
      const div = document.createElement("div"); host.appendChild(div);
      ctrl[f] = makeMS(div, defs[f][0], defs[f][1].map((x) => ({ value: x.id, label: x.name })), onChange);
    });
    return { qs: () => fields.map((f) => { const v = ctrl[f].get(); return v.length ? f + "=" + v.join(",") : ""; }).filter(Boolean).join("&"), ctrl };
  }

  function fillDateSelect(sel, selected) {
    const dates = META.dates.map((d) => d.as_on_date).reverse();
    sel.innerHTML = dates.map((d) => '<option value="' + d + '">' + dmy(d) + "</option>").join("");
    if (selected && dates.includes(selected)) sel.value = selected;
  }
  function emptyState(el) {
    el.innerHTML = '<div class="empty"><svg viewBox="0 0 24 24"><path d="M3 20h18"/><rect x="5" y="11" width="3.5" height="7" rx="1"/><rect x="10.5" y="6" width="3.5" height="12" rx="1"/><rect x="16" y="9" width="3.5" height="9" rx="1"/></svg>' +
      "<h2>No data uploaded yet</h2><p>" + (META.is_admin ? 'Go to <a href="/uploads">Upload Data</a> and upload the first monthly Excel file.' : "Please ask the administrator to upload the first monthly file.") + "</p></div>";
  }

  /* Export buttons: <div id="exports" data-path="/export/xyz"> with <a data-export="xlsx|pdf">.
     The link is built at click time from the current filters + chosen amount unit. */
  function bindExports(getQs) {
    const box = document.getElementById("exports");
    if (!box) return;
    box.addEventListener("click", (e) => {
      const a = e.target.closest("a[data-export]");
      if (!a) return;
      const qs = (getQs() || "") + (getQs() ? "&" : "") + "unit=" + getUnit();
      a.href = box.dataset.path + "." + a.dataset.export + "?" + qs;
    });
  }

  window.IT = { bindExports, api, amt, full, compact, inr, dmy, mon, pct, deltaHTML, esc, getUnit, mountUnitToggle, PALETTE, OTHER, POS, NEG, seqBlues,
    loadMeta, meta: () => META, colorFor, foldOthers, drawChart, GRID, moneyTip, legendHTML, makeMS, buildFilters, fillDateSelect, emptyState, csrf };
})();
