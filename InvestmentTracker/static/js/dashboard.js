(async function () {
  const { api, amt, full, dmy, mon, pct, deltaHTML, esc } = IT;
  const meta = await IT.loadMeta();
  const body = document.getElementById("body"), sub = document.getElementById("subline");
  if (!meta.dates.length) { const ex = document.getElementById("exports"); if (ex) ex.remove();
    document.getElementById("filters").remove();
    document.querySelector(".pagehead .field").remove();
    sub.textContent = "";
    const box = document.createElement("div"); body.parentNode.appendChild(box); IT.emptyState(box);
    return;
  }

  const sel = document.getElementById("asOn");
  IT.fillDateSelect(sel, meta.dates[meta.dates.length - 1].as_on_date);
  const filters = IT.buildFilters(document.getElementById("filters"), ["entity", "group", "type"], load);
  sel.addEventListener("change", load);
  IT.mountUnitToggle(() => render(last));
  IT.bindExports(() => "date=" + sel.value + (filters.qs() ? "&" + filters.qs() : ""));
  let last = null, lastMatrix = null;

  async function load() {
    const qs = "date=" + sel.value + (filters.qs() ? "&" + filters.qs() : "");
    [last, lastMatrix] = await Promise.all([api("/api/dashboard?" + qs), api("/api/matrix?" + qs)]);
    render(last);
  }

  function kpi(cls, label, value, foot) {
    return '<div class="card kpi ' + cls + '"><div class="label">' + label + '</div><div class="value">' + value + '</div><div class="delta">' + (foot || "&nbsp;") + "</div></div>";
  }

  function render(d) {
    if (!d || d.empty) return;
    body.style.display = "";
    sub.textContent = "Position as on " + dmy(d.date) + " · uploaded " + dmy(d.uploaded_at) + " by " + d.uploaded_by;

    // ---- KPIs
    const k = [];
    k.push(kpi("accent", "Total investments", amt(d.total),
      d.prev_date ? deltaHTML(d.change, d.change_pct) + ' <span class="muted small">vs ' + dmy(d.prev_date) + "</span>" : '<span class="muted small">First period – nothing to compare yet</span>'));
    if (d.market.n > 0) {
      const g = d.market.gain, cls = g >= 0 ? "pos" : "neg";
      k.push(kpi("accent2", "Gain / (loss) – market-linked", '<span class="' + cls + '">' + amt(g) + "</span>",
        '<span class="' + cls + '">' + pct(d.market.gain_pct, true) + '</span> <span class="muted small">on ' + amt(d.market.invested) + " cost · " + d.market.n + " of " + d.market.total_n + " holdings</span>"));
    } else {
      k.push(kpi("accent2", "Gain / (loss) – market-linked", '<span class="muted">Not available</span>', '<span class="muted small">Fill “Invested Amount” in the Excel for funds, shares, PMS, bonds</span>'));
    }
    k.push(kpi("accent", "Holdings", IT.inr(d.holdings_count), '<span class="muted small">' + d.by_entity.length + " entities · " + d.by_type.length + " investment types</span>"));
    k.push(kpi("accent2", "Avg. interest rate", d.avg_rate !== null ? d.avg_rate.toFixed(2) + "%" : "–",
      '<span class="muted small">value-weighted, ' + d.avg_rate_n + " interest-bearing holdings</span>"));
    document.getElementById("kpis").innerHTML = k.join("");

    // ---- Allocation doughnut (by group, fold beyond palette)
    const grp = IT.foldOthers("group", d.by_group.filter((x) => x.v > 0).map((x) => ({ label: x.label, v: x.v })), "v");
    const gcol = (g) => (g._other ? IT.OTHER : IT.colorFor("group", g.label));
    const tot = grp.reduce((s, x) => s + x.v, 0) || 1;
    IT.drawChart("cAlloc", {
      type: "doughnut",
      data: { labels: grp.map((g) => g.label), datasets: [{ data: grp.map((g) => g.v), backgroundColor: grp.map(gcol), borderColor: "#fff", borderWidth: 2, hoverOffset: 6 }] },
      options: { cutout: "62%", plugins: { tooltip: { callbacks: { label: (c) => " " + full(c.parsed) + "  (" + (c.parsed / tot * 100).toFixed(1) + "%)",
        afterLabel: (c) => (grp[c.dataIndex].members ? "Includes: " + grp[c.dataIndex].members.join(", ") : "") } } } },
      plugins: [{ id: "centerText", afterDraw(ch) {
        const { ctx, chartArea: a } = ch; ctx.save(); ctx.textAlign = "center"; ctx.fillStyle = "#7b8798"; ctx.font = "12px Segoe UI, sans-serif";
        const cx = (a.left + a.right) / 2, cy = (a.top + a.bottom) / 2; ctx.fillText("Total", cx, cy - 8);
        ctx.fillStyle = "#16202e"; ctx.font = "700 17px Segoe UI, sans-serif"; ctx.fillText(IT.compact(tot), cx, cy + 14); ctx.restore(); } }],
    });
    IT.legendHTML(document.getElementById("lAlloc"), grp.map((g) => ({ color: gcol(g), label: g.label, extra: (g.v / tot * 100).toFixed(1) + "%" })));

    // ---- Trend (total)
    const t = d.trend, labels = t.dates.map(mon);
    IT.drawChart("cTrend", {
      type: "line",
      data: { labels, datasets: [{ label: "Total investments", data: t.total, borderColor: "#2a78d6", backgroundColor: "rgba(42,120,214,.10)", fill: true, tension: .25, pointBackgroundColor: "#fff", pointBorderColor: "#2a78d6", pointBorderWidth: 2, pointRadius: 4 }] },
      options: { interaction: { mode: "index", intersect: false }, scales: { x: { grid: { display: false } }, y: { grid: IT.GRID, ticks: { callback: IT.compact }, beginAtZero: false } }, plugins: { tooltip: IT.moneyTip } },
    });

    // ---- Stacked mix over time (fold)
    const keep = [], rest = [];
    t.groups.forEach((g) => (IT.colorFor("group", g.name) !== IT.OTHER ? keep : rest).push(g));
    const stackSeries = keep.map((g) => ({ label: g.name, values: g.values, color: IT.colorFor("group", g.name) }));
    if (rest.length) stackSeries.push({ label: "Other (" + rest.length + ")", values: t.dates.map((_, i) => rest.reduce((s, r) => s + r.values[i], 0)), color: IT.OTHER });
    IT.drawChart("cStack", {
      type: "bar",
      data: { labels, datasets: stackSeries.map((s) => ({ label: s.label, data: s.values, backgroundColor: s.color, borderColor: "#fff", borderWidth: 1.5, borderRadius: 0 })) },
      options: { interaction: { mode: "index", intersect: false }, scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, grid: IT.GRID, ticks: { callback: IT.compact } } }, plugins: { tooltip: IT.moneyTip } },
    });
    IT.legendHTML(document.getElementById("lStack"), stackSeries.map((s) => ({ color: s.color, label: s.label })));

    // ---- By entity (horizontal bars; prior period as grey reference)
    const ent = d.by_entity;
    const ds = [{ label: dmy(d.date), data: ent.map((e) => e.v), backgroundColor: "#2a78d6" }];
    if (d.prev_date) ds.unshift({ label: dmy(d.prev_date), data: ent.map((e) => e.prev || 0), backgroundColor: "#b9d3f3" });
    IT.drawChart("cEntity", {
      type: "bar", data: { labels: ent.map((e) => e.label), datasets: ds },
      options: { indexAxis: "y", interaction: { mode: "index", intersect: false }, scales: { x: { grid: IT.GRID, ticks: { callback: IT.compact } }, y: { grid: { display: false } } }, plugins: { tooltip: IT.moneyTip } },
    });
    IT.legendHTML(document.getElementById("lEntity"), ds.slice().reverse().map((x) => ({ color: x.backgroundColor, label: x.label })));

    renderMatrix();
    // ---- Movement by type
    let h = "<thead><tr><th>Investment type</th><th class='r'>Current</th><th class='r'>Previous</th><th class='r'>Change</th></tr></thead><tbody>";
    d.by_type.forEach((r) => {
      const ch = r.prev !== null && r.prev !== undefined ? r.v - r.prev : (d.prev_date ? r.v : null);
      const p = r.prev ? ((r.v - r.prev) / r.prev) * 100 : null;
      h += "<tr><td>" + esc(r.label) + "</td><td class='num'>" + amt(r.v) + "</td><td class='num'>" + (d.prev_date ? amt(r.prev || 0) : "–") + "</td><td class='num'>" + deltaHTML(ch, p) + "</td></tr>";
    });
    h += "<tr class='total'><td>Total</td><td class='num'>" + amt(d.total) + "</td><td class='num'>" + (d.prev_total !== null ? amt(d.prev_total) : "–") + "</td><td class='num'>" + deltaHTML(d.change, d.change_pct) + "</td></tr></tbody>";
    document.getElementById("typeTable").innerHTML = h;

    // ---- Top holdings
    let t2 = "<thead><tr><th>#</th><th>Holding</th><th>Entity</th><th class='r'>Value</th></tr></thead><tbody>";
    d.top.forEach((r, i) => { t2 += "<tr><td>" + (i + 1) + "</td><td>" + esc(r.name) + '<div class="muted small">' + esc(r.type) + (r.account_no ? " · " + esc(r.account_no) : "") + "</div></td><td>" + esc(r.entity) + "</td><td class='num'>" + amt(r.v) + "</td></tr>"; });
    document.getElementById("topTable").innerHTML = t2 + "</tbody>";
  }

  function renderMatrix() {
    const m = lastMatrix; if (!m || m.empty) return;
    document.getElementById("matrixDate").textContent = "· as on " + dmy(m.date);
    let h = "<thead><tr><th class='sticky'>Investment type</th>" + m.entities.map((e) => "<th class='r'>" + esc(e) + "</th>").join("") + "<th class='r'>Total</th></tr></thead><tbody>";
    m.rows.forEach((r) => { h += "<tr><td class='sticky'>" + esc(r.type) + "</td>" + r.values.map((v) => "<td class='num'>" + (v ? amt(v, { sym: false }) : "–") + "</td>").join("") + "<td class='num'><b>" + amt(r.total, { sym: false }) + "</b></td></tr>"; });
    h += "<tr class='total'><td class='sticky'>Total</td>" + m.col_totals.map((v) => "<td class='num'>" + amt(v, { sym: false }) + "</td>").join("") + "<td class='num'>" + amt(m.grand_total, { sym: false }) + "</td></tr></tbody>";
    document.getElementById("matrix").innerHTML = h;
  }

  await load();
})();
