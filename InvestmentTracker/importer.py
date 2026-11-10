"""Excel upload: parse + validate the structured template, then commit to SQLite."""
import re
import difflib
import datetime as dt
import openpyxl
from openpyxl.utils.datetime import from_excel

# header text (normalised) -> internal field
HEADER_ALIASES = {
    "entity": "entity", "entityfirstholder": "entity", "firstholder": "entity",
    "accountholder": "entity", "entityfirstaccountholder": "entity",
    "investmenttype": "type", "type": "type", "accounttype": "type",
    "bankinstitution": "bank", "bank": "bank", "institution": "bank", "bankinstitutionheldwith": "bank",
    "fundsecurityschemename": "fund", "fundname": "fund", "fund": "fund", "security": "fund",
    "fundsecurityname": "fund",
    "jointholders": "joint_holder", "jointholder": "joint_holder",
    "nominee": "nominee",
    "accountfolioreferenceno": "account_no", "accountfoliorefno": "account_no", "refno": "account_no", "accountno": "account_no", "accountfolionumber": "account_no",
    "accountfolioref": "account_no", "folionoaccountno": "account_no",
    "quantityunits": "quantity", "quantity": "quantity", "units": "quantity",
    "startissuedate": "start_date", "issuedate": "start_date", "fdissuedate": "start_date", "startdate": "start_date",
    "investedamount": "invested_amount", "investedamountrs": "invested_amount", "costamount": "invested_amount",
    "currentvalue": "current_value", "currentvaluers": "current_value", "balanceprinciple": "current_value",
    "balanceprincipal": "current_value", "value": "current_value",
    "maturitydate": "maturity_date",
    "maturityamount": "maturity_amount", "maturityamountrs": "maturity_amount",
    "interestrate": "interest_rate", "interestratepa": "interest_rate",
    "autorenewal": "auto_renewal",
    "status": "status",
    "lastupdatedon": "last_updated", "lastupdated": "last_updated",
    "managedby": "managed_by",
    "contactperson": "contact_person",
    "contactno": "contact_no", "contactnumber": "contact_no",
    "contactemail": "contact_email", "contactmailid": "contact_email",
    "remarks": "remarks", "notes": "remarks",
}
REQUIRED = ["entity", "type", "current_value"]


def _norm_header(s):
    s = str(s or "").lower()
    s = re.sub(r"\(.*?\)", "", s)  # drop bracketed hints like (Rs) (% p.a.)
    s = s.replace("₹", "").replace("*", "")
    return re.sub(r"[^a-z0-9]", "", s)


def _blank(v):
    return v is None or (isinstance(v, str) and v.strip() in ("", "-", "--", "—", "NA", "N/A", "na", "n/a"))


def parse_number(v):
    if _blank(v):
        return None
    if isinstance(v, bool):
        raise ValueError("not a number")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("\xa0", " ").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"(?i)(rs\.?|inr|₹)", "", s)
    s = s.replace(",", "").replace(" ", "").strip("()")
    if s.endswith("%"):
        s = s[:-1]
    try:
        n = float(s)
    except ValueError:
        raise ValueError(f"'{v}' is not a valid number")
    return -n if neg else n


_DATE_FORMATS = ["%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y",
                 "%d/%m/%y", "%d-%m-%y", "%d.%m.%y", "%d %B %Y"]


def parse_date(v):
    if _blank(v):
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 20000 < v < 80000:
        return from_excel(v).date().isoformat()
    s = str(v).strip()
    for f in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"'{v}' is not a recognisable date (use DD-MM-YYYY)")


def _text(v):
    if _blank(v):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"[ \t]+", " ", str(v).replace("\xa0", " ").replace("\n", " ")).strip()


def _find_labelled(ws, label_regex, max_row=12, max_col=12):
    """Find a label cell in the top rows and return the first DATE-like cell to its right.
    Explanatory text next to a blank input cell is ignored."""
    for r in range(1, max_row + 1):
        for c in range(1, max_col + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and re.search(label_regex, v, re.I) and len(v) < 60:
                for c2 in range(c + 1, c + 4):
                    val = ws.cell(r, c2).value
                    if _blank(val):
                        continue
                    if isinstance(val, (dt.datetime, dt.date, int, float)):
                        return val
                    try:
                        parse_date(val)
                        return val
                    except ValueError:
                        if len(str(val)) < 25:   # looks like a mistyped date, report it
                            return val
    return None


def _compress_warnings(warns, limit=3):
    """Collapse 'Row N: <same message>' repeated on many rows into a single line."""
    groups, order, other = {}, [], []
    for w in warns:
        m = re.match(r"^Row (\d+): (.*)$", w)
        if not m:
            other.append(w)
            continue
        msg = re.sub(r"\(#\d+\)", "", m.group(2))
        if msg not in groups:
            groups[msg] = []
            order.append(msg)
        groups[msg].append((int(m.group(1)), w))
    out = list(other)
    for msg in order:
        items = groups[msg]
        if len(items) <= limit:
            out += [w for _, w in items]
        else:
            rows = [str(n) for n, _ in items]
            out.append(f"{len(items)} rows (e.g. rows {', '.join(rows[:6])}{'…' if len(rows) > 6 else ''}): {msg}")
    return out


def make_key(entity_id, type_id, bank, fund, account_no):
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return "|".join([str(entity_id), str(type_id), norm(bank), norm(fund), norm(account_no)])


def parse_workbook(path, con):
    """Return a dict: as_on, prepared_on, rows, errors, warnings, new_banks, new_funds."""
    result = {"as_on": None, "prepared_on": None, "rows": [], "errors": [], "warnings": [],
              "new_banks": [], "new_funds": []}
    err, warn = result["errors"], result["warnings"]
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:  # noqa
        err.append(f"Could not open the file as an Excel workbook: {e}")
        return result

    ws = None
    for name in wb.sheetnames:
        if name.strip().lower() == "data":
            ws = wb[name]
            break
    if ws is None:
        ws = wb[wb.sheetnames[0]]
        warn.append(f"No sheet named 'Data' found; reading the first sheet '{ws.title}'.")

    # --- as-on date / prepared date
    raw_as_on = _find_labelled(ws, r"as[\s\-]*on")
    try:
        result["as_on"] = parse_date(raw_as_on)
    except ValueError as e:
        err.append(f"Statement As-On Date: {e}")
    if not result["as_on"] and not any("As-On Date" in e for e in err):
        err.append("Statement As-On Date is missing. Fill the 'Statement As-On Date' cell at the top of the Data sheet "
                   "(e.g. 30-09-2026).")
    try:
        result["prepared_on"] = parse_date(_find_labelled(ws, r"(upload|prepared)"))
    except ValueError:
        result["prepared_on"] = None
    if result["as_on"]:
        if result["as_on"] > dt.date.today().isoformat():
            err.append(f"As-On Date {result['as_on']} is in the future.")

    # --- header row
    hdr_row, colmap = None, {}
    for r in range(1, 25):
        found = {}
        for c in range(1, ws.max_column + 1):
            f = HEADER_ALIASES.get(_norm_header(ws.cell(r, c).value))
            if f and f not in found:
                found[f] = c
        if "entity" in found and "type" in found and "current_value" in found:
            hdr_row, colmap = r, found
            break
    if hdr_row is None:
        err.append("Could not find the header row. It must contain at least: Entity, Investment Type, Current Value. "
                   "Please use the template downloaded from this tool.")
        return result

    # --- masters
    entities = {r["name"].lower(): r for r in con.execute("SELECT * FROM entities WHERE active=1")}
    types = {r["name"].lower(): r for r in con.execute(
        "SELECT t.*, g.name AS group_name FROM investment_types t JOIN investment_groups g ON g.id=t.group_id WHERE t.active=1")}
    banks = {r["name"].lower(): r["name"] for r in con.execute("SELECT name FROM banks")}
    funds = {r["name"].lower(): r["name"] for r in con.execute("SELECT name FROM funds")}
    new_banks, new_funds = {}, {}

    seen = {}
    key_count = {}
    for r in range(hdr_row + 1, ws.max_row + 1):
        raw = {f: ws.cell(r, c).value for f, c in colmap.items()}
        if all(_blank(v) for v in raw.values()):
            continue
        tag = f"Row {r}"
        row_errs = []

        def add_err(msg):
            row_errs.append(msg)
            err.append(f"{tag}: {msg}")

        # entity
        ent_txt = _text(raw.get("entity"))
        ent = None
        if not ent_txt:
            add_err("Entity is blank.")
        else:
            ent = entities.get(ent_txt.lower())
            if not ent:
                sug = difflib.get_close_matches(ent_txt.lower(), list(entities), n=1, cutoff=0.6)
                hint = f" Did you mean '{entities[sug[0]]['name']}'?" if sug else ""
                add_err(f"Entity '{ent_txt}' is not in Masters → Entities.{hint}")
        # type
        typ_txt = _text(raw.get("type"))
        typ = None
        if not typ_txt:
            add_err("Investment Type is blank.")
        else:
            typ = types.get(typ_txt.lower())
            if not typ:
                sug = difflib.get_close_matches(typ_txt.lower(), list(types), n=1, cutoff=0.6)
                hint = f" Did you mean '{types[sug[0]]['name']}'?" if sug else ""
                add_err(f"Investment Type '{typ_txt}' is not in Masters → Investment Types.{hint}")

        # numbers
        def num(field, label, required=False):
            try:
                v = parse_number(raw.get(field))
            except ValueError as e:
                add_err(f"{label}: {e}")
                return None
            if required and v is None and raw.get(field) is None:
                add_err(f"{label} is blank (enter 0 if nil).")
            return v

        cur = num("current_value", "Current Value", required=True)
        if cur is None and raw.get("current_value") is not None and _blank(raw.get("current_value")):
            add_err("Current Value is blank (enter 0 if nil).")
        inv = num("invested_amount", "Invested Amount")
        mat_amt = num("maturity_amount", "Maturity Amount")
        qty = num("quantity", "Quantity / Units")
        rate = num("interest_rate", "Interest Rate")
        if rate is not None:
            if 0 < abs(rate) <= 1:
                warn.append(f"{tag}: Interest rate {rate} looks like a fraction; stored as {round(rate * 100, 4)}% p.a.")
                rate = rate * 100
            if rate < 0 or rate > 40:
                warn.append(f"{tag}: Interest rate {rate}% looks unusual — please check.")

        def dte(field, label):
            try:
                return parse_date(raw.get(field))
            except ValueError as e:
                add_err(f"{label}: {e}")
                return None

        start = dte("start_date", "Start / Issue Date")
        mdate = dte("maturity_date", "Maturity Date")
        lupd = dte("last_updated", "Last Updated On")

        status = (_text(raw.get("status")) or "Active").title()
        if status not in ("Active", "Closed"):
            add_err(f"Status must be Active or Closed (found '{status}').")
        renew = _text(raw.get("auto_renewal"))
        if renew:
            if renew.lower() in ("yes", "y", "true"):
                renew = "Yes"
            elif renew.lower() in ("no", "n", "false"):
                renew = "No"
            else:
                warn.append(f"{tag}: Auto Renewal '{renew}' should be Yes or No.")

        bank = _text(raw.get("bank"))
        fund = _text(raw.get("fund"))
        if bank:
            if bank.lower() in banks:
                bank = banks[bank.lower()]
            else:
                new_banks[bank.lower()] = bank
        if fund:
            if fund.lower() in funds:
                fund = funds[fund.lower()]
            else:
                new_funds[fund.lower()] = fund

        if typ and not bank and not fund and not _text(raw.get("managed_by")) and not _text(raw.get("account_no")):
            warn.append(f"{tag}: Neither Bank / Institution nor Fund / Security is given for '{typ['name']}'.")
        if cur is not None and cur < 0:
            warn.append(f"{tag}: Negative Current Value ({cur:,.2f}).")
        if start and mdate and mdate < start:
            warn.append(f"{tag}: Maturity Date is earlier than Start / Issue Date.")
        if typ and typ["name"] in ("Fixed Deposit", "Bond", "Debenture") and not mdate and status == "Active":
            warn.append(f"{tag}: {typ['name']} without a Maturity Date.")
        if status == "Closed" and cur:
            warn.append(f"{tag}: Closed holding still carries a value ({cur:,.2f}); it is excluded from all totals.")
        if result["as_on"] and lupd and lupd > result["as_on"]:
            warn.append(f"{tag}: Last Updated On is after the As-On Date.")

        if row_errs or not ent or not typ:
            continue
        if inv is None and typ["cost_equals_value"]:
            inv = cur

        account_no = _text(raw.get("account_no"))
        base_key = make_key(ent["id"], typ["id"], bank, fund, account_no)
        n = key_count.get(base_key, 0) + 1
        key_count[base_key] = n
        if n > 1:
            warn.append(f"{tag}: Same Entity / Type / Bank / Fund / Account No. as an earlier row — "
                        f"treated as a separate holding (#{n}). Check for accidental duplicates.")
        hkey = base_key if n == 1 else f"{base_key}#{n}"

        result["rows"].append({
            "excel_row": r, "entity_id": ent["id"], "entity": ent["name"], "type_id": typ["id"], "type": typ["name"],
            "group": typ["group_name"], "bank": bank, "fund": fund,
            "joint_holder": _text(raw.get("joint_holder")), "nominee": _text(raw.get("nominee")),
            "managed_by": _text(raw.get("managed_by")), "account_no": account_no, "quantity": qty,
            "start_date": start, "invested_amount": inv, "current_value": cur if cur is not None else 0.0,
            "maturity_date": mdate, "maturity_amount": mat_amt, "interest_rate": rate, "auto_renewal": renew,
            "status": status, "last_updated": lupd, "contact_person": _text(raw.get("contact_person")),
            "contact_no": _text(raw.get("contact_no")), "contact_email": _text(raw.get("contact_email")),
            "remarks": _text(raw.get("remarks")), "holding_key": hkey,
        })

    result["warnings"] = _compress_warnings(result["warnings"])
    result["new_banks"] = sorted(new_banks.values())
    result["new_funds"] = sorted(new_funds.values())
    if not result["rows"] and not err:
        err.append("No data rows found below the header row.")
    return result


def summarise(rows):
    """Totals by entity and by group for the preview (active rows only)."""
    by_entity, by_group = {}, {}
    total = 0.0
    for r in rows:
        if r["status"] != "Active":
            continue
        by_entity[r["entity"]] = by_entity.get(r["entity"], 0) + r["current_value"]
        by_group[r["group"]] = by_group.get(r["group"], 0) + r["current_value"]
        total += r["current_value"]
    return {"total": total, "by_entity": by_entity, "by_group": by_group}


def commit(con, parsed, username, filename, stored_file, replace=False, note=None):
    """Write parsed rows into the DB. Returns upload id."""
    as_on = parsed["as_on"]
    existing = con.execute("SELECT id FROM uploads WHERE as_on_date=?", (as_on,)).fetchone()
    if existing:
        if not replace:
            raise ValueError("Data for this As-On Date already exists.")
        con.execute("DELETE FROM holdings WHERE upload_id=?", (existing["id"],))
        con.execute("DELETE FROM uploads WHERE id=?", (existing["id"],))

    for b in parsed["new_banks"]:
        con.execute("INSERT OR IGNORE INTO banks(name) VALUES (?)", (b,))
    for f in parsed["new_funds"]:
        con.execute("INSERT OR IGNORE INTO funds(name) VALUES (?)", (f,))
    bank_id = {r["name"].lower(): r["id"] for r in con.execute("SELECT id,name FROM banks")}
    fund_id = {r["name"].lower(): r["id"] for r in con.execute("SELECT id,name FROM funds")}

    s = summarise(parsed["rows"])
    cur = con.execute(
        "INSERT INTO uploads(as_on_date, prepared_on, uploaded_at, uploaded_by, filename, stored_file, row_count, total_value, note) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (as_on, parsed.get("prepared_on"), dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username, filename,
         stored_file, len(parsed["rows"]), s["total"], note))
    uid = cur.lastrowid
    for r in parsed["rows"]:
        con.execute(
            """INSERT INTO holdings(upload_id, as_on_date, entity_id, type_id, bank_id, fund_id, joint_holder, nominee,
               managed_by, account_no, quantity, start_date, invested_amount, current_value, maturity_date,
               maturity_amount, interest_rate, auto_renewal, status, last_updated, contact_person, contact_no,
               contact_email, remarks, holding_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, as_on, r["entity_id"], r["type_id"],
             bank_id.get(r["bank"].lower()) if r["bank"] else None,
             fund_id.get(r["fund"].lower()) if r["fund"] else None,
             r["joint_holder"], r["nominee"], r["managed_by"], r["account_no"], r["quantity"], r["start_date"],
             r["invested_amount"], r["current_value"], r["maturity_date"], r["maturity_amount"], r["interest_rate"],
             r["auto_renewal"], r["status"], r["last_updated"], r["contact_person"], r["contact_no"],
             r["contact_email"], r["remarks"], r["holding_key"]))
    return uid
