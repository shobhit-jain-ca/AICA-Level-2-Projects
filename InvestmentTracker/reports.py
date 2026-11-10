"""All reporting queries. Only 'Active' holdings are counted in totals."""
import datetime as dt

FROM = """
FROM holdings h
JOIN entities e ON e.id = h.entity_id
JOIN investment_types t ON t.id = h.type_id
JOIN investment_groups g ON g.id = t.group_id
LEFT JOIN banks b ON b.id = h.bank_id
LEFT JOIN funds f ON f.id = h.fund_id
"""

DIMS = {
    "entity": ("e.id", "e.name", "e.sort_order, e.name"),
    "group": ("g.id", "g.name", "g.sort_order, g.name"),
    "type": ("t.id", "t.name", "g.sort_order, t.sort_order, t.name"),
    "bank": ("COALESCE(b.id,0)", "COALESCE(b.name,'(No bank / institution)')", "COALESCE(b.name,'~')"),
    "fund": ("COALESCE(f.id,0)", "COALESCE(f.name,'(No fund / security)')", "COALESCE(f.name,'~')"),
    "holding": (
        "h.holding_key",
        "t.name || ' | ' || COALESCE(f.name, b.name, h.managed_by, '-') || CASE WHEN COALESCE(h.account_no,'')<>'' "
        "THEN ' | ' || h.account_no ELSE '' END || ' [' || e.name || ']'",
        "e.sort_order, e.name, g.sort_order, t.name, COALESCE(f.name,b.name,'')"),
}
DIM_TITLES = {"entity": "Entity", "group": "Investment Group", "type": "Investment Type",
              "bank": "Bank / Institution", "fund": "Fund / Security", "holding": "Individual Holding"}


def _ids(v):
    out = []
    for x in v or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return out


def build_where(filters, include_closed=False):
    where, params = [], []
    if not include_closed:
        where.append("h.status='Active'")
    for key, col in (("entity", "h.entity_id"), ("group", "g.id"), ("type", "h.type_id"),
                     ("bank", "h.bank_id"), ("fund", "h.fund_id")):
        ids = _ids((filters or {}).get(key))
        if ids:
            where.append(f"{col} IN ({','.join('?' * len(ids))})")
            params += ids
    return where, params


def list_dates(con):
    return [dict(r) for r in con.execute(
        "SELECT id, as_on_date, prepared_on, uploaded_at, uploaded_by, filename, row_count, total_value, note "
        "FROM uploads ORDER BY as_on_date")]


def color_order(con):
    """Per dimension, item labels ordered by value on the latest date (unfiltered).
    The front end gives the first 7 a fixed chart colour so colours never change when filters change."""
    ups = list_dates(con)
    if not ups:
        return {}
    latest = ups[-1]["as_on_date"]
    out = {}
    for dim in ("entity", "group", "type", "bank", "fund"):
        rows = sorted(_group_by(con, dim, latest, {}), key=lambda r: -(r["v"] or 0))
        out[dim] = [r["label"] for r in rows]
    return out


def _total(con, date, filters):
    where, params = build_where(filters)
    where.append("h.as_on_date=?")
    params.append(date)
    return con.execute(f"SELECT COALESCE(SUM(h.current_value),0) {FROM} WHERE {' AND '.join(where)}", params).fetchone()[0]


def _group_by(con, dim, date, filters):
    idc, lab, order = DIMS[dim]
    where, params = build_where(filters)
    where.append("h.as_on_date=?")
    params.append(date)
    rows = con.execute(
        f"SELECT {idc} AS k, {lab} AS label, SUM(h.current_value) AS v, COUNT(*) AS n {FROM} "
        f"WHERE {' AND '.join(where)} GROUP BY k ORDER BY {order}", params).fetchall()
    return [dict(r) for r in rows]


def previous_date(dates, date):
    prev = [d for d in dates if d < date]
    return prev[-1] if prev else None


def dashboard(con, date, filters):
    ups = list_dates(con)
    dates = [u["as_on_date"] for u in ups]
    if not dates:
        return {"empty": True}
    if date not in dates:
        date = dates[-1]
    prev = previous_date(dates, date)
    total = _total(con, date, filters)
    prev_total = _total(con, prev, filters) if prev else None

    where, params = build_where(filters)
    where_d = where + ["h.as_on_date=?"]
    pd = params + [date]
    w = " AND ".join(where_d)
    cnt = con.execute(f"SELECT COUNT(*) {FROM} WHERE {w}", pd).fetchone()[0]
    cost = con.execute(
        f"SELECT COALESCE(SUM(h.invested_amount),0), COALESCE(SUM(h.current_value),0), COUNT(*) {FROM} "
        f"WHERE {w} AND h.invested_amount IS NOT NULL", pd).fetchone()
    market_cost = con.execute(
        f"SELECT COALESCE(SUM(h.invested_amount),0), COALESCE(SUM(h.current_value),0), COUNT(*) {FROM} "
        f"WHERE {w} AND h.invested_amount IS NOT NULL AND t.cost_equals_value=0", pd).fetchone()
    mkt_total = con.execute(f"SELECT COUNT(*) {FROM} WHERE {w} AND t.cost_equals_value=0", pd).fetchone()[0]
    avg_rate = con.execute(
        f"SELECT SUM(h.interest_rate*h.current_value)/NULLIF(SUM(h.current_value),0), COUNT(*) {FROM} "
        f"WHERE {w} AND h.interest_rate IS NOT NULL AND h.current_value>0", pd).fetchone()

    def with_prev(dim):
        cur = _group_by(con, dim, date, filters)
        pv = {r["k"]: r["v"] for r in _group_by(con, dim, prev, filters)} if prev else {}
        for r in cur:
            r["prev"] = pv.get(r["k"]) if prev else None
        return cur

    # trend: total & by group, all dates
    idc, lab, order = DIMS["group"]
    tw, tp = build_where(filters)
    rows = con.execute(
        f"SELECT h.as_on_date AS d, g.name AS grp, SUM(h.current_value) AS v {FROM} "
        f"WHERE {' AND '.join(tw)} GROUP BY h.as_on_date, g.id ORDER BY h.as_on_date, g.sort_order", tp).fetchall()
    trend_total, grp_series = {d: 0.0 for d in dates}, {}
    for r in rows:
        trend_total[r["d"]] += r["v"]
        grp_series.setdefault(r["grp"], {})[r["d"]] = r["v"]
    trend = {
        "dates": dates,
        "total": [trend_total[d] for d in dates],
        "groups": [{"name": g, "values": [s.get(d, 0.0) for d in dates]} for g, s in grp_series.items()],
    }

    top = con.execute(
        f"SELECT e.name AS entity, t.name AS type, COALESCE(f.name,b.name,h.managed_by,t.name) AS name, h.account_no, h.current_value AS v "
        f"{FROM} WHERE {w} ORDER BY h.current_value DESC LIMIT 10", pd).fetchall()

    up = next(u for u in ups if u["as_on_date"] == date)
    return {
        "empty": False, "date": date, "prev_date": prev, "uploaded_at": up["uploaded_at"], "uploaded_by": up["uploaded_by"],
        "total": total, "prev_total": prev_total,
        "change": (total - prev_total) if prev_total is not None else None,
        "change_pct": ((total - prev_total) / prev_total * 100) if prev_total else None,
        "holdings_count": cnt,
        "cost": {"invested": cost[0], "current": cost[1], "n": cost[2],
                 "gain": cost[1] - cost[0], "gain_pct": ((cost[1] - cost[0]) / cost[0] * 100) if cost[0] else None},
        "market": {"invested": market_cost[0], "current": market_cost[1], "n": market_cost[2], "total_n": mkt_total,
                   "gain": market_cost[1] - market_cost[0],
                   "gain_pct": ((market_cost[1] - market_cost[0]) / market_cost[0] * 100) if market_cost[0] else None},
        "avg_rate": avg_rate[0], "avg_rate_n": avg_rate[1],
        "by_group": with_prev("group"), "by_type": with_prev("type"), "by_entity": with_prev("entity"),
        "trend": trend, "top": [dict(r) for r in top],
    }


def matrix(con, date, filters):
    """Investment type x entity summary for one date (like the client's old Summary sheet)."""
    where, params = build_where(filters)
    where.append("h.as_on_date=?")
    params.append(date)
    rows = con.execute(
        f"SELECT t.id AS tid, t.name AS tname, g.name AS gname, e.id AS eid, e.name AS ename, SUM(h.current_value) AS v "
        f"{FROM} WHERE {' AND '.join(where)} GROUP BY t.id, e.id", params).fetchall()
    ents = con.execute("SELECT id, name FROM entities WHERE active=1 ORDER BY sort_order, name").fetchall()
    types = con.execute(
        "SELECT t.id, t.name, g.name AS g FROM investment_types t JOIN investment_groups g ON g.id=t.group_id "
        "ORDER BY g.sort_order, t.sort_order, t.name").fetchall()
    cell = {(r["tid"], r["eid"]): r["v"] for r in rows}
    used_t = {r["tid"] for r in rows}
    used_e = {r["eid"] for r in rows}
    ent_list = [dict(e) for e in ents if e["id"] in used_e]
    out_rows = []
    for t in types:
        if t["id"] not in used_t:
            continue
        vals = [cell.get((t["id"], e["id"]), 0.0) for e in ent_list]
        out_rows.append({"type": t["name"], "group": t["g"], "values": vals, "total": sum(vals)})
    col_tot = [sum(r["values"][i] for r in out_rows) for i in range(len(ent_list))]
    return {"entities": [e["name"] for e in ent_list], "rows": out_rows, "col_totals": col_tot,
            "grand_total": sum(col_tot)}


def compare(con, dates, by, filters):
    if by not in DIMS:
        by = "type"
    all_dates = [u["as_on_date"] for u in list_dates(con)]
    dates = sorted(d for d in dates if d in all_dates)
    if not dates:
        return {"dates": [], "rows": [], "by": by, "by_title": DIM_TITLES[by]}
    idc, lab, order = DIMS[by]
    where, params = build_where(filters)
    where.append(f"h.as_on_date IN ({','.join('?' * len(dates))})")
    params += dates
    rows = con.execute(
        f"SELECT {idc} AS k, {lab} AS label, h.as_on_date AS d, SUM(h.current_value) AS v, "
        f"SUM(CASE WHEN h.invested_amount IS NOT NULL THEN h.invested_amount END) AS inv {FROM} "
        f"WHERE {' AND '.join(where)} GROUP BY k, h.as_on_date ORDER BY {order}", params).fetchall()
    out, order_keys = {}, []
    for r in rows:
        if r["k"] not in out:
            out[r["k"]] = {"key": str(r["k"]), "label": r["label"], "values": {d: None for d in dates}}
            order_keys.append(r["k"])
        out[r["k"]]["values"][r["d"]] = r["v"]
    result = []
    for k in order_keys:
        row = out[k]
        first, last = row["values"][dates[0]], row["values"][dates[-1]]
        f0, l0 = (first or 0.0), (last or 0.0)
        row["change"] = l0 - f0
        row["pct"] = ((l0 - f0) / f0 * 100) if f0 else None
        row["status"] = ("new" if first is None and last is not None else
                         "exited" if last is None and first is not None else "")
        result.append(row)
    totals = {d: sum((r["values"][d] or 0.0) for r in result) for d in dates}
    t0, tl = totals[dates[0]], totals[dates[-1]]
    return {"dates": dates, "rows": result, "totals": totals, "by": by, "by_title": DIM_TITLES[by],
            "total_change": tl - t0, "total_pct": ((tl - t0) / t0 * 100) if t0 else None}


def holdings(con, date, filters, q=None, include_closed=False):
    where, params = build_where(filters, include_closed)
    where.append("h.as_on_date=?")
    params.append(date)
    if q:
        like = f"%{q.lower()}%"
        where.append("(LOWER(COALESCE(f.name,'')) LIKE ? OR LOWER(COALESCE(b.name,'')) LIKE ? OR LOWER(COALESCE(h.account_no,'')) LIKE ? "
                     "OR LOWER(e.name) LIKE ? OR LOWER(t.name) LIKE ? OR LOWER(COALESCE(h.remarks,'')) LIKE ? "
                     "OR LOWER(COALESCE(h.joint_holder,'')) LIKE ?)")
        params += [like] * 7
    rows = con.execute(
        f"SELECT h.id, e.name AS entity, t.name AS type, g.name AS grp, b.name AS bank, f.name AS fund, h.joint_holder, "
        f"h.nominee, h.managed_by, h.account_no, h.quantity, h.start_date, h.invested_amount, h.current_value, "
        f"h.maturity_date, h.maturity_amount, h.interest_rate, h.auto_renewal, h.status, h.last_updated, "
        f"h.contact_person, h.contact_no, h.contact_email, h.remarks {FROM} WHERE {' AND '.join(where)} "
        f"ORDER BY e.sort_order, e.name, g.sort_order, t.sort_order, COALESCE(f.name,b.name,''), h.account_no", params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["stale"] = bool(d["last_updated"] and (dt.date.fromisoformat(date) - dt.date.fromisoformat(d["last_updated"])).days > 62
                          and d["status"] == "Active")
        d["gain"] = (d["current_value"] - d["invested_amount"]) if d["invested_amount"] is not None else None
        out.append(d)
    return out


def maturities(con, date, window_days, filters, today=None):
    today = today or dt.date.today()
    where, params = build_where(filters)
    where += ["h.as_on_date=?", "h.maturity_date IS NOT NULL"]
    params.append(date)
    limit = (today + dt.timedelta(days=int(window_days))).isoformat()
    where.append("h.maturity_date <= ?")
    params.append(limit)
    rows = con.execute(
        f"SELECT e.name AS entity, t.name AS type, COALESCE(f.name,b.name,h.managed_by,t.name) AS name, b.name AS bank, h.account_no, "
        f"h.current_value, h.maturity_date, h.maturity_amount, h.interest_rate, h.auto_renewal "
        f"{FROM} WHERE {' AND '.join(where)} ORDER BY h.maturity_date, e.name", params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["days_left"] = (dt.date.fromisoformat(d["maturity_date"]) - today).days
        out.append(d)
    return out


def maturity_ladder(con, date, filters, today=None):
    """Value maturing per month (future) for the next 24 months + 'Past due'."""
    today = today or dt.date.today()
    where, params = build_where(filters)
    where += ["h.as_on_date=?", "h.maturity_date IS NOT NULL"]
    params.append(date)
    rows = con.execute(
        f"SELECT h.maturity_date AS md, h.current_value AS v, COALESCE(h.maturity_amount,h.current_value) AS mv "
        f"{FROM} WHERE {' AND '.join(where)}", params).fetchall()
    buckets, past = {}, 0.0
    for r in rows:
        md = dt.date.fromisoformat(r["md"])
        if md < today:
            past += r["v"]
            continue
        k = md.strftime("%Y-%m")
        buckets[k] = buckets.get(k, 0.0) + r["v"]
    keys = sorted(buckets)
    return {"labels": keys, "values": [buckets[k] for k in keys], "past_due": past}


# --------------------------------------------------------------------------- search
SEARCH_LIMIT = 1000
_SEARCH_FIELDS = ("e.name", "g.name", "t.name", "b.name", "f.name", "h.account_no", "h.joint_holder", "h.nominee",
                  "h.managed_by", "h.remarks", "h.contact_person", "h.contact_no", "h.contact_email", "h.status",
                  "h.auto_renewal")


def _alnum(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def search(con, q, date=None, include_closed=False, filters=None):
    """Free-text search over bank / institution, fund, account or folio number, investment type, entity,
    joint holder, nominee, contact details, remarks and so on.
    Every word typed must match somewhere (AND). Account numbers match even if typed without spaces or dashes.
    date=None searches every uploaded date (history); otherwise only that As-On date."""
    tokens = [t for t in (q or "").lower().split() if t][:8]
    where, params = build_where(filters, include_closed)
    if date:
        where.append("h.as_on_date=?")
        params.append(date)
    hay = " || ' ' || ".join(f"LOWER(COALESCE({c},''))" for c in _SEARCH_FIELDS)
    acct = "LOWER(COALESCE(h.account_no,''))"
    for ch in (" ", "-", "/", ".", "_", ":", ",", "#", "(", ")", "\\"):
        acct = f"REPLACE({acct},'{ch}','')"
    esc = lambda x: x.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    for t in tokens:
        like = f"%{esc(t)}%"
        nt = _alnum(t)
        if nt and nt != t:
            where.append(f"(({hay}) LIKE ? ESCAPE '\\' OR {acct} LIKE ? ESCAPE '\\')")
            params += [like, f"%{nt}%"]
        elif nt and len(nt) >= 3:
            where.append(f"(({hay}) LIKE ? ESCAPE '\\' OR {acct} LIKE ? ESCAPE '\\')")
            params += [like, like]
        else:
            where.append(f"(({hay}) LIKE ? ESCAPE '\\')")
            params.append(like)
    if not tokens:
        return {"rows": [], "truncated": False, "total": 0.0, "count": 0, "tokens": []}
    rows = con.execute(
        f"SELECT h.id, h.as_on_date, e.name AS entity, t.name AS type, g.name AS grp, b.name AS bank, f.name AS fund, "
        f"h.joint_holder, h.nominee, h.managed_by, h.account_no, h.quantity, h.start_date, h.invested_amount, "
        f"h.current_value, h.maturity_date, h.maturity_amount, h.interest_rate, h.auto_renewal, h.status, h.last_updated, "
        f"h.contact_person, h.contact_no, h.contact_email, h.remarks {FROM} WHERE {' AND '.join(where)} "
        f"ORDER BY h.as_on_date DESC, e.sort_order, e.name, g.sort_order, t.sort_order, COALESCE(f.name,b.name,''), h.account_no "
        f"LIMIT {SEARCH_LIMIT + 1}", params).fetchall()
    truncated = len(rows) > SEARCH_LIMIT
    out = []
    for r in rows[:SEARCH_LIMIT]:
        d = dict(r)
        d["gain"] = (d["current_value"] - d["invested_amount"]) if d["invested_amount"] is not None else None
        out.append(d)
    total = sum(r["current_value"] for r in out if r["status"] == "Active") if date else None
    return {"rows": out, "truncated": truncated, "total": total, "count": len(out), "tokens": tokens}
