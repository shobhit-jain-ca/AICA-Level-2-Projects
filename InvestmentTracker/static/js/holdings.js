(async function () {
  const { api, amt, dmy, pct, esc } = IT;
  const meta = await IT.loadMeta();
  const body = document.getElementById("body");
  if (!meta.dates.length) { const ex = document.getElementById("exports"); if (ex) ex.remove(); document.getElementById("filters").remove(); document.querySelector(".pagehead .field").remove(); const b = document.createElement("div"); body.parentNode.appendChild(b); IT.emptyState(b); return; }
  const sel = document.getElementById("asOn");
  IT.fillDateSelect(sel, meta.dates[meta.dates.length - 1].as_on_date);
  const filtersHost = document.getElementById("filters");
  const holder = document.createElement("div"); holder.style.display = "contents"; filtersHost.prepend(holder);
  const filters = IT.buildFilters(holder, ["entity", "group", "type", "bank", "fund"], load);
  const q = document.getElementById("q"), closed = document.getElementById("closed");
  let rows = [], sort = { k: null, dir: 1 }, timer;
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 300); });
  closed.addEventListener("change", load); sel.addEventListener("change", load);
  IT.mountUnitToggle(() => render());
  IT.bindExports(() => qs());

  function qs() { return "date=" + sel.value + (filters.qs() ? "&" + filters.qs() : "") + (q.value ? "&q=" + encodeURIComponent(q.value) : "") + (closed.checked ? "&closed=1" : ""); }
  async function load() {
    const r = await api("/api/holdings?" + qs());
    rows = r.rows; body.style.display = "";
    render();
  }
  const COLS = [
    ["entity", "Entity", false], ["type", "Type", false], ["name", "Bank / Fund / Security", false], ["account_no", "Account / Folio No.", false],
    ["invested_amount", "Invested", true], ["current_value", "Current value", true], ["gain", "Gain / (loss)", true],
    ["maturity_date", "Maturity", false], ["interest_rate", "Rate", true], ["last_updated", "Last updated", false],
  ];
  const nameOf = (r) => r.fund || r.bank || "–";
  function render() {
    let list = rows.map((r) => Object.assign({ name: nameOf(r) }, r));
    if (sort.k) list.sort((a, b) => { const x = a[sort.k], y = b[sort.k]; if (x === y) return 0; if (x === null || x === undefined) return 1; if (y === null || y === undefined) return -1; return (x > y ? 1 : -1) * sort.dir; });
    const total = list.filter((r) => r.status === "Active").reduce((s, r) => s + r.current_value, 0);
    document.getElementById("count").innerHTML = "<b>" + list.length + "</b> holdings · total active value <b>" + amt(total) + "</b>";
    let h = "<thead><tr>" + COLS.map((c) => "<th class='" + (c[2] ? "r" : "") + (c[0] === "entity" ? " sticky" : "") + "' data-k='" + c[0] + "' style='cursor:pointer'>" + c[1] + (sort.k === c[0] ? (sort.dir > 0 ? " ▲" : " ▼") : "") + "</th>").join("") + "</tr></thead><tbody>";
    list.forEach((r, i) => {
      const bank = r.fund && r.bank ? '<div class="muted small">' + esc(r.bank) + "</div>" : "";
      const gain = r.gain === null ? "–" : '<span class="' + (r.gain >= 0 ? "pos" : "neg") + '">' + (r.gain >= 0 ? "▲ " : "▼ ") + amt(Math.abs(r.gain), { dec: 0 }) + "</span>";
      let mat = r.maturity_date ? dmy(r.maturity_date) : "–";
      h += "<tr data-i='" + i + "' style='cursor:pointer;" + (r.status === "Closed" ? "opacity:.55" : "") + "'>" +
        "<td class='sticky'>" + esc(r.entity) + (r.status === "Closed" ? ' <span class="badge grey">Closed</span>' : "") + "</td>" +
        "<td>" + esc(r.type) + "</td><td>" + esc(nameOf(r)) + bank + "</td><td>" + esc(r.account_no || "–") + "</td>" +
        "<td class='num'>" + (r.invested_amount === null ? "–" : amt(r.invested_amount, { dec: 0 })) + "</td><td class='num'><b>" + amt(r.current_value, { dec: 0 }) + "</b></td><td class='num'>" + gain + "</td>" +
        "<td class='nowrap'>" + mat + "</td><td class='num'>" + (r.interest_rate === null ? "–" : r.interest_rate.toFixed(2) + "%") + "</td>" +
        "<td class='nowrap'>" + (r.last_updated ? dmy(r.last_updated) : "–") + (r.stale ? ' <span class="badge red" title="Not updated for over 2 months before the As-On date">stale</span>' : "") + "</td></tr>";
      h += "<tr class='detail' id='d" + i + "' style='display:none'><td colspan='" + COLS.length + "' style='background:var(--bg-2)'>" + details(r) + "</td></tr>";
    });
    document.getElementById("tbl").innerHTML = h + "</tbody>";
  }
  function details(r) {
    const f = (l, v) => (v ? '<div><span class="muted small">' + l + "</span><br>" + esc(v) + "</div>" : "");
    return '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px 18px;padding:4px 0">' +
      f("Group", r.grp) + f("Joint holder(s)", r.joint_holder) + f("Nominee", r.nominee) + f("Managed by", r.managed_by) + f("Start / issue date", r.start_date ? dmy(r.start_date) : "") +
      f("Maturity amount", r.maturity_amount !== null ? amt(r.maturity_amount, { dec: 0 }) : "") + f("Auto renewal", r.auto_renewal) + f("Quantity / units", r.quantity !== null ? String(r.quantity) : "") +
      f("Contact person", r.contact_person) + f("Contact no.", r.contact_no) + f("Contact email", r.contact_email) + f("Remarks", r.remarks) + "</div>";
  }
  document.getElementById("tbl").addEventListener("click", (e) => {
    const th = e.target.closest("th[data-k]");
    if (th) { const k = th.dataset.k; sort = { k, dir: sort.k === k ? -sort.dir : 1 }; render(); return; }
    const tr = e.target.closest("tr[data-i]");
    if (tr) { const d = document.getElementById("d" + tr.dataset.i); d.style.display = d.style.display === "none" ? "" : "none"; }
  });
  await load();
})();
