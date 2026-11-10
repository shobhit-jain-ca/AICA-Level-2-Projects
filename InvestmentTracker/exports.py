"""PDF and Excel exports of the reports.

Everything here receives plain data (the same dictionaries the web pages use) plus a small context dict:
    ctx = {"client": str, "title": str, "user": str, "filters": str, "unit": "full"|"lakh"|"crore"}
and returns the file as bytes.  PDF uses reportlab with the bundled DejaVu Sans font so the rupee sign prints.
"""
import io
import os
import datetime as dt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
from reportlab.graphics.shapes import Drawing, Rect, String, Line, PolyLine, Circle
from reportlab.pdfbase.pdfmetrics import stringWidth

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, LineChart, Reference

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts")
pdfmetrics.registerFont(TTFont("DV", os.path.join(FONT_DIR, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DV-B", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV", boldItalic="DV-B")

BLUE = colors.HexColor("#1f4fa8")
BLUE2 = colors.HexColor("#2a78d6")
RED = colors.HexColor("#e34948")
INK = colors.HexColor("#16202e")
INK2 = colors.HexColor("#4a5568")
GREY = colors.HexColor("#8a94a6")
LINE = colors.HexColor("#d9dfe8")
ZEBRA = colors.HexColor("#f4f7fb")
TOTALBG = colors.HexColor("#e8effa")
POSC, NEGC = "#1f4fa8", "#c62f2e"          # text colours for gain / loss (darker than chart fills, readable on white)


# --------------------------------------------------------------------------- number / date formatting
def inr(v, dec=0):
    """Indian digit grouping: 12,34,56,789.50"""
    if v is None:
        return "-"
    neg = v < 0
    v = abs(float(v))
    s = f"{v:.{dec}f}"
    ip, _, fp = s.partition(".")
    if len(ip) > 3:
        head, tail = ip[:-3], ip[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        ip = ",".join(parts) + "," + tail
    return ("-" if neg else "") + ip + ("." + fp if fp else "")


UNIT_DIV = {"full": (1, 0, ""), "lakh": (1e5, 2, " L"), "crore": (1e7, 2, " Cr")}
UNIT_NAME = {"full": "Rupees (₹)", "lakh": "₹ Lakhs", "crore": "₹ Crores"}


def num(v, unit="full"):
    """Number only (no rupee sign) in the chosen unit."""
    if v is None:
        return "-"
    div, dec, _ = UNIT_DIV.get(unit, UNIT_DIV["full"])
    return inr(v / div, dec)


def amt(v, unit="full"):
    if v is None:
        return "-"
    return "₹ " + num(v, unit) + UNIT_DIV.get(unit, UNIT_DIV["full"])[2]


def compact(v):
    a = abs(v)
    t = lambda x: str(round(x, 2)).rstrip("0").rstrip(".") if "." in str(round(x, 2)) else str(round(x, 2))
    if a >= 1e7:
        return "₹" + t(v / 1e7) + " Cr"
    if a >= 1e5:
        return "₹" + t(v / 1e5) + " L"
    if a >= 1e3:
        return "₹" + t(v / 1e3) + "k"
    return "₹" + str(int(v))


def dmy(s):
    if not s:
        return "-"
    try:
        return dt.date.fromisoformat(str(s)[:10]).strftime("%d-%b-%Y")
    except ValueError:
        return str(s)


def mon(s):
    try:
        return dt.date.fromisoformat(str(s)[:10]).strftime("%b %y")
    except ValueError:
        return str(s)


def pct(v, sign=False):
    if v is None:
        return "-"
    return ("+" if sign and v > 0 else "") + f"{v:.2f}%"


def _trunc(text, font, size, width):
    text = str(text)
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _fname(base, ext):
    return f"{base}_{dt.date.today():%Y%m%d}.{ext}"


# --------------------------------------------------------------------------- PDF framework
S = {
    "body": ParagraphStyle("body", fontName="DV", fontSize=8, leading=10, textColor=INK),
    "bodyr": ParagraphStyle("bodyr", fontName="DV", fontSize=8, leading=10, textColor=INK, alignment=TA_RIGHT),
    "small": ParagraphStyle("small", fontName="DV", fontSize=7, leading=9, textColor=INK2),
    "h1": ParagraphStyle("h1", fontName="DV-B", fontSize=17, leading=21, textColor=BLUE),
    "h2": ParagraphStyle("h2", fontName="DV-B", fontSize=11, leading=14, textColor=BLUE, spaceBefore=8, spaceAfter=4),
    "sub": ParagraphStyle("sub", fontName="DV", fontSize=8.5, leading=11, textColor=INK2),
    "klabel": ParagraphStyle("klabel", fontName="DV", fontSize=7.5, leading=9, textColor=INK2),
    "kvalue": ParagraphStyle("kvalue", fontName="DV-B", fontSize=14, leading=17, textColor=INK),
    "kfoot": ParagraphStyle("kfoot", fontName="DV", fontSize=7.5, leading=9.5, textColor=INK2),
}


def _xml(s):
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, style="body"):
    return Paragraph(_xml(text), S[style])


def PR(text, style="body"):
    """Paragraph that allows our own <font>/<b> markup."""
    return Paragraph(text, S[style])


def delta_markup(change, p=None, unit="full"):
    if change is None:
        return "-"
    col = POSC if change > 0 else NEGC if change < 0 else "#4a5568"
    arrow = "▲" if change > 0 else "▼" if change < 0 else "•"
    s = f'<font color="{col}">{arrow} {_xml(num(abs(change), unit))}'
    if p is not None:
        s += f" ({abs(p):.2f}%)"
    return s + "</font>"


class _NumberedCanvas(rl_canvas.Canvas):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved)
        for st in self._saved:
            self.__dict__.update(st)
            self.setFont("DV", 7)
            self.setFillColor(GREY)
            w, h = self._pagesize
            self.drawRightString(w - 14 * mm, 8 * mm, f"Page {self._pageNumber} of {n}")
            super().showPage()
        super().save()


def _make_doc(buf, ctx, title, orientation="landscape"):
    size = landscape(A4) if orientation == "landscape" else A4
    generated = f"Generated {dt.datetime.now():%d-%b-%Y %H:%M} by {ctx.get('user', '')}"

    def frame(c, doc):
        w, h = size
        c.saveState()
        c.setFillColor(RED)
        c.rect(0, h - 3, w, 3, stroke=0, fill=1)
        c.setFillColor(BLUE)
        c.setFont("DV-B", 9)
        c.drawString(14 * mm, h - 11 * mm, ctx.get("title") or "Investment Tracker")
        c.setFont("DV", 8)
        c.setFillColor(INK2)
        c.drawRightString(w - 14 * mm, h - 11 * mm, ctx.get("client") or "")
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.line(14 * mm, h - 13.5 * mm, w - 14 * mm, h - 13.5 * mm)
        c.line(14 * mm, 12 * mm, w - 14 * mm, 12 * mm)
        c.setFont("DV", 7)
        c.setFillColor(GREY)
        c.drawString(14 * mm, 8 * mm, generated)
        c.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=18 * mm,
                            bottomMargin=16 * mm, title=title, author=ctx.get("user", ""), subject=ctx.get("client", ""))
    return doc, frame, size[0] - 28 * mm


def _title_block(title, sub_lines, ctx):
    out = [P(title, "h1")]
    for ln in sub_lines:
        if ln:
            out.append(P(ln, "sub"))
    if ctx.get("filters"):
        out.append(P("Filters: " + ctx["filters"], "sub"))
    out.append(Spacer(1, 6))
    return out


def _table(rows, widths, right_cols=(), total_last=False, font=7.5, header_rows=1, bold_rows=(), grey_rows=(), repeat=True):
    """rows: list of lists of str / Paragraph.  Strings in right_cols are right aligned."""
    st = ParagraphStyle("c", fontName="DV", fontSize=font, leading=font + 2, textColor=INK)
    sth = ParagraphStyle("ch", fontName="DV-B", fontSize=font, leading=font + 2, textColor=colors.white)
    sr = ParagraphStyle("cr", parent=st, alignment=TA_RIGHT)
    shr = ParagraphStyle("chr", parent=sth, alignment=TA_RIGHT)
    stb = ParagraphStyle("cb", parent=st, fontName="DV-B")
    srb = ParagraphStyle("crb", parent=sr, fontName="DV-B")
    data = []
    for ri, r in enumerate(rows):
        line = []
        for ci, c in enumerate(r):
            if not isinstance(c, str):
                line.append(c)
                continue
            right = ci in right_cols
            if ri < header_rows:
                line.append(Paragraph(_xml(c), shr if right else sth))
            elif (total_last and ri == len(rows) - 1) or ri in bold_rows:
                line.append(Paragraph(_xml(c), srb if right else stb))
            else:
                line.append(Paragraph(_xml(c), sr if right else st))
        data.append(line)
    t = Table(data, colWidths=widths, repeatRows=header_rows if repeat else 0)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, header_rows), (-1, -1), 0.3, LINE),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [colors.white, ZEBRA]),
    ]
    if total_last and len(rows) > header_rows:
        cmds += [("BACKGROUND", (0, -1), (-1, -1), TOTALBG), ("LINEABOVE", (0, -1), (-1, -1), 0.8, BLUE)]
    for r in grey_rows:
        cmds.append(("TEXTCOLOR", (0, r), (-1, r), GREY))
    t.setStyle(TableStyle(cmds))
    return t


def _fit(widths, avail):
    tot = float(sum(widths))
    return [w * avail / tot for w in widths]


# ---- simple charts (reportlab graphics)
def hbar_chart(items, width, unit="full", signed=False, row_h=15, label_w=170, max_rows=14, title=None):
    """Horizontal bars. items=[(label, value)]. signed=True draws blue (+) and red (-) bars around a zero line."""
    items = items[:max_rows]
    if not items:
        return Spacer(1, 1)
    top = 16 if title else 4
    h = top + row_h * len(items) + 4
    d = Drawing(width, h)
    if title:
        d.add(String(0, h - 11, title, fontName="DV-B", fontSize=9, fillColor=INK))
    val_w = 74
    x0, x1 = label_w, width - val_w
    vmax = max(abs(v) for _, v in items) or 1
    if signed and any(v < 0 for _, v in items):
        vmin_neg = max(abs(v) for _, v in items if v < 0)
        vmax_pos = max([v for _, v in items if v > 0] or [0])
        span = (vmin_neg + vmax_pos) or 1
        zero = x0 + (x1 - x0) * (vmin_neg / span)
        scale = (x1 - x0) / span
    else:
        zero, scale = x0, (x1 - x0) / vmax
    for i, (lab, v) in enumerate(items):
        y = h - top - row_h * (i + 1) + 3
        d.add(String(0, y + 2, _trunc(lab, "DV", 7.5, label_w - 8), fontName="DV", fontSize=7.5, fillColor=INK))
        bw = abs(v) * scale
        col = BLUE2 if v >= 0 else RED
        bx = zero if v >= 0 else zero - bw
        d.add(Rect(bx, y, max(bw, 0.6), row_h - 6, fillColor=col, strokeColor=None))
        txt = ("-" if v < 0 else "") + num(abs(v), unit) if unit != "full" else ("-" if v < 0 else "") + inr(abs(v))
        d.add(String(width - val_w + 6, y + 2, txt, fontName="DV", fontSize=7.5, fillColor=INK))
    if signed:
        d.add(Line(zero, 2, zero, h - top, strokeColor=GREY, strokeWidth=0.6))
    return d


def line_chart(dates, series, width, height=150, title=None):
    """series=[(name, values, colour)] -> line chart with markers; x labels are the dates."""
    n = len(dates)
    if n == 0:
        return Spacer(1, 1)
    top = 18 if title else 6
    left, right, bottom = 56, 10, 34 if len(series) > 1 else 20
    d = Drawing(width, height)
    if title:
        d.add(String(0, height - 11, title, fontName="DV-B", fontSize=9, fillColor=INK))
    allv = [v for _, vals, _ in series for v in vals if v is not None]
    vmax, vmin = max(allv), min(allv)
    if vmin > 0:
        vmin = min(vmin, vmax * 0.0) if len(set(allv)) == 1 else vmin - (vmax - vmin) * 0.15
    if vmax == vmin:
        vmax = vmin + 1
    vmin = max(vmin, 0) if min(allv) >= 0 else vmin
    px0, px1 = left, width - right
    py0, py1 = bottom, height - top
    xpos = lambda i: px0 + ((px1 - px0) * (i / (n - 1) if n > 1 else 0.5))
    ypos = lambda v: py0 + (py1 - py0) * ((v - vmin) / (vmax - vmin))
    for k in range(5):
        v = vmin + (vmax - vmin) * k / 4
        y = ypos(v)
        d.add(Line(px0, y, px1, y, strokeColor=colors.HexColor("#e3e8f0"), strokeWidth=0.5))
        d.add(String(px0 - 4, y - 2.5, compact(v), fontName="DV", fontSize=6.5, fillColor=INK2, textAnchor="end"))
    step = max(1, (n + 7) // 8)
    for i, dd in enumerate(dates):
        if i % step == 0 or i == n - 1:
            d.add(String(xpos(i), py0 - 11, mon(dd), fontName="DV", fontSize=6.5, fillColor=INK2, textAnchor="middle"))
    for si, (name, vals, col) in enumerate(series):
        pts = []
        for i, v in enumerate(vals):
            if v is not None:
                pts += [xpos(i), ypos(v)]
        if len(pts) >= 4:
            d.add(PolyLine(pts, strokeColor=col, strokeWidth=1.6))
        for i, v in enumerate(vals):
            if v is not None:
                d.add(Circle(xpos(i), ypos(v), 2.2, fillColor=col, strokeColor=colors.white, strokeWidth=0.6))
        if len(series) == 1 and n <= 8:
            for i, v in enumerate(vals):
                anchor = "start" if (i == 0 and n > 1) else "end" if (i == n - 1 and n > 1) else "middle"
                dx = 2 if anchor == "start" else -2 if anchor == "end" else 0
                d.add(String(xpos(i) + dx, ypos(v) + 5, compact(v), fontName="DV", fontSize=6.5, fillColor=INK, textAnchor=anchor))
    if len(series) > 1:
        x = px0
        for name, _, col in series:
            d.add(Rect(x, 4, 7, 7, fillColor=col, strokeColor=None))
            lab = _trunc(name, "DV", 7, 110)
            d.add(String(x + 10, 4.5, lab, fontName="DV", fontSize=7, fillColor=INK))
            x += 10 + stringWidth(lab, "DV", 7) + 14
    return d


def vbar_chart(labels, values, width, height=140, title=None, colors_=None):
    n = len(values)
    if n == 0:
        return Spacer(1, 1)
    top = 18 if title else 6
    left, bottom = 56, 22
    d = Drawing(width, height)
    if title:
        d.add(String(0, height - 11, title, fontName="DV-B", fontSize=9, fillColor=INK))
    vmax = (max(values) or 1) * 1.06
    plot_w = width - left - 8
    slot = plot_w / n
    bw = min(slot * 0.62, 30)
    for k in range(5):
        v = vmax * k / 4
        y = bottom + (height - top - bottom) * k / 4
        d.add(Line(left, y, width - 8, y, strokeColor=colors.HexColor("#e3e8f0"), strokeWidth=0.5))
        d.add(String(left - 4, y - 2.5, compact(v), fontName="DV", fontSize=6.5, fillColor=INK2, textAnchor="end"))
    for i, v in enumerate(values):
        x = left + slot * i + (slot - bw) / 2
        bh = (height - top - bottom) * v / vmax
        col = (colors_ or {}).get(i, BLUE2)
        d.add(Rect(x, bottom, bw, max(bh, 0.6), fillColor=col, strokeColor=None))
        if i % max(1, n // 12) == 0:
            d.add(String(x + bw / 2, bottom - 10, labels[i], fontName="DV", fontSize=6.5, fillColor=INK2, textAnchor="middle"))
    return d


def _side_by_side(left, right, avail, gap=14):
    w = (avail - gap) / 2
    t = Table([[left(w), right(w)]], colWidths=[w + gap / 2, w + gap / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), gap / 2), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _finish(doc, frame, story):
    buf = doc.filename
    doc.build(story, onFirstPage=frame, onLaterPages=frame, canvasmaker=_NumberedCanvas)
    return buf.getvalue()


# --------------------------------------------------------------------------- PDF reports
def dashboard_pdf(d, matrix, ctx):
    unit = ctx.get("unit", "full")
    buf = io.BytesIO()
    doc, frame, avail = _make_doc(buf, ctx, "Dashboard")
    story = _title_block("Dashboard", [f"Position as on {dmy(d['date'])}  ·  uploaded {dmy(d['uploaded_at'])} by {d['uploaded_by']}",
                                       f"Amounts in {UNIT_NAME[unit]}  ·  active holdings only"], ctx)

    # KPI row
    def kpi(label, value, foot):
        return [P(label, "klabel"), PR(_xml(value), "kvalue"), PR(foot, "kfoot")]
    k1 = kpi("Total investments", amt(d["total"], unit),
             (delta_markup(d["change"], d["change_pct"], unit) + f" vs {dmy(d['prev_date'])}") if d["prev_date"] else "First period")
    m = d["market"]
    if m["n"] > 0:
        k2 = kpi("Gain / (loss) – market-linked", amt(m["gain"], unit),
                 f'<font color="{POSC if m["gain"] >= 0 else NEGC}">{pct(m["gain_pct"], True)}</font> on {_xml(amt(m["invested"], unit))} cost · {m["n"]} of {m["total_n"]} holdings')
    else:
        k2 = kpi("Gain / (loss) – market-linked", "Not available", "Fill Invested Amount in the Excel")
    k3 = kpi("Holdings", inr(d["holdings_count"]), f'{len(d["by_entity"])} entities · {len(d["by_type"])} investment types')
    k4 = kpi("Avg. interest rate", f'{d["avg_rate"]:.2f}%' if d["avg_rate"] is not None else "-",
             f'value-weighted, {d["avg_rate_n"]} interest-bearing holdings')
    kt = Table([[k1, k2, k3, k4]], colWidths=[avail / 4] * 4)
    kt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
                            ("LINEABOVE", (0, 0), (0, 0), 2, BLUE), ("LINEABOVE", (1, 0), (1, 0), 2, RED),
                            ("LINEABOVE", (2, 0), (2, 0), 2, BLUE), ("LINEABOVE", (3, 0), (3, 0), 2, RED),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    story += [kt, Spacer(1, 10)]

    # charts
    tot = d["total"] or 1
    groups = sorted([(g["label"], g["v"]) for g in d["by_group"] if g["v"] and g["v"] > 0], key=lambda x: -x[1])
    labelled = [(f"{lab}  ({v / tot * 100:.1f}%)", v) for lab, v in groups]
    tr = d["trend"]
    story.append(_side_by_side(
        lambda w: hbar_chart(labelled, w, unit, title="Where the money is (by group)", label_w=150),
        lambda w: line_chart(tr["dates"], [("Total investments", tr["total"], BLUE2)], w, 150, "Total investments over time"), avail))
    story.append(Spacer(1, 8))

    # group & entity summary
    def mv_table(rows, title):
        data = [[title, "Value", "% of total", "Previous", "Change"]]
        for r in rows:
            ch = (r["v"] - r["prev"]) if r.get("prev") is not None else None
            chp = (ch / r["prev"] * 100) if (ch is not None and r["prev"]) else None
            data.append([r["label"], num(r["v"], unit), f"{r['v'] / tot * 100:.1f}%", num(r["prev"], unit) if r.get("prev") is not None else "-",
                         PR(delta_markup(ch, chp, unit), "bodyr") if ch is not None else "-"])
        data.append(["Total", num(d["total"], unit), "100.0%", num(d["prev_total"], unit) if d["prev_total"] is not None else "-",
                     PR(delta_markup(d["change"], d["change_pct"], unit), "bodyr") if d["change"] is not None else "-"])
        return _table(data, _fit([100, 72, 44, 72, 108], avail * 0.5 - 8), right_cols=(1, 2, 3, 4), total_last=True, font=7)

    story.append(KeepTogether([P("Movement by group and entity", "h2"),
                               _side_by_side(lambda w: mv_table(d["by_group"], "Investment group"),
                                             lambda w: mv_table(d["by_entity"], "Entity"), avail)]))
    story.append(PageBreak())

    # type movement
    data = [["Investment type", "Value", "% of total", "Previous", "Change", "Change %"]]
    for r in d["by_type"]:
        ch = (r["v"] - r["prev"]) if r.get("prev") is not None else None
        chp = (ch / r["prev"] * 100) if (ch is not None and r["prev"]) else None
        data.append([r["label"], num(r["v"], unit), f"{r['v'] / tot * 100:.1f}%", num(r["prev"], unit) if r.get("prev") is not None else "-",
                     PR(delta_markup(ch, None, unit), "bodyr") if ch is not None else "-", pct(chp, True)])
    data.append(["Total", num(d["total"], unit), "100.0%", num(d["prev_total"], unit) if d["prev_total"] is not None else "-",
                 PR(delta_markup(d["change"], None, unit), "bodyr") if d["change"] is not None else "-", pct(d["change_pct"], True)])
    story.append(KeepTogether([P("Movement by investment type", "h2"),
                               _table(data, _fit([200, 100, 60, 100, 110, 60], avail), right_cols=(1, 2, 3, 4, 5), total_last=True)]))

    # matrix
    if matrix and matrix.get("rows"):
        ents = matrix["entities"]
        head = ["Investment type"] + ents + ["Total"]
        data = [head]
        for r in matrix["rows"]:
            data.append([r["type"]] + [num(v, unit) if v else "-" for v in r["values"]] + [num(r["total"], unit)])
        data.append(["Total"] + [num(v, unit) for v in matrix["col_totals"]] + [num(matrix["grand_total"], unit)])
        story.append(KeepTogether([P(f"Entity-wise summary (as on {dmy(matrix.get('date') or d['date'])})", "h2"),
                                   _table(data, _fit([150] + [90] * len(ents) + [100], avail), right_cols=tuple(range(1, len(head))),
                                          total_last=True, font=7 if len(ents) > 5 else 7.5)]))

    # top 10
    data = [["#", "Entity", "Investment type", "Bank / fund / security", "Account / folio no.", "Value", "% of total"]]
    for i, r in enumerate(d["top"], 1):
        data.append([str(i), r["entity"], r["type"], r["name"], r["account_no"] or "-", num(r["v"], unit), f"{r['v'] / tot * 100:.1f}%"])
    story.append(KeepTogether([P("Top 10 holdings", "h2"), _table(data, _fit([18, 60, 90, 190, 110, 90, 50], avail), right_cols=(5, 6))]))
    return _finish(doc, frame, story)


def compare_pdf(res, ctx):
    unit = ctx.get("unit", "full")
    dates = res["dates"]
    if len(dates) > 7 and unit == "full":
        unit = "lakh"
    buf = io.BytesIO()
    doc, frame, avail = _make_doc(buf, ctx, "Comparison")
    story = _title_block(f"Comparison by {res['by_title']}",
                         [f"Periods: {', '.join(dmy(x) for x in dates)}", f"Amounts in {UNIT_NAME[unit]}  ·  active holdings only"], ctx)
    if not dates or not res["rows"]:
        story.append(P("No data for the selected periods."))
        return _finish(doc, frame, story)
    tr = [("Total investments", [res["totals"][x] for x in dates], BLUE2)]
    ch_items = sorted([(r["label"], r["change"]) for r in res["rows"] if r["change"]], key=lambda x: -abs(x[1]))[:12]
    if len(dates) > 1:
        story.append(_side_by_side(
            lambda w: line_chart(dates, tr, w, 150, "Total across periods"),
            lambda w: hbar_chart(ch_items, w, unit, signed=True, title=f"Change {mon(dates[0])} → {mon(dates[-1])} (largest 12)", label_w=140), avail))
        story.append(Spacer(1, 8))
    head = [res["by_title"]] + [dmy(x) for x in dates] + ["Change", "Change %"]
    data = [head]
    for r in res["rows"]:
        tag = " (new)" if r["status"] == "new" else " (exited)" if r["status"] == "exited" else ""
        data.append([r["label"] + tag] + [num(r["values"][x], unit) if r["values"][x] is not None else "-" for x in dates]
                    + [PR(delta_markup(r["change"], None, unit), "bodyr"), pct(r["pct"], True)])
    data.append(["Total"] + [num(res["totals"][x], unit) for x in dates]
                + [PR(delta_markup(res["total_change"], None, unit), "bodyr"), pct(res["total_pct"], True)])
    n = len(dates)
    widths = _fit([190] + [80] * n + [95, 52], avail)
    story.append(_table(data, widths, right_cols=tuple(range(1, n + 3)), total_last=True, font=7 if n > 5 else 7.5))
    return _finish(doc, frame, story)


def _cap(text, n=46):
    text = " ".join(str(text or "").split())
    return (text[: n - 1] + "…") if len(text) > n else (text or "-")


def _holding_rows_table(rows, avail, unit, show_date=False, total_label="Total active value"):
    head = (["As on"] if show_date else []) + ["Entity", "Investment type", "Bank / fund / security", "Account / folio no.",
                                              "Invested", "Current value", "Gain / (loss)", "Maturity", "Rate"]
    data, grey = [head], []
    total = 0.0
    for r in rows:
        name = r.get("fund") or r.get("bank") or r.get("managed_by") or "-"
        if r.get("fund") and r.get("bank"):
            name += f"  [{r['bank']}]"
        gain = (PR(delta_markup(r["gain"], None, unit), "bodyr")
                if (r.get("gain") is not None and abs(r["gain"]) >= 0.5) else "-")
        ent = r["entity"] + (" (Closed)" if r.get("status") == "Closed" else "")
        line = ([dmy(r["as_on_date"])] if show_date else []) + [ent, r["type"], name, _cap(r.get("account_no")),
                num(r["invested_amount"], unit) if r.get("invested_amount") is not None else "-", num(r["current_value"], unit), gain,
                dmy(r["maturity_date"]) if r.get("maturity_date") else "-", f"{r['interest_rate']:.2f}%" if r.get("interest_rate") is not None else "-"]
        data.append(line)
        if r.get("status") == "Closed":
            grey.append(len(data) - 1)
        elif not show_date:
            total += r["current_value"]
    base = [60, 74, 168, 100, 62, 66, 66, 60, 32]
    if show_date:
        base = [64] + base
    off = 1 if show_date else 0
    right = tuple(range(4 + off, 7 + off)) + (8 + off,)
    if not show_date:
        tot_row = [""] * len(head)
        tot_row[0] = total_label
        tot_row[5 + off] = num(total, unit)
        data.append(tot_row)
    return _table(data, _fit(base, avail), right_cols=right, total_last=not show_date, font=7, grey_rows=grey)


def holdings_pdf(rows, date, ctx):
    unit = ctx.get("unit", "full")
    buf = io.BytesIO()
    doc, frame, avail = _make_doc(buf, ctx, "Holdings")
    story = _title_block(f"Holdings as on {dmy(date)}", [f"{len(rows)} holdings  ·  amounts in {UNIT_NAME[unit]}"], ctx)
    if not rows:
        story.append(P("No holdings match the selection."))
    else:
        story.append(_holding_rows_table(rows, avail, unit))
    return _finish(doc, frame, story)


def maturities_pdf(rows, ladder, date, days, ctx):
    unit = ctx.get("unit", "full")
    buf = io.BytesIO()
    doc, frame, avail = _make_doc(buf, ctx, "Maturities")
    win = "all future maturities" if days >= 36500 else f"maturing within {days} days"
    story = _title_block("Maturities", [f"Position as on {dmy(date)}  ·  {win}  ·  amounts in {UNIT_NAME[unit]}"], ctx)
    total = sum(r["current_value"] for r in rows)
    story.append(P(f"{len(rows)} holdings  ·  current value {amt(total, unit)}", "sub"))
    story.append(Spacer(1, 6))
    if ladder and ladder.get("labels"):
        labs = [mon(k + "-01") for k in ladder["labels"]]
        vals = list(ladder["values"])
        cols = {}
        if ladder.get("past_due"):
            labs = ["Past due"] + labs
            vals = [ladder["past_due"]] + vals
            cols = {0: RED}
        story.append(vbar_chart(labs, vals, avail, 130, "Maturity ladder (value maturing each month)", cols))
        story.append(Spacer(1, 6))
    if not rows:
        story.append(P("Nothing matures in this window."))
        return _finish(doc, frame, story)
    head = ["Entity", "Investment type", "Name", "Account / folio no.", "Current value", "Maturity date", "Days left", "Maturity amount", "Rate", "Auto renew"]
    data = [head]
    grey = []
    for r in rows:
        dl = r["days_left"]
        left = "Overdue" if dl < 0 else str(dl)
        data.append([r["entity"], r["type"], r["name"] + (f"  [{r['bank']}]" if r.get("bank") and r["bank"] != r["name"] else ""),
                     _cap(r.get("account_no")), num(r["current_value"], unit), dmy(r["maturity_date"]), left,
                     num(r["maturity_amount"], unit) if r.get("maturity_amount") is not None else "-",
                     f"{r['interest_rate']:.2f}%" if r.get("interest_rate") is not None else "-", r.get("auto_renewal") or "-"])
    data.append(["Total", "", "", "", num(total, unit)] + [""] * 5)
    story.append(_table(data, _fit([60, 74, 160, 96, 70, 60, 42, 72, 34, 44], avail), right_cols=(4, 6, 7, 8), total_last=True, font=7))
    return _finish(doc, frame, story)


def search_pdf(result, q, date, ctx):
    unit = ctx.get("unit", "full")
    buf = io.BytesIO()
    doc, frame, avail = _make_doc(buf, ctx, "Search results")
    scope = f"as on {dmy(date)}" if date else "across all uploaded dates"
    story = _title_block("Search results", [f"Searched for: “{q}”  ·  {scope}  ·  amounts in {UNIT_NAME[unit]}",
                                            f"{result['count']} holdings found" + ("  (list cut at the first 1000)" if result.get("truncated") else "")], ctx)
    if not result["rows"]:
        story.append(P("Nothing matched."))
    else:
        story.append(_holding_rows_table(result["rows"], avail, unit, show_date=not date, total_label="Total active value"))
    return _finish(doc, frame, story)


# --------------------------------------------------------------------------- Excel (new reports)
HEAD_FILL = PatternFill("solid", fgColor="1F4FA8")
HEAD_FONT = Font(bold=True, color="FFFFFF")
TOT_FILL = PatternFill("solid", fgColor="E8EFFA")
AMT = r'[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00'


def _wb_bytes(wb):
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _sheet_title(ws, title, lines):
    ws["A1"] = title
    ws["A1"].font = Font(size=14, bold=True, color="1F4FA8")
    r = 2
    for ln in lines:
        if ln:
            ws.cell(r, 1, ln).font = Font(color="4A5568")
            r += 1
    return r + 1


def _header(ws, row, heads, widths=None):
    for i, h in enumerate(heads, 1):
        c = ws.cell(row, i, h)
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if widths:
            ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]


def _holding_cols(show_date):
    cols = ([("As on", "as_on_date", 13)] if show_date else []) + [
        ("Entity", "entity", 20), ("Investment Group", "grp", 18), ("Investment Type", "type", 18), ("Bank / Institution", "bank", 24),
        ("Fund / Security", "fund", 38), ("Joint Holder(s)", "joint_holder", 16), ("Nominee", "nominee", 12),
        ("Account / Folio No.", "account_no", 24), ("Start / Issue Date", "start_date", 14), ("Invested Amount", "invested_amount", 16),
        ("Current Value", "current_value", 16), ("Gain / (Loss)", "gain", 16), ("Maturity Date", "maturity_date", 14),
        ("Maturity Amount", "maturity_amount", 16), ("Interest %", "interest_rate", 10), ("Auto Renewal", "auto_renewal", 10),
        ("Status", "status", 9), ("Last Updated", "last_updated", 14), ("Managed By", "managed_by", 16),
        ("Contact Person", "contact_person", 20), ("Contact No.", "contact_no", 16), ("Contact Email", "contact_email", 24),
        ("Remarks", "remarks", 36)]
    return cols


def search_xlsx(result, q, date, ctx):
    wb = Workbook()
    ws = wb.active
    ws.title = "Search results"
    scope = f"as on {dmy(date)}" if date else "across all uploaded dates"
    r0 = _sheet_title(ws, "Search results", [f"Searched for: {q}  ({scope})", f"Generated {dt.datetime.now():%d-%b-%Y %H:%M} by {ctx.get('user', '')}. Amounts in INR.",
                                            ("Filters: " + ctx["filters"]) if ctx.get("filters") else ""])
    cols = _holding_cols(not date)
    _header(ws, r0, [c[0] for c in cols], [c[2] for c in cols])
    for ri, row in enumerate(result["rows"], r0 + 1):
        for ci, (h, k, w) in enumerate(cols, 1):
            v = row.get(k)
            if k in ("start_date", "maturity_date", "last_updated", "as_on_date") and v:
                v = dt.date.fromisoformat(v)
            c = ws.cell(ri, ci, v)
            if k in ("start_date", "maturity_date", "last_updated", "as_on_date"):
                c.number_format = "dd-mmm-yyyy"
            elif k in ("invested_amount", "current_value", "gain", "maturity_amount"):
                c.number_format = AMT
    n = len(result["rows"])
    if n:
        ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(cols))}{r0 + n}"
        ws.freeze_panes = ws.cell(r0 + 1, 1)
    return _wb_bytes(wb)


def maturities_xlsx(rows, ladder, date, days, ctx):
    wb = Workbook()
    ws = wb.active
    ws.title = "Maturities"
    win = "all future maturities" if days >= 36500 else f"maturing within {days} days"
    r0 = _sheet_title(ws, "Maturities", [f"Position as on {dmy(date)}  ·  {win}", f"Generated {dt.datetime.now():%d-%b-%Y %H:%M} by {ctx.get('user', '')}. Amounts in INR.",
                                         ("Filters: " + ctx["filters"]) if ctx.get("filters") else ""])
    heads = ["Entity", "Investment Type", "Name", "Bank / Institution", "Account / Folio No.", "Current Value", "Maturity Date", "Days Left",
             "Maturity Amount", "Interest %", "Auto Renewal"]
    _header(ws, r0, heads, [20, 18, 38, 24, 24, 16, 14, 10, 16, 10, 12])
    for ri, r in enumerate(rows, r0 + 1):
        vals = [r["entity"], r["type"], r["name"], r.get("bank"), r.get("account_no"), r["current_value"],
                dt.date.fromisoformat(r["maturity_date"]), r["days_left"], r.get("maturity_amount"), r.get("interest_rate"), r.get("auto_renewal")]
        for ci, v in enumerate(vals, 1):
            c = ws.cell(ri, ci, v)
            if ci in (6, 9):
                c.number_format = AMT
            elif ci == 7:
                c.number_format = "dd-mmm-yyyy"
    n = len(rows)
    if n:
        tr = r0 + n + 1
        ws.cell(tr, 1, "Total").font = Font(bold=True)
        c = ws.cell(tr, 6, f"=SUM(F{r0 + 1}:F{r0 + n})")
        c.number_format, c.font = AMT, Font(bold=True)
        for ci in range(1, 12):
            ws.cell(tr, ci).fill = TOT_FILL
        ws.auto_filter.ref = f"A{r0}:K{r0 + n}"
        ws.freeze_panes = ws.cell(r0 + 1, 1)
    if ladder and ladder.get("labels"):
        w2 = wb.create_sheet("Maturity ladder")
        _header(w2, 1, ["Month", "Value maturing"], [14, 20])
        rr = 2
        if ladder.get("past_due"):
            w2.cell(rr, 1, "Past due")
            w2.cell(rr, 2, ladder["past_due"]).number_format = AMT
            rr += 1
        first = rr
        for k, v in zip(ladder["labels"], ladder["values"]):
            w2.cell(rr, 1, mon(k + "-01"))
            w2.cell(rr, 2, v).number_format = AMT
            rr += 1
        ch = BarChart()
        ch.type, ch.title, ch.legend = "col", "Maturity ladder", None
        ch.add_data(Reference(w2, min_col=2, min_row=1, max_row=rr - 1), titles_from_data=True)
        ch.set_categories(Reference(w2, min_col=1, min_row=2, max_row=rr - 1))
        ch.height, ch.width = 8, 22
        w2.add_chart(ch, "D2")
    return _wb_bytes(wb)


def dashboard_xlsx(d, matrix, ctx):
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    r0 = _sheet_title(ws, "Dashboard summary", [f"Position as on {dmy(d['date'])}  ·  active holdings only  ·  amounts in INR",
                                                f"Generated {dt.datetime.now():%d-%b-%Y %H:%M} by {ctx.get('user', '')}.",
                                                ("Filters: " + ctx["filters"]) if ctx.get("filters") else ""])
    rows = [("Total investments", d["total"]), (f"Previous total ({dmy(d['prev_date'])})" if d["prev_date"] else "Previous total", d["prev_total"]),
            ("Change", d["change"]), ("Change %", (d["change_pct"] / 100) if d["change_pct"] is not None else None),
            ("Number of holdings", d["holdings_count"]),
            ("Market-linked: invested", d["market"]["invested"] if d["market"]["n"] else None),
            ("Market-linked: current value", d["market"]["current"] if d["market"]["n"] else None),
            ("Market-linked: gain / (loss)", d["market"]["gain"] if d["market"]["n"] else None),
            ("Average interest rate %", d["avg_rate"])]
    for i, (k, v) in enumerate(rows):
        ws.cell(r0 + i, 1, k).font = Font(bold=True)
        c = ws.cell(r0 + i, 2, v)
        if k == "Change %":
            c.number_format = "0.00%"
        elif k == "Number of holdings":
            c.number_format = "0"
        elif k.startswith("Average"):
            c.number_format = "0.00"
        else:
            c.number_format = AMT
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 22

    def block(name, items, label_head):
        w = wb.create_sheet(name)
        _header(w, 1, [label_head, "Value", "% of total", "Previous", "Change", "Change %"], [44, 20, 12, 20, 20, 12])
        tot = d["total"] or 1
        r = 2
        for it in items:
            w.cell(r, 1, it["label"])
            w.cell(r, 2, it["v"]).number_format = AMT
            w.cell(r, 3, it["v"] / tot).number_format = "0.0%"
            if it.get("prev") is not None:
                w.cell(r, 4, it["prev"]).number_format = AMT
                w.cell(r, 5, it["v"] - it["prev"]).number_format = AMT
                if it["prev"]:
                    w.cell(r, 6, (it["v"] - it["prev"]) / it["prev"]).number_format = "0.00%"
            r += 1
        w.cell(r, 1, "Total").font = Font(bold=True)
        c = w.cell(r, 2, f"=SUM(B2:B{r - 1})")
        c.number_format, c.font = AMT, Font(bold=True)
        for ci in range(1, 7):
            w.cell(r, ci).fill = TOT_FILL
        w.freeze_panes = "B2"
        return w, r - 1

    wg, ng = block("By group", d["by_group"], "Investment group")
    ch = BarChart()
    ch.type, ch.title, ch.legend = "bar", "Value by investment group", None
    ch.add_data(Reference(wg, min_col=2, min_row=1, max_row=ng + 1), titles_from_data=True)
    ch.set_categories(Reference(wg, min_col=1, min_row=2, max_row=ng + 1))
    ch.height, ch.width = 9, 20
    wg.add_chart(ch, "H2")
    block("By type", d["by_type"], "Investment type")
    block("By entity", d["by_entity"], "Entity")

    if matrix and matrix.get("rows"):
        wm = wb.create_sheet("Entity-wise")
        ents = matrix["entities"]
        _header(wm, 1, ["Investment type"] + ents + ["Total"], [30] + [18] * (len(ents) + 1))
        for ri, r in enumerate(matrix["rows"], 2):
            wm.cell(ri, 1, r["type"])
            for ci, v in enumerate(r["values"], 2):
                wm.cell(ri, ci, v).number_format = AMT
            wm.cell(ri, len(ents) + 2, r["total"]).number_format = AMT
        tr = len(matrix["rows"]) + 2
        wm.cell(tr, 1, "Total").font = Font(bold=True)
        for ci, v in enumerate(matrix["col_totals"], 2):
            c = wm.cell(tr, ci, v)
            c.number_format, c.font = AMT, Font(bold=True)
        c = wm.cell(tr, len(ents) + 2, matrix["grand_total"])
        c.number_format, c.font = AMT, Font(bold=True)
        for ci in range(1, len(ents) + 3):
            wm.cell(tr, ci).fill = TOT_FILL
        wm.freeze_panes = "B2"

    tr_ = d["trend"]
    wt = wb.create_sheet("Trend")
    groups = tr_["groups"]
    _header(wt, 1, ["As on", "Total"] + [g["name"] for g in groups], [14, 20] + [20] * len(groups))
    for i, dd in enumerate(tr_["dates"]):
        wt.cell(i + 2, 1, dt.date.fromisoformat(dd)).number_format = "dd-mmm-yyyy"
        wt.cell(i + 2, 2, tr_["total"][i]).number_format = AMT
        for gi, g in enumerate(groups):
            wt.cell(i + 2, 3 + gi, g["values"][i]).number_format = AMT
    if len(tr_["dates"]) > 1:
        lc = LineChart()
        lc.title, lc.height, lc.width = "Total investments over time", 9, 22
        lc.add_data(Reference(wt, min_col=2, min_row=1, max_row=len(tr_["dates"]) + 1), titles_from_data=True)
        lc.set_categories(Reference(wt, min_col=1, min_row=2, max_row=len(tr_["dates"]) + 1))
        wt.add_chart(lc, f"{get_column_letter(len(groups) + 4)}2")

    wtop = wb.create_sheet("Top 10")
    _header(wtop, 1, ["#", "Entity", "Investment Type", "Bank / Fund / Security", "Account / Folio No.", "Value", "% of total"], [5, 20, 20, 40, 26, 20, 12])
    for i, r in enumerate(d["top"], 1):
        vals = [i, r["entity"], r["type"], r["name"], r.get("account_no"), r["v"], r["v"] / (d["total"] or 1)]
        for ci, v in enumerate(vals, 1):
            c = wtop.cell(i + 1, ci, v)
            if ci == 6:
                c.number_format = AMT
            elif ci == 7:
                c.number_format = "0.0%"
    return _wb_bytes(wb)
