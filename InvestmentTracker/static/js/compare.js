(async function () {
  const { api, amt, full, dmy, mon, pct, deltaHTML, esc } = IT;
  const meta = await IT.loadMeta();
  const body = document.getElementById("body");
  if (meta.dates.length === 0) { const ex = document.getElementById("exports"); if (ex) ex.remove();
    document.getElementById("topControls").remove(); document.getElementById("filters").remove();
    const box = document.createElement("div"); body.parentNode.appendChild(box); IT.emptyState(box); return;
  }
  const allDates = meta.dates.map((d) => d.as_on_date);
  const periods = IT.makeMS(document.getElementById("fPeriods"), "Periods (As-on dates)", allDates.slice().reverse().map((d) => ({ value: d, label: dmy(d) })), load);
  const filters = IT.buildFilters(document.getElementById("filters"), ["entity", "group", "type", "bank", "fund"], load);
  const by = document.getElementById("by");
  const momBox = document.getElementById("mom");
  let data = null;

  function pick(n) { periods.set(n === 0 ? allDates : allDates.slice(-n)); load(); }
  pick(Math.min(3, allDates.length));
  document.getElementById("quick").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) pick(+b.dataset.n); });
  by.addEventListener("change", load);
  momBox.addEventListener("change", () => render());
  IT.mountUnitToggle(() => render());
  IT.bindExports(() => qs());

  function qs() {
    const p = periods.get().sort();
    return "dates=" + p.join(",") + "&by=" + by.value + (filters.qs() ? "&" + filters.qs() : "");
  }
  async function load() {
    const sel = periods.get();
    if (sel.length < 1) { body.style.display = "none"; return; }
    data = await api("/api/compare?" + qs());
    render();
  }

  function rankColor(dim, label, rankIdx) {
    if (dim === "holding") return rankIdx < IT.PALETTE.length ? IT.PALETTE[rankIdx] : IT.OTHER;
    return IT.colorFor(dim, label);
  }

  function render() {
    if (!data) return;
    body.style.display = "";
    const d = data, ds = d.dates, n = ds.length, last = ds[n - 1], first = ds[0];
    const msg = document.getElementById("msg");
    msg.innerHTML = n < 2 ? '<div class="flash warn">Select at least two periods to see a comparison. Only one period is shown below.</div>' : "";
    if (!d.rows.length) { body.querySelectorAll(".card, .kpis").forEach((c) => (c.style.display = "none")); msg.innerHTML += '<div class="empty">No holdings match these filters for the selected periods.</div>'; return; }
    body.querySelectorAll(".card, .kpis").forEach((c) => (c.style.display = ""));

    // ---- KPIs
    const tf = d.totals[first], tl = d.totals[last];
    document.getElementById("kpis").innerHTML =
      '<div class="card kpi accent"><div class="label">' + dmy(first) + '</div><div class="value">' + amt(tf) + '</div><div class="delta muted small">First period</div></div>' +
      '<div class="card kpi accent"><div class="label">' + dmy(last) + '</div><div class="value">' + amt(tl) + '</div><div class="delta muted small">Latest period</div></div>' +
      '<div class="card kpi accent2"><div class="label">Change</div><div class="value">' + (n > 1 ? deltaHTML(d.total_change, null).replace(/ \(.*\)/, "") : "–") + '</div><div class="delta">' + (n > 1 && d.total_pct !== null ? '<span class="' + (d.total_change >= 0 ? "pos" : "neg") + '">' + pct(d.total_pct, true) + "</span>" : "&nbsp;") + "</div></div>" +
      '<div class="card kpi accent2"><div class="label">' + esc(d.by_title) + " items</div><div class=\"value\">" + d.rows.length + '</div><div class="delta muted small">' + n + " period" + (n > 1 ? "s" : "") + " selected</div></div>";

    // ---- rank rows by latest value (fallback: first)
    const val = (r, dt) => r.values[dt] || 0;
    const ranked = d.rows.slice().sort((a, b) => (val(b, last) || val(b, first)) - (val(a, last) || val(a, first)));
    const TOP = 10;
    const topRows = ranked.slice(0, TOP), restRows = ranked.slice(TOP);
    const cats = topRows.map((r) => ({ label: r.label, values: r.values }));
    if (restRows.length) cats.push({ label: "Other (" + restRows.length + ")", values: Object.fromEntries(ds.map((x) => [x, restRows.reduce((s, r) => s + val(r, x), 0)])), other: true });

    document.getElementById("t1").textContent = d.by_title + "-wise: period by period";
    document.getElementById("t2").textContent = "Trend by " + d.by_title.toLowerCase();

    // ---- chart 1: categories on x, periods as series (sequential blues, latest darkest)
    const blues = IT.seqBlues(n);
    const useBars = n <= 8;
    const horizontal = cats.length > 6;
    const wrap = (s) => (s.length > 26 ? s.slice(0, 25) + "…" : s);
    IT.drawChart("cBars", {
      type: "bar",
      data: { labels: cats.map((c) => wrap(c.label)), datasets: ds.map((x, i) => ({ label: dmy(x), data: cats.map((c) => c.values[x] || 0), backgroundColor: useBars ? blues[i] : blues[i], maxBarThickness: horizontal ? 16 : 30 })) },
      options: { indexAxis: horizontal ? "y" : "x", interaction: { mode: "index", intersect: false },
        scales: horizontal ? { x: { grid: IT.GRID, ticks: { callback: IT.compact } }, y: { grid: { display: false } } } : { x: { grid: { display: false } }, y: { grid: IT.GRID, ticks: { callback: IT.compact } } },
        plugins: { tooltip: { callbacks: { title: (it) => cats[it[0].dataIndex].label, label: (c) => " " + c.dataset.label + ": " + full(horizontal ? c.parsed.x : c.parsed.y) } } } },
    });
    IT.legendHTML(document.getElementById("l1"), ds.map((x, i) => ({ color: blues[i], label: dmy(x) })));

    // ---- chart 2: lines per category across periods
    const lineCats = cats.slice(0, 8);
    const lineSets = lineCats.map((c, i) => {
      const col = c.other ? IT.OTHER : rankColor(d.by, c.label, i);
      return { label: c.label, data: ds.map((x) => c.values[x] || 0), borderColor: col, backgroundColor: col, tension: .2, pointBackgroundColor: "#fff", pointBorderColor: col, pointBorderWidth: 2 };
    });
    if (d.rows.length > 1) lineSets.push({ label: "Total", data: ds.map((x) => d.totals[x]), borderColor: "#173c82", backgroundColor: "#173c82", borderDash: [6, 4], borderWidth: 2.5, pointRadius: 3, tension: .2 });
    IT.drawChart("cLines", {
      type: "line", data: { labels: ds.map(mon), datasets: lineSets },
      options: { interaction: { mode: "index", intersect: false }, scales: { x: { grid: { display: false } }, y: { grid: IT.GRID, ticks: { callback: IT.compact } } },
        plugins: { tooltip: { callbacks: { label: (c) => " " + c.dataset.label + ": " + full(c.parsed.y) } } } },
    });
    IT.legendHTML(document.getElementById("l2"), lineSets.map((s) => ({ color: s.borderColor, label: s.label })));

    // ---- chart 3: change first -> last
    const chg = d.rows.slice().sort((a, b) => Math.abs(b.change) - Math.abs(a.change)).slice(0, 14).sort((a, b) => b.change - a.change);
    document.getElementById("chgBox").style.height = Math.max(180, 40 + chg.length * 30) + "px";
    IT.drawChart("cChange", {
      type: "bar", data: { labels: chg.map((r) => wrap(r.label)), datasets: [{ label: "Change", data: chg.map((r) => r.change), backgroundColor: chg.map((r) => (r.change >= 0 ? IT.POS : IT.NEG)), maxBarThickness: 18 }] },
      options: { indexAxis: "y", scales: { x: { grid: IT.GRID, ticks: { callback: IT.compact } }, y: { grid: { display: false } } },
        plugins: { tooltip: { callbacks: { title: (it) => chg[it[0].dataIndex].label, label: (c) => " " + (c.parsed.x >= 0 ? "+" : "−") + full(Math.abs(c.parsed.x)).replace("₹ ", "₹ ") + (chg[c.dataIndex].pct !== null ? "  (" + pct(chg[c.dataIndex].pct, true) + ")" : "") } } } },
    });

    // ---- table
    const mom = momBox.checked;
    document.getElementById("tblTitle").textContent = "Detailed table – by " + d.by_title.toLowerCase();
    let h = "<thead><tr><th class='sticky'>" + esc(d.by_title) + "</th>" + ds.map((x) => "<th class='r'>" + dmy(x) + "</th>").join("") + "<th class='r'>Change (first → last)</th><th class='r'>Change %</th></tr></thead><tbody>";
    ranked.forEach((r) => {
      h += "<tr><td class='sticky'>" + esc(r.label) + (r.status === "new" ? ' <span class="badge">New</span>' : r.status === "exited" ? ' <span class="badge red">Exited</span>' : "") + "</td>";
      ds.forEach((x, i) => {
        const v = r.values[x];
        let cell = v === null ? '<span class="muted">–</span>' : amt(v);
        if (mom && i > 0) { const pv = r.values[ds[i - 1]] || 0, dv = (v || 0) - pv; cell += '<div class="small ' + (dv > 0 ? "pos" : dv < 0 ? "neg" : "muted") + '">' + (dv > 0 ? "▲ " : dv < 0 ? "▼ " : "• ") + amt(Math.abs(dv)) + "</div>"; }
        h += "<td class='num'>" + cell + "</td>";
      });
      h += "<td class='num'>" + (n > 1 ? deltaHTML(r.change, null) : "–") + "</td><td class='num'>" + (r.pct !== null && n > 1 ? '<span class="' + (r.pct >= 0 ? "pos" : "neg") + '">' + pct(r.pct, true) + "</span>" : "–") + "</td></tr>";
    });
    h += "<tr class='total'><td class='sticky'>Total</td>" + ds.map((x, i) => {
      let cell = amt(d.totals[x]);
      if (mom && i > 0) { const dv = d.totals[x] - d.totals[ds[i - 1]]; cell += '<div class="small ' + (dv >= 0 ? "pos" : "neg") + '">' + (dv >= 0 ? "▲ " : "▼ ") + amt(Math.abs(dv)) + "</div>"; }
      return "<td class='num'>" + cell + "</td>";
    }).join("") + "<td class='num'>" + (n > 1 ? deltaHTML(d.total_change, null) : "–") + "</td><td class='num'>" + (n > 1 && d.total_pct !== null ? pct(d.total_pct, true) : "–") + "</td></tr></tbody>";
    document.getElementById("tbl").innerHTML = h;
  }
})();
