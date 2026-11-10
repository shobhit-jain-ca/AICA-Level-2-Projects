"""Convert the client's old multi-sheet tracker into the new structured upload template.

    python tools/migrate_sample.py OLD.xlsx NEW.xlsx [--seed-masters]

* Nothing is silently 'corrected': every judgement call is written to the 'Review Notes' sheet.
* --seed-masters also creates the entities / banks / funds found in the file in the database
  pointed to by IT_DATA_DIR (used for testing).
"""
import os
import re
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

import db
import importer
import template_builder

TYPE_MAP = {
    "sav a/c": "Savings Account", "ca a/c": "Current Account", "fd": "Fixed Deposit", "debt fund": "Debt Fund",
    "liquid fund": "Liquid Fund", "equity fund": "Equity Fund", "bond": "Bond", "pms": "PMS",
    "equity shares": "Equity Shares", "ppf": "PPF", "epf": "EPF", "immovable property attached": "Immovable Property",
}
BANK_TYPES = {"Savings Account", "Current Account", "Fixed Deposit", "PPF"}
SHEET_ENTITY = {"AAA": ("AAA", "Individual"), "BBB": ("BBB", "Individual"), "CCC": ("CCC", "Individual"),
                "AAA HUF": ("AAA HUF", "HUF"), "ABCPL": ("ABCPL", "Company")}
EXTRA_ENTITIES = {"BPL": "Company"}
SUMMARY_SKIP = {"Summary"}


def clean(v):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v).replace("\xa0", " ")).strip()
    return s or None


def strip_prefix(s, pat):
    s = clean(s)
    return clean(re.sub(pat, "", s, flags=re.I)) if s else None


def main(src, dst, seed):
    wb = openpyxl.load_workbook(src, data_only=True)
    rows, notes = [], []
    as_on = None
    src_totals = {}
    for ws in wb:
        if ws.title in SUMMARY_SKIP or ws.title not in SHEET_ENTITY:
            continue
        sheet_entity = SHEET_ENTITY[ws.title][0]
        hdr = None
        for r in range(1, 12):
            if clean(ws.cell(r, 1).value) == "Account type":
                hdr = r
                break
        if hdr is None:
            notes.append(("Info", ws.title, "", f"Header row not found – sheet skipped."))
            continue
        if ws.title == "AAA" and isinstance(ws["O3"].value, dt.datetime):
            as_on = ws["O3"].value.date()
        sheet_sum = 0.0
        for r in range(hdr + 1, ws.max_row + 1):
            label = clean(ws.cell(r, 1).value)
            g = clean(ws.cell(r, 7).value)
            if any((clean(ws.cell(r, c).value) or "").lower() == "grand total" for c in (5, 6, 7)):
                v = ws.cell(r, 8).value
                src_totals[ws.title] = v if isinstance(v, (int, float)) else None
            if not label or label.lower() not in TYPE_MAP:
                continue
            typ = TYPE_MAP[label.lower()]
            ref = f"{ws.title}!R{r}"
            D, E = clean(ws.cell(r, 4).value), clean(ws.cell(r, 5).value)
            F = clean(ws.cell(r, 6).value)
            holder = clean(ws.cell(r, 2).value) or ""
            nominee = clean(ws.cell(r, 3).value)
            if nominee == "-":
                nominee = None
            parts = [p.strip() for p in holder.split("/")]
            first, joint = parts[0], ("/".join(parts[1:]) or None)

            entity = sheet_entity
            if first.upper() in EXTRA_ENTITIES and ws.title == "CCC":
                entity = first.upper()
                joint = None
                if not any(n[0] == "Assumption" for n in notes):
                    notes.append(("Assumption", "CCC (rows with holder 'BPL')", "", "Rows whose holder is 'BPL' on sheet CCC were placed under a separate "
                                  "entity 'BPL' (company) – you mentioned 2 companies and 1 HUF. Confirm, or change the Entity column to CCC."))
            elif first and first != sheet_entity and not sheet_entity.startswith(first):
                notes.append(("Check", ref, "", f"First holder is '{holder}' but the row sits on sheet '{ws.title}'. "
                              f"Placed under '{sheet_entity}' – confirm who the first holder is."))

            # value
            raw_h = ws.cell(r, 8).value
            val = None
            if isinstance(raw_h, (int, float)):
                val = float(raw_h)
            elif raw_h is not None and clean(raw_h) not in (None, "-"):
                try:
                    val = importer.parse_number(raw_h)
                    notes.append(("Fixed", ref, str(raw_h), f"Amount was stored as TEXT in the old sheet; read as {val:,.2f}. "
                                  f"This is why the old Excel total showed #VALUE! / excluded it. Please verify the figure."))
                except ValueError:
                    notes.append(("Error", ref, str(raw_h), "Could not read amount."))
            if val is None:
                val = 0.0
                notes.append(("Check", ref, str(raw_h), "Amount was blank / '-' – set to 0."))
            sheet_sum += val

            # dates
            def d(c):
                v = ws.cell(r, c).value
                return v.date().isoformat() if isinstance(v, dt.datetime) else None
            start, lupd = d(7), d(9)
            mat = None
            kv = ws.cell(r, 11).value
            if isinstance(kv, dt.datetime):
                mat = kv.date().isoformat()
            elif isinstance(kv, str):
                m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", kv)
                if m:
                    mat = dt.date(int(m[3]), int(m[2]), int(m[1])).isoformat()
                    notes.append(("Fixed", ref, kv, f"Maturity date typed as text; read as {mat}."))
            mamt = ws.cell(r, 10).value
            remarks_parts = []
            if isinstance(mamt, str) and mamt.strip():
                mm = re.search(r"maturity\s+(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", mamt, flags=re.I)
                if mm and not mat:
                    mat = dt.date(int(mm[3]), int(mm[2]), int(mm[1])).isoformat()
                    notes.append(("Fixed", ref, mamt, f"Maturity date was typed as text in the 'Maturity Amount' column; read as {mat}."))
                else:
                    remarks_parts.append(clean(mamt))
                mamt = None
            elif not isinstance(mamt, (int, float)):
                mamt = None
            elif typ not in ("Fixed Deposit", "Bond") and mamt == 0:
                mamt = None
            rate = ws.cell(r, 12).value
            rate = float(rate) if isinstance(rate, (int, float)) else None
            if rate is not None and rate <= 1:
                rate = round(rate * 100, 4)
                notes.append(("Fixed", ref, "", f"Interest rate stored as a fraction; converted to {rate}% p.a."))
            renew = clean(ws.cell(r, 13).value)
            renew = {"YES": "Yes", "NO": "No"}.get((renew or "").upper(), renew)

            status = "Active"
            low = " ".join(remarks_parts).lower()
            if "closed" in low:
                status = "Closed"
                if val:
                    notes.append(("Check", ref, f"{val:,.2f}", "Account marked closed in the old sheet but still carries a balance; "
                                  "status set to Closed so it is excluded from totals. Confirm."))

            # bank / fund
            qty = None
            if typ in BANK_TYPES:
                bank = D if typ != "PPF" else (E or D)
                fund = None
                managed = E if (E and D and E.lower() != D.lower() and typ != "PPF") else None
            else:
                fund = D
                bank = E if typ != "EPF" else None
                managed = None
                if typ == "EPF":
                    fund = None
                    managed = E
            m = re.fullmatch(r"([\d,]+) Shares?", F or "", flags=re.I)
            if m:
                qty = float(m[1].replace(",", ""))
                F = None

            cp = clean(ws.cell(r, 14).value)
            cno = clean(ws.cell(r, 15).value)
            mail = clean(ws.cell(r, 16).value)
            oth = clean(ws.cell(r, 17).value)
            if cp and cp.upper() == "REGULAR FD":
                remarks_parts.append("Regular FD")
                cp = None
            cp = strip_prefix(cp, r"^contact person\s*:\s*")
            if cno and re.fullmatch(r"\d{1,2}", cno):
                cno = None
            cno = strip_prefix(cno, r"^contact no\.?\s*:\s*")
            mail = strip_prefix(mail, r"^e-?mail\s*(id)?\s*:\s*")
            if oth:
                remarks_parts.append(oth)

            rows.append(dict(entity=entity, type=typ, bank=bank, fund=fund, joint_holder=joint, nominee=nominee,
                             account_no=F, quantity=qty, start_date=start, invested_amount=None, current_value=val,
                             maturity_date=mat, maturity_amount=mamt, interest_rate=rate, auto_renewal=renew,
                             status=status, last_updated=lupd, managed_by=managed, contact_person=cp, contact_no=cno,
                             contact_email=mail, remarks="; ".join(remarks_parts) or None, _ref=ref, _sheet=ws.title))

            # classification sanity hints (never changed automatically)
            nm = (fund or "").lower()
            if typ == "Equity Fund" and re.search(r"liquid|debt|bond|psu|gilt|banking", nm):
                notes.append(("Check", ref, fund, "Tagged 'Equity Fund' but the name looks like a debt / liquid fund. Classification NOT changed."))
            if typ == "Debt Fund" and re.search(r"arbitrage", nm):
                notes.append(("Check", ref, fund, "Tagged 'Debt Fund' but this is an arbitrage fund (equity-oriented for tax). Classification NOT changed."))
            if typ == "Equity Fund" and re.search(r"arbitrage", nm):
                notes.append(("Info", ref, fund, "Arbitrage fund tagged 'Equity Fund' – consistent with equity taxation but note SBI arbitrage is tagged 'Debt Fund' elsewhere."))
            if typ == "Equity Fund" and re.search(r"pvt|private|limited|ltd", nm):
                notes.append(("Check", ref, fund, "Tagged 'Equity Fund' but name looks like a company, not a fund. Classification NOT changed."))
            if typ == "EPF" and val > 50_000_000:
                notes.append(("Check", ref, f"{val:,.0f}", "Unusually large EPF balance (₹ 27 crore+) – verify the figure; may be a typing error."))

        notes.append(("Info", ws.title, "", f"Sheet total of rows read = {sheet_sum:,.2f}; old sheet Grand Total = "
                      f"{src_totals.get(ws.title) if src_totals.get(ws.title) is not None else 'ERROR (#VALUE!/blank)'}"))

    if seed:
        db.init_db()
        con = db.connect()
        for n, t in {**{v[0]: v[1] for v in SHEET_ENTITY.values()}, **EXTRA_ENTITIES}.items():
            con.execute("INSERT OR IGNORE INTO entities(name, entity_type, sort_order) VALUES (?,?,?)", (n, t, 10 + len(n)))
        for r in rows:
            for k, tab in (("bank", "banks"), ("fund", "funds")):
                if r[k]:
                    con.execute(f"INSERT OR IGNORE INTO {tab}(name) VALUES (?)", (r[k],))
        con.commit()
    else:
        db.init_db()
        con = db.connect()
        con.close()
        con = db.connect()
    data = template_builder.build_template(con, sample_rows=rows, as_on=as_on)
    con.close()

    # add a Review Notes sheet to the generated workbook
    import io
    wb2 = openpyxl.load_workbook(io.BytesIO(data))
    ws2 = wb2.create_sheet("Review Notes")
    ws2.append(["Type", "Where (old sheet!row)", "Value", "Note"])
    for c in ws2[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4FA8")
    order = {"Check": 0, "Assumption": 1, "Fixed": 2, "Info": 3, "Error": 0}
    for n in sorted(notes, key=lambda x: order.get(x[0], 9)):
        ws2.append(list(n))
    for col, w in zip("ABCD", (12, 22, 26, 120)):
        ws2.column_dimensions[col].width = w
    wb2.save(dst)
    print(f"{len(rows)} rows, {len(notes)} notes, as-on {as_on}")
    return rows, notes, src_totals


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--seed-masters" in sys.argv)
