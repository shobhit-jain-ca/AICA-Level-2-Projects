(async function () {
  const { api, amt, dmy, esc } = IT;
  const meta = await IT.loadMeta();
  const out = document.getElementById("out");
  if (!meta.dates.length) { const ex = document.getElementById("exports"); if (ex) ex.remove(); document.getElementById("sform").remove(); IT.emptyState(out); return; }

  const q = document.getElementById("q"), sel = document.getElementById("asOn"), closed = document.getElementById("closed");
  IT.fillDateSelect(sel, meta.dates[meta.dates.length - 1].as_on_date);
  sel.insertAdjacentHTML("beforeend", '<option value="all">All dates (history)</option>');
  const params = new URLSearchParams(location.search);
  q.value = params.get("q") || "";
  if (params.get("date")) sel.value = params.get("date");
  if (params.get("closed") === "1") closed.checked = true;

  let last = null, sort = { k: null, dir: 1 };
  IT.mountUnitToggle(() => render());
  const query = () => "q=" + encodeURIComponent(q.value.trim()) + "&date=" + sel.value + (closed.checked ? "&closed=1" : "");
  IT.bindExports(() => query());
  document.getElementById("sform").addEventListener("submit", (e) => { e.preventDefault(); run(); });
  sel.addEventListener("change", () => q.value.trim() && run());
  closed.addEventListener("change", () => q.value.trim() && run());

  const tips = '<div class="card tips"><h2>How to search</h2>Type one or more words &ndash; every word must match somewhere in the holding.<br>' +
    'You can search by <b>bank or institution</b> (<code>HDFC</code>), <b>account / folio number</b> (<code>50300</code> &ndash; spaces and dashes are ignored), ' +
    '<b>fund or security</b>, <b>investment type</b> (<code>fixed deposit</code>), <b>entity</b>, joint holder, nominee, contact person, remarks and more.<br>' +
    'Example: <code>BBB hdfc fixed</code> finds the HDFC fixed deposits of BBB. Choose <b>All dates</b> to see how a holding appeared in earlier months.</div>';

  async function run() {
    const text = q.value.trim();
    history.replaceState(null, "", "/search?" + query());
    const tq = document.getElementById("topQ"); if (tq) tq.value = text;
    if (!text) { last = null; out.innerHTML = tips; return; }
    out.innerHTML = '<p class="muted">Searching…</p>';
    try { last = await api("/api/search?" + query()); } catch (e) { out.innerHTML = '<div class="flash error">' + esc(e.message) + "</div>"; return; }
    render();
  }

  // highlight search words without breaking HTML: split the raw text, escape each piece
  function hl(text) {
    if (text === null || text === undefined || text === "") return "–";
    const s = String(text), toks = (last && last.tokens) || [];
    if (!toks.length) return esc(s);
    const re = new RegExp("(" + toks.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "ig");
    return s.split(re).map((p, i) => (i % 2 ? "<mark>" + esc(p) + "</mark>" : esc(p))).join("");
  }

  const nameOf = (r) => r.fund || r.bank || r.managed_by || "–";
  function details(r) {
    const f = (l, v) => (v ? '<div><span class="muted small">' + l + "</span><br>" + hl(v) + "</div>" : "");
    return '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px 18px;padding:4px 0">' +
      f("Group", r.grp) + f("Bank / institution", r.fund ? r.bank : "") + f("Joint holder(s)", r.joint_holder) + f("Nominee", r.nominee) + f("Managed by", r.managed_by) +
      f("Start / issue date", r.start_date ? dmy(r.start_date) : "") + f("Maturity amount", r.maturity_amount !== null && r.maturity_amount !== undefined ? amt(r.maturity_amount, { dec: 0 }) : "") +
      f("Auto renewal", r.auto_renewal) + f("Quantity / units", r.quantity !== null && r.quantity !== undefined ? String(r.quantity) : "") +
      f("Contact person", r.contact_person) + f("Contact no.", r.contact_no) + f("Contact email", r.contact_email) + f("Remarks", r.remarks) + "</div>";
  }

  function render() {
    if (!last) return;
    const allDates = last.date === null;
    let rows = last.rows.map((r) => Object.assign({ name: nameOf(r) }, r));
    if (sort.k) rows.sort((a, b) => { const x = a[sort.k], y = b[sort.k]; if (x === y) return 0; if (x === null || x === undefined) return 1; if (y === null || y === undefined) return -1; return (x > y ? 1 : -1) * sort.dir; });
    if (!rows.length) { out.innerHTML = '<div class="card"><p style="margin:0">Nothing matched <b>' + esc(last.q) + "</b>" + (allDates ? "" : " as on " + dmy(last.date)) + ".</p><p class='muted small' style='margin:8px 0 0'>Try fewer or shorter words, or choose <b>All dates</b>.</p></div>"; return; }
    let head = "<b>" + rows.length + "</b> holding" + (rows.length === 1 ? "" : "s") + " found" + (allDates ? " across all dates" : " as on " + dmy(last.date));
    if (!allDates && last.total !== null) head += " · total active value <b>" + amt(last.total) + "</b>";
    if (last.truncated) head += ' · <span class="neg">showing the first ' + rows.length + " &ndash; add more words to narrow down</span>";
    const COLS = (allDates ? [["as_on_date", "As on", false]] : []).concat([
      ["entity", "Entity", false], ["type", "Type", false], ["name", "Bank / Fund / Security", false], ["account_no", "Account / Folio No.", false],
      ["current_value", "Current value", true], ["maturity_date", "Maturity", false], ["interest_rate", "Rate", true]]);
    let h = "<thead><tr>" + COLS.map((c) => "<th class='" + (c[2] ? "r" : "") + "' data-k='" + c[0] + "' style='cursor:pointer'>" + c[1] + (sort.k === c[0] ? (sort.dir > 0 ? " ▲" : " ▼") : "") + "</th>").join("") + "</tr></thead><tbody>";
    rows.forEach((r, i) => {
      const bank = r.fund && r.bank ? '<div class="muted small">' + hl(r.bank) + "</div>" : "";
      h += "<tr data-i='" + i + "' style='cursor:pointer;" + (r.status === "Closed" ? "opacity:.55" : "") + "'>" +
        (allDates ? "<td class='nowrap'>" + dmy(r.as_on_date) + "</td>" : "") +
        "<td>" + hl(r.entity) + (r.status === "Closed" ? ' <span class="badge grey">Closed</span>' : "") + "</td><td>" + hl(r.type) + "</td><td>" + hl(r.fund || r.bank || r.managed_by) + bank + "</td><td>" + hl(r.account_no) + "</td>" +
        "<td class='num'><b>" + amt(r.current_value, { dec: 0 }) + "</b></td><td class='nowrap'>" + (r.maturity_date ? dmy(r.maturity_date) : "–") + "</td><td class='num'>" + (r.interest_rate === null || r.interest_rate === undefined ? "–" : r.interest_rate.toFixed(2) + "%") + "</td></tr>";
      h += "<tr id='d" + i + "' style='display:none'><td colspan='" + COLS.length + "' style='background:var(--bg-2)'>" + details(r) + "</td></tr>";
    });
    out.innerHTML = '<div class="muted" style="margin-bottom:8px">' + head + '</div><div class="tablewrap" style="max-height:72vh"><table class="t" id="tbl">' + h + "</tbody></table></div>" +
      '<p class="muted small">Click a row for full details.</p>';
    document.getElementById("tbl").addEventListener("click", (e) => {
      const th = e.target.closest("th[data-k]");
      if (th) { const k = th.dataset.k; sort = { k, dir: sort.k === k ? -sort.dir : 1 }; render(); return; }
      const tr = e.target.closest("tr[data-i]");
      if (tr) { const d = document.getElementById("d" + tr.dataset.i); d.style.display = d.style.display === "none" ? "" : "none"; }
    });
  }

  if (q.value.trim()) run(); else out.innerHTML = tips;
})();
