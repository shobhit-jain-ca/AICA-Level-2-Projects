(async function () {
  const { api, amt, full, dmy, mon, esc } = IT;
  const meta = await IT.loadMeta();
  const body = document.getElementById("body");
  if (!meta.dates.length) { const ex = document.getElementById("exports"); if (ex) ex.remove(); document.getElementById("filters").remove(); document.querySelectorAll(".pagehead .field").forEach((f) => f.remove()); const b = document.createElement("div"); body.parentNode.appendChild(b); IT.emptyState(b); return; }
  const sel = document.getElementById("asOn"), days = document.getElementById("days");
  IT.fillDateSelect(sel, meta.dates[meta.dates.length - 1].as_on_date);
  const filters = IT.buildFilters(document.getElementById("filters"), ["entity", "type", "bank"], load);
  sel.addEventListener("change", load); days.addEventListener("change", load);
  let last = null;
  IT.mountUnitToggle(() => render());
  IT.bindExports(() => "date=" + sel.value + "&days=" + days.value + (filters.qs() ? "&" + filters.qs() : ""));

  async function load() {
    last = await api("/api/maturities?date=" + sel.value + "&days=" + days.value + (filters.qs() ? "&" + filters.qs() : ""));
    body.style.display = ""; render();
  }
  function badge(d) {
    if (d < 0) return '<span class="badge red">Matured ' + (-d) + " days ago</span>";
    if (d === 0) return '<span class="badge red">Today</span>';
    if (d <= 30) return '<span class="badge red">' + d + " days</span>";
    return '<span class="badge">' + d + " days</span>";
  }
  function render() {
    if (!last) return;
    const rows = last.rows, today = meta.today;
    document.getElementById("note").innerHTML = '<div class="flash warn">Figures are from the file as on <b>' + dmy(last.date) + "</b>; days are counted from today (" + dmy(today) + "). Items marked “Matured” may already have been renewed or paid out – confirm in the next upload.</div>";
    const L = last.ladder, cols = L.labels.map((l) => IT.POS);
    const labels = L.labels.map(mon), vals = L.values.slice();
    if (L.past_due > 0) { labels.unshift("Past due"); vals.unshift(L.past_due); cols.unshift(IT.NEG); }
    IT.drawChart("cLadder", { type: "bar", data: { labels, datasets: [{ label: "Value", data: vals, backgroundColor: cols }] },
      options: { scales: { x: { grid: { display: false } }, y: { grid: IT.GRID, ticks: { callback: IT.compact } } }, plugins: { tooltip: IT.moneyTip } } });
    const past = rows.filter((r) => r.days_left < 0), fut = rows.filter((r) => r.days_left >= 0);
    const sum = (a, k) => a.reduce((s, r) => s + (r[k] || 0), 0);
    document.getElementById("sum").innerHTML =
      '<div class="grid" style="grid-template-columns:1fr 1fr;gap:12px">' +
      '<div><div class="muted small">In window (upcoming)</div><div style="font-size:22px;font-weight:700">' + fut.length + '</div><div>' + amt(sum(fut, "current_value")) + "</div></div>" +
      '<div><div class="muted small">Past maturity date (verify)</div><div style="font-size:22px;font-weight:700;color:var(--red)">' + past.length + '</div><div>' + amt(sum(past, "current_value")) + "</div></div></div>" +
      '<p class="muted small" style="margin-top:14px">Maturity amount of listed items: <b>' + amt(sum(rows, "maturity_amount")) + "</b> (where provided).</p>";
    let h = "<thead><tr><th>Maturity date</th><th>When</th><th>Entity</th><th>Type</th><th>Bank / Fund</th><th>Account no.</th><th class='r'>Current value</th><th class='r'>Maturity amount</th><th class='r'>Rate</th><th>Auto-renew</th></tr></thead><tbody>";
    if (!rows.length) h += "<tr><td colspan='10' class='muted' style='text-align:center;padding:24px'>Nothing matures in this window.</td></tr>";
    rows.forEach((r) => {
      h += "<tr><td class='nowrap'>" + dmy(r.maturity_date) + "</td><td>" + badge(r.days_left) + "</td><td>" + esc(r.entity) + "</td><td>" + esc(r.type) + "</td><td>" + esc(r.name) + "</td><td>" + esc(r.account_no || "–") + "</td>" +
        "<td class='num'>" + amt(r.current_value) + "</td><td class='num'>" + (r.maturity_amount === null ? "–" : amt(r.maturity_amount)) + "</td><td class='num'>" + (r.interest_rate === null ? "–" : r.interest_rate.toFixed(2) + "%") + "</td><td>" + esc(r.auto_renewal || "–") + "</td></tr>";
    });
    document.getElementById("tbl").innerHTML = h + "</tbody>";
  }
  await load();
})();
