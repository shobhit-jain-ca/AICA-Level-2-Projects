"""Investment Tracker - Flask web application."""
import ipaddress
import os
import io
import re
import json
import time
import uuid
import secrets
import shutil
import datetime as dt
from functools import wraps

from flask import (Flask, g, request, session, redirect, url_for, render_template, jsonify, abort,
                   send_file, flash, Response)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

import db
import importer
import reports
import exports
import template_builder

APP_VERSION = "1.2"
MAX_UPLOAD_MB = 15

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


# --------------------------------------------------------------------------- setup
def _load_secret():
    db.ensure_dirs()
    p = os.path.join(db.DATA_DIR, "secret.key")
    if not os.path.exists(p):
        with open(p, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(p) as fh:
        return fh.read().strip()


def load_config():
    cfg = {"host": "0.0.0.0", "port": 8080, "https": False}
    p = os.path.join(db.DATA_DIR, "config.json")
    if os.path.exists(p):
        try:
            with open(p) as fh:
                cfg.update(json.load(fh))
        except Exception:
            pass
    return cfg


db.init_db()
app.secret_key = _load_secret()
CONFIG = load_config()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(CONFIG.get("https")),
    PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=10),
)


# --------------------------------------------------------------------------- helpers
def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def client_ip():
    """Real visitor address. Behind the Cloudflare tunnel every request arrives from this
    server itself (127.0.0.1), so the address Cloudflare supplies is trusted ONLY when the
    connection really comes from the loopback interface; from anywhere else it is ignored."""
    ra = request.remote_addr or "?"
    if ra in ("127.0.0.1", "::1"):
        fwd = (request.headers.get("CF-Connecting-IP") or "").strip()
        if fwd:
            try:
                return str(ipaddress.ip_address(fwd))
            except ValueError:
                pass
    return ra


def log(action, detail=""):
    con = get_db()
    db.audit(con, session.get("username"), client_ip(), action, detail)
    con.commit()


def inr(v, decimals=2):
    """Indian digit grouping: 12,34,567.89"""
    if v is None or v == "":
        return "-"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    neg = v < 0
    v = abs(v)
    s = f"{v:.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    out = whole + ("." + frac if decimals else "")
    return ("-" if neg else "") + out


def dmy(s):
    if not s:
        return "-"
    try:
        return dt.date.fromisoformat(s[:10]).strftime("%d-%b-%Y")
    except ValueError:
        return s


def dmy_time(s):
    if not s:
        return "-"
    try:
        return dt.datetime.fromisoformat(s).strftime("%d-%b-%Y %H:%M")
    except ValueError:
        return s


app.jinja_env.filters["inr"] = inr
app.jinja_env.filters["dmy"] = dmy
app.jinja_env.filters["dmytime"] = dmy_time


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    if "user" not in g:
        row = get_db().execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
        g.user = row
    return g.user


def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify(error="Please log in again."), 401
            return redirect(url_for("login", next=request.path))
        return fn(*a, **k)
    return w


def admin_required(fn):
    @wraps(fn)
    @login_required
    def w(*a, **k):
        if current_user()["role"] != "admin":
            if request.path.startswith("/api/"):
                return jsonify(error="Administrator access required."), 403
            abort(403)
        return fn(*a, **k)
    return w


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        sent = request.headers.get("X-CSRF-Token") or request.form.get("_csrf")
        if not sent or sent != session.get("csrf"):
            if request.path.startswith("/api/"):
                return jsonify(error="Session expired. Please reload the page."), 400
            flash("Your session expired. Please try again.", "error")
            return redirect(request.referrer or url_for("login"))


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self'")
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "public, max-age=86400"
    else:
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.context_processor
def inject_globals():
    ctx = {"app_version": APP_VERSION, "user": None, "settings": {}}
    try:
        ctx["settings"] = db.get_settings(get_db())
        ctx["user"] = current_user()
    except Exception:
        pass
    return ctx


# --------------------------------------------------------------------------- auth
_fails = {}  # (ip, username) -> [count, locked_until]
MAX_FAILS, LOCK_SECONDS = 5, 600


@app.route("/login", methods=["GET", "POST"])
def login():
    con = get_db()
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        return render_template("login.html", no_users=True)
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        pw = request.form.get("password") or ""
        k = (client_ip(), username.lower())
        rec = _fails.get(k, [0, 0])
        if rec[1] > time.time():
            wait = int((rec[1] - time.time()) / 60) + 1
            flash(f"Too many failed attempts. Try again in about {wait} minute(s).", "error")
            return render_template("login.html"), 429
        u = con.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if u and check_password_hash(u["password_hash"], pw):
            _fails.pop(k, None)
            session.clear()
            session.permanent = True
            session["uid"] = u["id"]
            session["username"] = u["username"]
            session["csrf"] = secrets.token_hex(16)
            con.execute("UPDATE users SET last_login=datetime('now','localtime') WHERE id=?", (u["id"],))
            db.audit(con, u["username"], client_ip(), "login")
            con.commit()
            nxt = request.args.get("next") or ""
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("dashboard_page")
            return redirect(nxt)
        rec[0] += 1
        if rec[0] >= MAX_FAILS:
            rec = [0, time.time() + LOCK_SECONDS]
        _fails[k] = rec
        db.audit(con, username, client_ip(), "login_failed")
        con.commit()
        flash("Incorrect username or password.", "error")
        return render_template("login.html"), 401
    return render_template("login.html")


@app.route("/logout", methods=["POST", "GET"])
def logout():
    if session.get("uid"):
        log("logout")
    session.clear()
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        old, new, new2 = (request.form.get(x) or "" for x in ("old", "new", "new2"))
        u = current_user()
        if not check_password_hash(u["password_hash"], old):
            flash("Current password is incorrect.", "error")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new != new2:
            flash("New passwords do not match.", "error")
        else:
            con = get_db()
            con.execute("UPDATE users SET password_hash=? WHERE id=?",
                        (generate_password_hash(new, method="pbkdf2:sha256"), u["id"]))
            con.commit()
            log("password_changed")
            flash("Password changed.", "ok")
            return redirect(url_for("account"))
    return render_template("account.html", page="account")


# --------------------------------------------------------------------------- pages
@app.route("/")
@login_required
def dashboard_page():
    return render_template("dashboard.html", page="dashboard")


@app.route("/compare")
@login_required
def compare_page():
    return render_template("compare.html", page="compare")


@app.route("/holdings")
@login_required
def holdings_page():
    return render_template("holdings.html", page="holdings")


@app.route("/maturities")
@login_required
def maturities_page():
    return render_template("maturities.html", page="maturities")


@app.route("/search")
@login_required
def search_page():
    return render_template("search.html", page="search")


@app.route("/masters")
@admin_required
def masters_page():
    return render_template("masters.html", page="masters")


@app.route("/audit")
@admin_required
def audit_page():
    rows = get_db().execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 500").fetchall()
    return render_template("audit.html", rows=rows, page="audit")


@app.route("/manifest.webmanifest")
def manifest():
    title = db.get_settings(get_db()).get("app_title", "Investment Tracker")
    return Response(json.dumps({
        "name": title, "short_name": "Investments", "start_url": "/", "display": "standalone",
        "background_color": "#ffffff", "theme_color": "#1f4fa8",
        "icons": [{"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png"}]}),
        mimetype="application/manifest+json")


@app.errorhandler(403)
def err403(_e):
    return render_template("error.html", code=403, msg="You do not have permission to open this page."), 403


@app.errorhandler(404)
def err404(_e):
    return render_template("error.html", code=404, msg="Page not found."), 404


@app.errorhandler(413)
def err413(_e):
    return render_template("error.html", code=413, msg=f"File too large (max {MAX_UPLOAD_MB} MB)."), 413


# --------------------------------------------------------------------------- report APIs
def parse_filters(args):
    def lst(name):
        v = args.get(name, "")
        return [x for x in v.split(",") if x.strip()] if v else []
    return {k: lst(k) for k in ("entity", "group", "type", "bank", "fund")}


@app.route("/api/meta")
@login_required
def api_meta():
    con = get_db()
    q = lambda sql: [dict(r) for r in con.execute(sql)]
    return jsonify(
        dates=reports.list_dates(con),
        entities=q("SELECT id,name,entity_type FROM entities WHERE active=1 ORDER BY sort_order,name"),
        groups=q("SELECT id,name FROM investment_groups WHERE active=1 ORDER BY sort_order,name"),
        types=q("SELECT t.id,t.name,t.group_id FROM investment_types t WHERE t.active=1 ORDER BY t.sort_order,t.name"),
        banks=q("SELECT id,name FROM banks WHERE active=1 ORDER BY name"),
        funds=q("SELECT id,name FROM funds WHERE active=1 ORDER BY name"),
        color_order=reports.color_order(con),
        settings=db.get_settings(con), is_admin=current_user()["role"] == "admin", today=dt.date.today().isoformat())


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    con = get_db()
    return jsonify(reports.dashboard(con, request.args.get("date"), parse_filters(request.args)))


@app.route("/api/matrix")
@login_required
def api_matrix():
    con = get_db()
    date = request.args.get("date")
    dates = [u["as_on_date"] for u in reports.list_dates(con)]
    if not dates:
        return jsonify(empty=True)
    if date not in dates:
        date = dates[-1]
    out = reports.matrix(con, date, parse_filters(request.args))
    out["date"] = date
    return jsonify(out)


@app.route("/api/compare")
@login_required
def api_compare():
    dates = [d for d in (request.args.get("dates") or "").split(",") if d]
    return jsonify(reports.compare(get_db(), dates, request.args.get("by", "type"), parse_filters(request.args)))


@app.route("/api/holdings")
@login_required
def api_holdings():
    con = get_db()
    date = request.args.get("date")
    dates = [u["as_on_date"] for u in reports.list_dates(con)]
    if not dates:
        return jsonify(date=None, rows=[])
    if date not in dates:
        date = dates[-1]
    rows = reports.holdings(con, date, parse_filters(request.args), request.args.get("q"),
                            request.args.get("closed") == "1")
    return jsonify(date=date, rows=rows)


@app.route("/api/maturities")
@login_required
def api_maturities():
    con = get_db()
    date = request.args.get("date")
    dates = [u["as_on_date"] for u in reports.list_dates(con)]
    if not dates:
        return jsonify(date=None, rows=[], ladder={"labels": [], "values": [], "past_due": 0})
    if date not in dates:
        date = dates[-1]
    f = parse_filters(request.args)
    days = request.args.get("days", "180")
    days = int(days) if days.isdigit() else 180
    return jsonify(date=date, rows=reports.maturities(con, date, days, f),
                   ladder=reports.maturity_ladder(con, date, f))


# --------------------------------------------------------------------------- Excel exports
HEAD_FILL = PatternFill("solid", fgColor="1F4FA8")
HEAD_FONT = Font(bold=True, color="FFFFFF")
AMT = r'[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00'


def _send_wb(wb, name):
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(bio, as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/export/compare.xlsx")
@login_required
def export_compare():
    dates = [d for d in (request.args.get("dates") or "").split(",") if d]
    res = reports.compare(get_db(), dates, request.args.get("by", "type"), parse_filters(request.args))
    wb = Workbook()
    ws = wb.active
    ws.title = "Comparison"
    ws["A1"] = f"Comparison by {res['by_title']}"
    ws["A1"].font = Font(size=14, bold=True, color="1F4FA8")
    ws["A2"] = f"Generated {dt.datetime.now():%d-%b-%Y %H:%M} by {current_user()['username']}. Active holdings only; amounts in INR."
    hdr = [res["by_title"]] + [dmy(d) for d in res["dates"]] + ["Change (first → last)", "Change %"]
    for i, h in enumerate(hdr, 1):
        c = ws.cell(4, i, h)
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    r = 5
    for row in res["rows"]:
        ws.cell(r, 1, row["label"])
        for i, d in enumerate(res["dates"], 2):
            ws.cell(r, i, row["values"][d]).number_format = AMT
        n = len(res["dates"])
        ws.cell(r, n + 2, row["change"]).number_format = AMT
        if row["pct"] is not None:
            ws.cell(r, n + 3, row["pct"] / 100).number_format = "0.00%"
        r += 1
    if res["rows"]:
        ws.cell(r, 1, "TOTAL").font = Font(bold=True)
        for i, d in enumerate(res["dates"], 2):
            c = ws.cell(r, i, res["totals"][d])
            c.number_format, c.font = AMT, Font(bold=True)
        n = len(res["dates"])
        ws.cell(r, n + 2, res["total_change"]).number_format = AMT
        if res["total_pct"] is not None:
            ws.cell(r, n + 3, res["total_pct"] / 100).number_format = "0.00%"
    ws.column_dimensions["A"].width = 58
    for i in range(2, len(hdr) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 19
    ws.freeze_panes = "B5"
    return _send_wb(wb, f"Comparison_{res['by']}_{dt.date.today():%Y%m%d}.xlsx")


@app.route("/export/holdings.xlsx")
@login_required
def export_holdings():
    con = get_db()
    dates = [u["as_on_date"] for u in reports.list_dates(con)]
    date = request.args.get("date")
    if date not in dates:
        date = dates[-1] if dates else None
    if not date:
        abort(404)
    rows = reports.holdings(con, date, parse_filters(request.args), request.args.get("q"), request.args.get("closed") == "1")
    wb = Workbook()
    ws = wb.active
    ws.title = "Holdings"
    cols = [("Entity", "entity", 20), ("Investment Group", "grp", 18), ("Investment Type", "type", 18),
            ("Bank / Institution", "bank", 24), ("Fund / Security", "fund", 38), ("Joint Holder(s)", "joint_holder", 16),
            ("Nominee", "nominee", 12), ("Account / Folio No.", "account_no", 24), ("Quantity", "quantity", 12),
            ("Start / Issue Date", "start_date", 14), ("Invested Amount", "invested_amount", 16),
            ("Current Value", "current_value", 16), ("Gain / (Loss)", "gain", 16), ("Maturity Date", "maturity_date", 14),
            ("Maturity Amount", "maturity_amount", 16), ("Interest %", "interest_rate", 10), ("Auto Renewal", "auto_renewal", 10),
            ("Status", "status", 9), ("Last Updated", "last_updated", 14), ("Managed By", "managed_by", 16),
            ("Contact Person", "contact_person", 20), ("Contact No.", "contact_no", 16), ("Contact Email", "contact_email", 24),
            ("Remarks", "remarks", 36)]
    ws["A1"] = f"Holdings as on {dmy(date)}"
    ws["A1"].font = Font(size=14, bold=True, color="1F4FA8")
    for i, (h, k, w) in enumerate(cols, 1):
        c = ws.cell(3, i, h)
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        ws.column_dimensions[get_column_letter(i)].width = w
    for r, row in enumerate(rows, 4):
        for i, (h, k, w) in enumerate(cols, 1):
            v = row.get(k)
            if k in ("start_date", "maturity_date", "last_updated") and v:
                v = dt.date.fromisoformat(v)
            c = ws.cell(r, i, v)
            if k in ("start_date", "maturity_date", "last_updated"):
                c.number_format = "dd-mmm-yyyy"
            elif k in ("invested_amount", "current_value", "gain", "maturity_amount"):
                c.number_format = AMT
    n = len(rows)
    ws.cell(n + 5, 11, "Total").font = Font(bold=True)
    c = ws.cell(n + 5, 12, f"=SUMIFS(L4:L{n + 3},R4:R{n + 3},\"Active\")")
    c.number_format, c.font = AMT, Font(bold=True)
    ws.freeze_panes = "C4"
    ws.auto_filter.ref = f"A3:{get_column_letter(len(cols))}{n + 3}"
    return _send_wb(wb, f"Holdings_{date}.xlsx")


# --------------------------------------------------------------------------- search + PDF / Excel exports
def _dates(con):
    return [u["as_on_date"] for u in reports.list_dates(con)]


def _pick_date(con, arg):
    dates = _dates(con)
    if not dates:
        return None
    return arg if arg in dates else dates[-1]


def _filter_text(con, f):
    """'Entity: AAA, BBB · Type: Fixed Deposit' for the report header."""
    tables = (("entity", "Entity", "entities"), ("group", "Group", "investment_groups"), ("type", "Type", "investment_types"),
              ("bank", "Bank", "banks"), ("fund", "Fund", "funds"))
    parts = []
    for key, label, tbl in tables:
        ids = reports._ids((f or {}).get(key))
        if ids:
            names = [r["name"] for r in con.execute(
                f"SELECT name FROM {tbl} WHERE id IN ({','.join('?' * len(ids))}) ORDER BY name", ids)]
            parts.append(f"{label}: {', '.join(names)}")
    return "  ·  ".join(parts)


def _ctx(con, f=None):
    st = db.get_settings(con)
    unit = request.args.get("unit", "full")
    return {"client": st.get("client_name", ""), "title": st.get("app_title", "Investment Tracker"),
            "user": current_user()["username"], "filters": _filter_text(con, f), "unit": unit if unit in ("full", "lakh", "crore") else "full"}


def _send_bytes(data, name, kind):
    mime = "application/pdf" if kind == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)


def _search_args(con):
    q = (request.args.get("q") or "").strip()
    raw = request.args.get("date", "")
    date = None if raw == "all" else _pick_date(con, raw)
    return q, date, request.args.get("closed") == "1"


@app.route("/api/search")
@login_required
def api_search():
    con = get_db()
    q, date, closed = _search_args(con)
    res = reports.search(con, q, date, closed, parse_filters(request.args))
    res["date"] = date
    res["q"] = q
    if q:
        log("search", q[:80])
    return jsonify(res)


@app.route("/export/search.<kind>")
@login_required
def export_search(kind):
    if kind not in ("pdf", "xlsx"):
        abort(404)
    con = get_db()
    q, date, closed = _search_args(con)
    f = parse_filters(request.args)
    res = reports.search(con, q, date, closed, f)
    ctx = _ctx(con, f)
    log("export", f"search.{kind}")
    data = exports.search_pdf(res, q, date, ctx) if kind == "pdf" else exports.search_xlsx(res, q, date, ctx)
    return _send_bytes(data, exports._fname("Search", kind), kind)


@app.route("/export/dashboard.<kind>")
@login_required
def export_dashboard(kind):
    if kind not in ("pdf", "xlsx"):
        abort(404)
    con = get_db()
    date = _pick_date(con, request.args.get("date"))
    if not date:
        abort(404)
    f = parse_filters(request.args)
    d = reports.dashboard(con, date, f)
    m = reports.matrix(con, date, f)
    m["date"] = date
    ctx = _ctx(con, f)
    log("export", f"dashboard.{kind} {date}")
    data = exports.dashboard_pdf(d, m, ctx) if kind == "pdf" else exports.dashboard_xlsx(d, m, ctx)
    return _send_bytes(data, exports._fname("Dashboard_" + date, kind), kind)


@app.route("/export/compare.pdf")
@login_required
def export_compare_pdf():
    con = get_db()
    dates = [d for d in (request.args.get("dates") or "").split(",") if d]
    f = parse_filters(request.args)
    res = reports.compare(con, dates, request.args.get("by", "type"), f)
    log("export", "compare.pdf")
    return _send_bytes(exports.compare_pdf(res, _ctx(con, f)), exports._fname("Comparison_" + res["by"], "pdf"), "pdf")


@app.route("/export/holdings.pdf")
@login_required
def export_holdings_pdf():
    con = get_db()
    date = _pick_date(con, request.args.get("date"))
    if not date:
        abort(404)
    f = parse_filters(request.args)
    rows = reports.holdings(con, date, f, request.args.get("q"), request.args.get("closed") == "1")
    ctx = _ctx(con, f)
    if request.args.get("q"):
        ctx["filters"] = (ctx["filters"] + "  ·  " if ctx["filters"] else "") + f"Search: {request.args.get('q')}"
    log("export", f"holdings.pdf {date}")
    return _send_bytes(exports.holdings_pdf(rows, date, ctx), exports._fname("Holdings_" + date, "pdf"), "pdf")


@app.route("/export/maturities.<kind>")
@login_required
def export_maturities(kind):
    if kind not in ("pdf", "xlsx"):
        abort(404)
    con = get_db()
    date = _pick_date(con, request.args.get("date"))
    if not date:
        abort(404)
    f = parse_filters(request.args)
    days = request.args.get("days", "180")
    days = int(days) if days.isdigit() else 180
    rows = reports.maturities(con, date, days, f)
    ladder = reports.maturity_ladder(con, date, f)
    ctx = _ctx(con, f)
    log("export", f"maturities.{kind} {date}")
    data = (exports.maturities_pdf(rows, ladder, date, days, ctx) if kind == "pdf"
            else exports.maturities_xlsx(rows, ladder, date, days, ctx))
    return _send_bytes(data, exports._fname("Maturities_" + date, kind), kind)



@app.route("/template.xlsx")
@login_required
def download_template():
    data = template_builder.build_template(get_db())
    return send_file(io.BytesIO(data), as_attachment=True, download_name="Investment_Upload_Template.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/export/database")
@admin_required
def export_database():
    p = db.backup_db()
    log("database_backup_download")
    return send_file(p, as_attachment=True, download_name=os.path.basename(p))


# --------------------------------------------------------------------------- uploads
def _tmp_path(token, ext):
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        abort(400)
    return os.path.join(db.TMP_DIR, token + ext)


def _clean_tmp():
    cutoff = time.time() - 86400
    for f in os.listdir(db.TMP_DIR):
        p = os.path.join(db.TMP_DIR, f)
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
        except OSError:
            pass


@app.route("/uploads")
@admin_required
def uploads_page():
    ups = list(reversed(reports.list_dates(get_db())))
    return render_template("uploads.html", ups=ups, page="uploads")


@app.route("/uploads/parse", methods=["POST"])
@admin_required
def uploads_parse():
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Please choose an Excel file to upload.", "error")
        return redirect(url_for("uploads_page"))
    if not f.filename.lower().endswith((".xlsx", ".xlsm")):
        flash("Only .xlsx files are supported. Please use the template from this tool.", "error")
        return redirect(url_for("uploads_page"))
    _clean_tmp()
    token = uuid.uuid4().hex
    xlsx = _tmp_path(token, ".xlsx")
    f.save(xlsx)
    con = get_db()
    parsed = importer.parse_workbook(xlsx, con)
    parsed["filename"] = secure_filename(f.filename) or "upload.xlsx"
    summ = importer.summarise(parsed["rows"])
    exists = None
    variance = []
    if parsed["as_on"]:
        exists = con.execute("SELECT * FROM uploads WHERE as_on_date=?", (parsed["as_on"],)).fetchone()
        prev = con.execute("SELECT as_on_date FROM uploads WHERE as_on_date<? ORDER BY as_on_date DESC LIMIT 1",
                           (parsed["as_on"],)).fetchone()
        if prev:
            pv = {r["name"]: r["v"] for r in con.execute(
                "SELECT e.name, SUM(h.current_value) v FROM holdings h JOIN entities e ON e.id=h.entity_id "
                "WHERE h.as_on_date=? AND h.status='Active' GROUP BY e.id", (prev["as_on_date"],))}
            for name in sorted(set(pv) | set(summ["by_entity"])):
                a, b = pv.get(name, 0.0), summ["by_entity"].get(name, 0.0)
                pct = ((b - a) / a * 100) if a else None
                variance.append({"entity": name, "prev": a, "new": b, "pct": pct})
                if pct is not None and abs(pct) >= 25:
                    parsed["warnings"].append(
                        f"{name}: total moved {pct:+.1f}% versus {dmy(prev['as_on_date'])} — please confirm this is expected.")
            parsed["prev_date"] = prev["as_on_date"]
    with open(_tmp_path(token, ".json"), "w") as fh:
        json.dump(parsed, fh)
    return render_template("upload_preview.html", p=parsed, token=token, summ=summ, exists=exists,
                           variance=variance, page="uploads")


@app.route("/uploads/confirm", methods=["POST"])
@admin_required
def uploads_confirm():
    token = request.form.get("token")
    jp = _tmp_path(token, ".json")
    if not os.path.exists(jp):
        flash("The preview expired. Please upload the file again.", "error")
        return redirect(url_for("uploads_page"))
    with open(jp) as fh:
        parsed = json.load(fh)
    if parsed["errors"]:
        flash("The file still has errors. Please fix them and upload again.", "error")
        return redirect(url_for("uploads_page"))
    con = get_db()
    exists = con.execute("SELECT id FROM uploads WHERE as_on_date=?", (parsed["as_on"],)).fetchone()
    replace = request.form.get("replace") == "1"
    if exists and not replace:
        flash("Data for this As-On Date already exists. Tick the replace box to overwrite it.", "error")
        return redirect(url_for("uploads_page"))
    stored = f"{parsed['as_on']}_{dt.datetime.now():%Y%m%d%H%M%S}_{parsed['filename']}"
    shutil.copy(_tmp_path(token, ".xlsx"), os.path.join(db.UPLOAD_DIR, stored))
    try:
        db.backup_db()  # safety copy BEFORE changing data
        importer.commit(con, parsed, current_user()["username"], parsed["filename"], stored, replace,
                        (request.form.get("note") or "").strip() or None)
        db.audit(con, session["username"], client_ip(), "upload_replace" if exists else "upload",
                 f"as_on={parsed['as_on']} rows={len(parsed['rows'])} file={parsed['filename']}")
        con.commit()
    except Exception as e:  # noqa
        con.rollback()
        flash(f"Upload failed: {e}", "error")
        return redirect(url_for("uploads_page"))
    for ext in (".json", ".xlsx"):
        try:
            os.remove(_tmp_path(token, ext))
        except OSError:
            pass
    flash(f"Data for {dmy(parsed['as_on'])} saved ({len(parsed['rows'])} holdings).", "ok")
    return redirect(url_for("dashboard_page"))


@app.route("/uploads/<int:uid>/delete", methods=["POST"])
@admin_required
def uploads_delete(uid):
    con = get_db()
    u = con.execute("SELECT * FROM uploads WHERE id=?", (uid,)).fetchone()
    if not u:
        abort(404)
    db.backup_db()
    con.execute("DELETE FROM uploads WHERE id=?", (uid,))  # holdings cascade
    db.audit(con, session["username"], client_ip(), "upload_deleted", f"as_on={u['as_on_date']}")
    con.commit()
    flash(f"Data for {dmy(u['as_on_date'])} deleted. (A backup copy was taken first.)", "ok")
    return redirect(url_for("uploads_page"))


@app.route("/uploads/<int:uid>/file")
@admin_required
def uploads_file(uid):
    u = get_db().execute("SELECT * FROM uploads WHERE id=?", (uid,)).fetchone()
    if not u or not u["stored_file"]:
        abort(404)
    p = os.path.join(db.UPLOAD_DIR, os.path.basename(u["stored_file"]))
    if not os.path.exists(p):
        abort(404)
    return send_file(p, as_attachment=True, download_name=u["filename"] or "upload.xlsx")


# --------------------------------------------------------------------------- masters API
def _opts(con, sql):
    return [{"value": r[0], "label": r[1]} for r in con.execute(sql)]


def master_defs(con):
    return {
        "entities": dict(title="Entities", table="entities", used="SELECT COUNT(*) FROM holdings WHERE entity_id=?",
                         help="Individuals, companies, HUFs whose investments are tracked. Name must match the Excel exactly.",
                         fields=[dict(k="name", label="Name", type="text", required=True),
                                 dict(k="entity_type", label="Type", type="select",
                                      options=[{"value": x, "label": x} for x in db.ENTITY_TYPES]),
                                 dict(k="sort_order", label="Display order", type="number")]),
        "banks": dict(title="Banks / Institutions", table="banks", used="SELECT COUNT(*) FROM holdings WHERE bank_id=?",
                      help="Banks, brokers, AMCs where investments are held.",
                      fields=[dict(k="name", label="Bank / Institution name", type="text", required=True)]),
        "funds": dict(title="Funds / Securities", table="funds", used="SELECT COUNT(*) FROM holdings WHERE fund_id=?",
                      help="Mutual fund schemes, PMS, bonds, shares, debentures.",
                      fields=[dict(k="name", label="Fund / Security name", type="text", required=True)]),
        "types": dict(title="Investment Types", table="investment_types", used="SELECT COUNT(*) FROM holdings WHERE type_id=?",
                      help="Each type belongs to a group. Tick 'Cost = value' for items without market movement "
                           "(bank balance, FD, PPF, EPF).",
                      fields=[dict(k="name", label="Investment type", type="text", required=True),
                              dict(k="group_id", label="Group", type="select", required=True,
                                   options=_opts(con, "SELECT id,name FROM investment_groups WHERE active=1 ORDER BY sort_order,name")),
                              dict(k="cost_equals_value", label="Cost = value", type="check"),
                              dict(k="sort_order", label="Display order", type="number")]),
        "groups": dict(title="Investment Groups", table="investment_groups",
                       used="SELECT COUNT(*) FROM investment_types WHERE group_id=?",
                       help="Broad buckets used in charts (e.g. Mutual Funds, Fixed Deposits).",
                       fields=[dict(k="name", label="Group name", type="text", required=True),
                               dict(k="sort_order", label="Display order", type="number")]),
        "users": dict(title="Users", table="users", used=None,
                      help="Administrators can upload data and manage masters. Viewers can only see reports.",
                      fields=[dict(k="username", label="Username", type="text", required=True),
                              dict(k="full_name", label="Full name", type="text"),
                              dict(k="role", label="Role", type="select", required=True,
                                   options=[{"value": "viewer", "label": "Viewer (reports only)"},
                                            {"value": "admin", "label": "Administrator"}]),
                              dict(k="password", label="Password (min 8 chars)", type="password", write_only=True)]),
    }


@app.route("/api/masters/<kind>", methods=["GET"])
@admin_required
def masters_list(kind):
    con = get_db()
    defs = master_defs(con)
    if kind == "all":
        return jsonify({k: {"title": v["title"], "help": v["help"]} for k, v in defs.items()})
    d = defs.get(kind)
    if not d:
        abort(404)
    cols = [f["k"] for f in d["fields"] if not f.get("write_only")]
    extra = ", last_login" if kind == "users" else ""
    rows = [dict(r) for r in con.execute(f"SELECT id, active, {', '.join(cols)}{extra} FROM {d['table']} ORDER BY "
                                         f"{'sort_order, ' if 'sort_order' in cols else ''}{cols[0]} COLLATE NOCASE")]
    for r in rows:
        r["used"] = con.execute(d["used"], (r["id"],)).fetchone()[0] if d["used"] else None
    return jsonify(title=d["title"], help=d["help"], fields=d["fields"], rows=rows)


def _clean_values(d, data, creating):
    vals = {}
    for f in d["fields"]:
        k = f["k"]
        if k not in data and not creating:
            continue
        v = data.get(k)
        if f["type"] == "check":
            vals[k] = 1 if v in (1, True, "1", "true", "on") else 0
        elif f["type"] == "number":
            try:
                vals[k] = int(v) if v not in (None, "") else 100
            except (TypeError, ValueError):
                raise ValueError(f"{f['label']} must be a number.")
        else:
            v = (v or "").strip() if isinstance(v, str) or v is None else v
            if f.get("required") and not v:
                raise ValueError(f"{f['label']} is required.")
            vals[k] = v
    return vals


@app.route("/api/masters/<kind>", methods=["POST"])
@admin_required
def masters_add(kind):
    con = get_db()
    d = master_defs(con).get(kind)
    if not d:
        abort(404)
    data = request.get_json(force=True) or {}
    try:
        vals = _clean_values(d, data, True)
        if kind == "users":
            pw = vals.pop("password", "")
            if len(pw) < 8:
                raise ValueError("Password must be at least 8 characters.")
            vals["password_hash"] = generate_password_hash(pw, method="pbkdf2:sha256")
            if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,40}", vals["username"]):
                raise ValueError("Username: 3-40 characters, letters/numbers/._@- only.")
        cols = ",".join(vals)
        con.execute(f"INSERT INTO {d['table']}({cols}) VALUES ({','.join('?' * len(vals))})", list(vals.values()))
        db.audit(con, session["username"], client_ip(), f"master_add:{kind}", str(vals.get("name") or vals.get("username")))
        con.commit()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # sqlite3.IntegrityError etc.
        con.rollback()
        msg = "That name already exists." if "UNIQUE" in str(e) else f"Could not save: {e}"
        return jsonify(error=msg), 400
    return jsonify(ok=True)


@app.route("/api/masters/<kind>/<int:rid>", methods=["PUT"])
@admin_required
def masters_edit(kind, rid):
    con = get_db()
    d = master_defs(con).get(kind)
    if not d:
        abort(404)
    data = request.get_json(force=True) or {}
    me = current_user()
    try:
        vals = _clean_values(d, data, False)
        if kind == "users":
            pw = vals.pop("password", "")
            if pw:
                if len(pw) < 8:
                    raise ValueError("Password must be at least 8 characters.")
                vals["password_hash"] = generate_password_hash(pw, method="pbkdf2:sha256")
            if rid == me["id"] and vals.get("role") == "viewer":
                raise ValueError("You cannot remove your own administrator access.")
        if "active" in data:
            vals["active"] = 1 if data["active"] else 0
            if kind == "users" and rid == me["id"] and not vals["active"]:
                raise ValueError("You cannot deactivate your own account.")
        if kind == "users" and (vals.get("active") == 0 or vals.get("role") == "viewer"):
            others = con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (rid,)).fetchone()[0]
            if others == 0:
                raise ValueError("At least one active administrator is required.")
        if not vals:
            return jsonify(ok=True)
        sets = ",".join(f"{k}=?" for k in vals)
        con.execute(f"UPDATE {d['table']} SET {sets} WHERE id=?", list(vals.values()) + [rid])
        db.audit(con, session["username"], client_ip(), f"master_edit:{kind}", f"id={rid} {list(vals)}")
        con.commit()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        con.rollback()
        msg = "That name already exists." if "UNIQUE" in str(e) else f"Could not save: {e}"
        return jsonify(error=msg), 400
    return jsonify(ok=True)


@app.route("/api/masters/<kind>/<int:rid>", methods=["DELETE"])
@admin_required
def masters_delete(kind, rid):
    con = get_db()
    d = master_defs(con).get(kind)
    if not d or kind == "users":
        return jsonify(error="Users cannot be deleted; deactivate them instead."), 400
    used = con.execute(d["used"], (rid,)).fetchone()[0]
    if used:
        return jsonify(error=f"This is used by {used} record(s) and cannot be deleted. Deactivate it instead."), 400
    con.execute(f"DELETE FROM {d['table']} WHERE id=?", (rid,))
    db.audit(con, session["username"], client_ip(), f"master_delete:{kind}", f"id={rid}")
    con.commit()
    return jsonify(ok=True)


@app.route("/api/settings", methods=["POST"])
@admin_required
def save_settings():
    data = request.get_json(force=True) or {}
    con = get_db()
    for k in ("app_title", "client_name"):
        if k in data:
            v = str(data[k]).strip()[:80]
            if not v:
                return jsonify(error="Value cannot be empty."), 400
            con.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (k, v))
    db.audit(con, session["username"], client_ip(), "settings_changed")
    con.commit()
    return jsonify(ok=True)


@app.route("/health")
def health():
    return "ok"


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=CONFIG["port"], debug=False)
