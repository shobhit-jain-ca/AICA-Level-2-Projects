(async function () {
  const { api, esc } = IT;
  const pane = document.getElementById("pane"), tabs = document.getElementById("tabs");
  const bg = document.getElementById("modalBg"), mTitle = document.getElementById("mTitle"), mFields = document.getElementById("mFields"), mErr = document.getElementById("mErr");
  let kind = "entities", cur = null, editing = null;

  tabs.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; tabs.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b)); kind = b.dataset.k; show(); });
  document.getElementById("mCancel").addEventListener("click", () => bg.classList.remove("show"));
  bg.addEventListener("click", (e) => { if (e.target === bg) bg.classList.remove("show"); });

  async function show() {
    if (kind === "settings") return settingsPane();
    cur = await api("/api/masters/" + kind);
    const f = cur.fields.filter((x) => !x.write_only);
    let h = '<div class="card"><div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:6px"><h2 style="margin:0">' + esc(cur.title) + '</h2><div class="spacer"></div>' +
      '<button class="btn" id="addBtn">+ Add new</button></div><p class="muted small" style="margin:0 0 12px">' + esc(cur.help) + "</p>" +
      '<div class="tablewrap"><table class="t"><thead><tr>' + f.map((x) => "<th>" + esc(x.label) + "</th>").join("") +
      (kind === "users" ? "<th>Last login</th>" : "<th class='r'>Used in</th>") + "<th>Status</th><th></th></tr></thead><tbody>";
    cur.rows.forEach((r) => {
      h += "<tr" + (r.active ? "" : ' style="opacity:.55"') + ">" + f.map((x) => "<td>" + esc(cellText(x, r)) + "</td>").join("") +
        (kind === "users" ? "<td class='nowrap'>" + esc(r.last_login || "–") + "</td>" : "<td class='num'>" + (r.used === null ? "–" : r.used + " records") + "</td>") +
        "<td>" + (r.active ? '<span class="badge">Active</span>' : '<span class="badge grey">Inactive</span>') + "</td>" +
        '<td class="nowrap"><button class="btn secondary sm" data-a="edit" data-id="' + r.id + '">Edit</button> ' +
        '<button class="btn secondary sm" data-a="toggle" data-id="' + r.id + '">' + (r.active ? "Deactivate" : "Activate") + "</button>" +
        (kind !== "users" && r.used === 0 ? ' <button class="btn danger sm" data-a="del" data-id="' + r.id + '">Delete</button>' : "") + "</td></tr>";
    });
    pane.innerHTML = h + "</tbody></table></div></div>";
    document.getElementById("addBtn").addEventListener("click", () => openForm(null));
  }
  function cellText(x, r) {
    const v = r[x.k];
    if (x.type === "select") { const o = (x.options || []).find((o) => String(o.value) === String(v)); return o ? o.label : v; }
    if (x.type === "check") return v ? "Yes" : "No";
    return v === null || v === undefined ? "" : v;
  }
  pane.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-a]"); if (!b) return;
    const id = +b.dataset.id, row = cur.rows.find((r) => r.id === id);
    try {
      if (b.dataset.a === "edit") openForm(row);
      else if (b.dataset.a === "toggle") { await api("/api/masters/" + kind + "/" + id, { method: "PUT", body: { active: row.active ? 0 : 1 } }); await show(); }
      else if (b.dataset.a === "del") { if (confirm("Delete this entry permanently?")) { await api("/api/masters/" + kind + "/" + id, { method: "DELETE" }); await show(); } }
    } catch (err) { alert(err.message); }
  });

  function openForm(row) {
    editing = row; mErr.textContent = "";
    mTitle.textContent = (row ? "Edit " : "Add ") + cur.title.replace(/s$/, "");
    mFields.innerHTML = cur.fields.map((f) => {
      const v = row ? row[f.k] : (f.type === "number" ? 100 : f.type === "select" ? (f.options[0] || {}).value : "");
      let input;
      if (f.type === "select") input = '<select data-k="' + f.k + '">' + f.options.map((o) => '<option value="' + esc(o.value) + '"' + (String(o.value) === String(v) ? " selected" : "") + ">" + esc(o.label) + "</option>").join("") + "</select>";
      else if (f.type === "check") input = '<label style="display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;font-weight:500;color:var(--ink)"><input type="checkbox" data-k="' + f.k + '" style="width:auto;min-height:0"' + (v ? " checked" : "") + "> Yes</label>";
      else if (f.type === "password") input = '<input type="password" data-k="' + f.k + '" autocomplete="new-password" placeholder="' + (row ? "Leave blank to keep current" : "") + '">';
      else input = '<input type="' + (f.type === "number" ? "number" : "text") + '" data-k="' + f.k + '" value="' + esc(v === undefined || v === null ? "" : v) + '"' + (row && kind === "users" && f.k === "username" ? " disabled" : "") + ">";
      return '<div class="row"><label>' + esc(f.label) + (f.required ? " *" : "") + "</label>" + input + "</div>";
    }).join("");
    bg.classList.add("show");
    const first = mFields.querySelector("input:not([disabled]),select"); first && first.focus();
  }
  document.getElementById("mSave").addEventListener("click", async () => {
    const body = {};
    mFields.querySelectorAll("[data-k]").forEach((el) => { if (el.disabled) return; body[el.dataset.k] = el.type === "checkbox" ? (el.checked ? 1 : 0) : el.value; });
    try {
      if (editing) await api("/api/masters/" + kind + "/" + editing.id, { method: "PUT", body });
      else await api("/api/masters/" + kind, { method: "POST", body });
      bg.classList.remove("show"); await show();
    } catch (err) { mErr.textContent = err.message; }
  });
  mFields.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); document.getElementById("mSave").click(); } });

  async function settingsPane() {
    const m = await IT.loadMeta();
    pane.innerHTML = '<div class="grid cols-2"><div class="card"><h2>Display names</h2>' +
      '<div class="field" style="margin-bottom:12px"><label>Application title</label><input type="text" id="sTitle" maxlength="80" value="' + esc(m.settings.app_title) + '"></div>' +
      '<div class="field" style="margin-bottom:14px"><label>Client name (shown under the title)</label><input type="text" id="sClient" maxlength="80" value="' + esc(m.settings.client_name) + '"></div>' +
      '<button class="btn" id="sSave">Save</button> <span id="sOk" class="muted small"></span></div>' +
      '<div class="card"><h2>Backup</h2><p class="muted" style="margin-top:0">A backup of the database is taken automatically at every server start and before every upload / replace / delete (the last 30 are kept in the <code>data/backups</code> folder). You can also download the full database now.</p>' +
      '<a class="btn secondary" href="/export/database">⬇ Download database backup</a></div></div>';
    document.getElementById("sSave").addEventListener("click", async () => {
      try { await api("/api/settings", { method: "POST", body: { app_title: sTitle.value, client_name: sClient.value } }); sOk.textContent = "Saved – reload to see the new name."; }
      catch (err) { sOk.textContent = err.message; }
    });
  }
  show();
})();
