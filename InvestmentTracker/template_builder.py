"""Build the structured Excel upload template (with dropdowns driven by the Masters)."""
import io
import datetime as dt
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

BLUE = "1F4FA8"
RED = "C62828"
LIGHT = "EAF1FB"
INPUT_FILL = PatternFill("solid", fgColor="FFF8E1")
AMT_FMT = r'[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00'
DATE_FMT = "dd-mmm-yyyy"

# (header, width, required, number format, help)
COLUMNS = [
    ("Entity (First Holder) *", 22, True, None, "Name of the first account holder. Pick from the list."),
    ("Investment Type *", 20, True, None, "Pick from the list (Masters → Investment Types)."),
    ("Bank / Institution", 26, False, None, "Bank / broker / AMC where the investment is held."),
    ("Fund / Security / Scheme Name", 38, False, None, "For mutual funds, PMS, shares, bonds, etc."),
    ("Joint Holder(s)", 18, False, None, "Other holders, for reference only."),
    ("Nominee", 14, False, None, ""),
    ("Account / Folio / Ref No.", 26, False, "@", "Account no., FD no., folio, UAN, demat no."),
    ("Quantity / Units", 14, False, "#,##0.0000", "Shares / units held (optional)."),
    ("Start / Issue Date", 14, False, DATE_FMT, "FD issue date / purchase date."),
    ("Invested Amount (₹)", 18, False, AMT_FMT, "Cost / principal. Leave blank for bank & FD-type items."),
    ("Current Value (₹) *", 18, True, AMT_FMT, "Balance / market value as on the As-On Date."),
    ("Maturity Date", 14, False, DATE_FMT, ""),
    ("Maturity Amount (₹)", 18, False, AMT_FMT, ""),
    ("Interest Rate (% p.a.)", 12, False, "0.00", "Enter 7.25 for 7.25%."),
    ("Auto Renewal", 11, False, None, "Yes / No"),
    ("Status", 10, False, None, "Active / Closed (blank = Active)."),
    ("Last Updated On", 14, False, DATE_FMT, "Date the balance was last confirmed."),
    ("Managed By", 18, False, None, "RM / wealth manager / platform."),
    ("Contact Person", 22, False, None, ""),
    ("Contact No.", 18, False, None, ""),
    ("Contact Email", 26, False, None, ""),
    ("Remarks", 40, False, None, "Any other contact info or notes."),
]
HEADER_ROW = 6
FIRST_DATA_ROW = 7
MAX_ROWS = 600


def build_template(con, sample_rows=None, as_on=None):
    """Return bytes of an .xlsx template. `sample_rows` optionally pre-fills Data (list of dict rows)."""
    entities = [r["name"] for r in con.execute("SELECT name FROM entities WHERE active=1 ORDER BY sort_order, name")]
    types = [r["name"] for r in con.execute("SELECT name FROM investment_types WHERE active=1 ORDER BY sort_order, name")]
    banks = [r["name"] for r in con.execute("SELECT name FROM banks WHERE active=1 ORDER BY name")]
    funds = [r["name"] for r in con.execute("SELECT name FROM funds WHERE active=1 ORDER BY name")]

    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    thin = Side(style="thin", color="C9D3E3")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws["A1"] = "Investment Tracker — Monthly Data Sheet"
    ws["A1"].font = Font(size=16, bold=True, color=BLUE)
    ws["A2"] = "Statement As-On Date *"
    ws["A3"] = "Date of Upload / Prepared On"
    for c in ("A2", "A3"):
        ws[c].font = Font(bold=True, color=BLUE)
    ws["B2"].fill = INPUT_FILL
    ws["B3"].fill = INPUT_FILL
    for c in ("B2", "B3"):
        ws[c].number_format = DATE_FMT
        ws[c].border = Border(left=Side(style="medium", color=RED), right=Side(style="medium", color=RED),
                              top=Side(style="medium", color=RED), bottom=Side(style="medium", color=RED)) \
            if c == "B2" else border
        ws[c].alignment = Alignment(horizontal="center")
    ws["B2"] = as_on if as_on else None
    ws["B3"] = dt.date.today()
    ws["D2"] = "← Enter the date the balances are 'as on' (e.g. month-end 30-Sep-2026). This is the period key used in all reports."
    ws["D3"] = "← The date this file is prepared / uploaded."
    ws["A4"] = ("One row per account / investment. Do NOT add total rows or blank separator rows. "
                "Joint accounts go under the FIRST holder. See the 'Instructions' sheet.")
    ws["A4"].font = Font(italic=True, color=RED)
    for c in ("D2", "D3"):
        ws[c].font = Font(italic=True, color="5F6B7A", size=9)

    for i, (h, w, req, fmt, hlp) in enumerate(COLUMNS, start=1):
        cell = ws.cell(HEADER_ROW, i, h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=RED if req else BLUE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[HEADER_ROW].height = 34
    ws.freeze_panes = ws.cell(FIRST_DATA_ROW, 3)

    last = FIRST_DATA_ROW + MAX_ROWS - 1
    for r in range(FIRST_DATA_ROW, last + 1):
        for i, (h, w, req, fmt, hlp) in enumerate(COLUMNS, start=1):
            c = ws.cell(r, i)
            if fmt:
                c.number_format = fmt
            c.border = border

    # ---- Lists sheet
    ls = wb.create_sheet("Lists")
    heads = ["Entities", "Investment Types", "Banks / Institutions", "Funds / Securities", "Yes/No", "Status"]
    data = [entities, types, banks, funds, ["Yes", "No"], ["Active", "Closed"]]
    for ci, (h, vals) in enumerate(zip(heads, data), start=1):
        ls.cell(1, ci, h).font = Font(bold=True, color="FFFFFF")
        ls.cell(1, ci).fill = PatternFill("solid", fgColor=BLUE)
        ls.column_dimensions[get_column_letter(ci)].width = 40
        for ri, v in enumerate(vals, start=2):
            ls.cell(ri, ci, v)
    ls["H1"] = "These lists are generated from the tool's Masters. Do not edit here — change them in the tool and re-download the template."
    ls["H1"].font = Font(italic=True, color=RED)

    def rng(col, n):
        return f"Lists!${col}$2:${col}${max(n, 1) + 1}"

    def dv(formula, col_letter, stop=True, prompt=None):
        d = DataValidation(type="list", formula1=formula, allow_blank=True)
        d.errorStyle = "stop" if stop else "warning"
        d.showErrorMessage = True
        d.errorTitle = "Not in list"
        d.error = ("Pick a value from the list." if stop else
                   "This name is not in the master list. It will be added to Masters when you upload. Continue?")
        if prompt:
            d.showInputMessage = True
            d.prompt = prompt
        ws.add_data_validation(d)
        d.add(f"{col_letter}{FIRST_DATA_ROW}:{col_letter}{last}")

    dv(rng("A", len(entities)), "A")
    dv(rng("B", len(types)), "B")
    dv(rng("C", len(banks)), "C", stop=False)
    dv(rng("D", len(funds)), "D", stop=False)
    dv(rng("E", 2), "O")
    dv(rng("F", 2), "P")
    nd = DataValidation(type="decimal", operator="between", formula1="-9999999999", formula2="9999999999", allow_blank=True)
    nd.errorTitle, nd.error, nd.showErrorMessage = "Number required", "Enter a number only (no text).", True
    ws.add_data_validation(nd)
    for col in ("J", "K", "M", "N"):
        nd.add(f"{col}{FIRST_DATA_ROW}:{col}{last}")

    # ---- Instructions
    ins = wb.create_sheet("Instructions", 0)
    ins.column_dimensions["A"].width = 34
    ins.column_dimensions["B"].width = 110
    ins["A1"] = "How to fill this sheet"
    ins["A1"].font = Font(size=16, bold=True, color=BLUE)
    rules = [
        "1. Go to the 'Data' sheet. Enter the Statement As-On Date in cell B2 (mandatory) — usually the month-end date.",
        "2. Enter ONE ROW per account / investment (each FD separately, each mutual fund scheme separately, each PMS, etc.).",
        "3. Do NOT enter totals, sub-totals, blank separator rows or formulas that return text — the tool calculates all totals.",
        "4. Entity = the FIRST account holder. Joint accounts are reported under the first holder; put other holders in 'Joint Holder(s)'.",
        "5. Pick Entity and Investment Type from the dropdown. New Banks / Funds typed in are added to Masters automatically.",
        "6. Amounts: enter plain numbers (no ₹, no commas as text). Dates: use real Excel dates, or DD-MM-YYYY.",
        "7. Interest Rate: enter 7.25 for 7.25% p.a.",
        "8. Invested Amount is optional for bank balances, FD, PPF, EPF (taken equal to Current Value). Fill it for mutual funds, "
        "shares, bonds, PMS, gold etc. to see gain / loss.",
        "9. Closed accounts: set Status = Closed (they are excluded from totals) or simply remove the row.",
        "10. Upload the file in the tool → Uploads. You will see a preview with checks before anything is saved. "
        "Uploading the same As-On Date again replaces that month's data (after confirmation).",
    ]
    for i, t in enumerate(rules, start=3):
        ins.cell(i, 1, t).alignment = Alignment(wrap_text=True, vertical="top")
        ins.merge_cells(start_row=i, start_column=1, end_row=i, end_column=2)
        ins.row_dimensions[i].height = 30
    r0 = 3 + len(rules) + 1
    ins.cell(r0, 1, "Column").font = Font(bold=True, color="FFFFFF")
    ins.cell(r0, 1).fill = PatternFill("solid", fgColor=BLUE)
    ins.cell(r0, 2, "What to enter").font = Font(bold=True, color="FFFFFF")
    ins.cell(r0, 2).fill = PatternFill("solid", fgColor=BLUE)
    for i, (h, w, req, fmt, hlp) in enumerate(COLUMNS, start=r0 + 1):
        ins.cell(i, 1, h + ("   (required)" if req else "")).font = Font(bold=req, color=RED if req else "000000")
        ins.cell(i, 2, hlp)

    # ---- optional sample rows
    if sample_rows:
        keys = ["entity", "type", "bank", "fund", "joint_holder", "nominee", "account_no", "quantity", "start_date",
                "invested_amount", "current_value", "maturity_date", "maturity_amount", "interest_rate",
                "auto_renewal", "status", "last_updated", "managed_by", "contact_person", "contact_no",
                "contact_email", "remarks"]
        for ri, row in enumerate(sample_rows, start=FIRST_DATA_ROW):
            for ci, k in enumerate(keys, start=1):
                v = row.get(k)
                if v is None:
                    continue
                if k in ("start_date", "maturity_date", "last_updated") and isinstance(v, str):
                    v = dt.date.fromisoformat(v)
                ws.cell(ri, ci, v)

    wb.move_sheet("Data", offset=-wb.index(wb["Data"]) + 1)
    wb.active = wb.index(wb["Data"])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
