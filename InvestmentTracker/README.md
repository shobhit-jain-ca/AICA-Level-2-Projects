# Investment Tracker

A web tool for tracking a family's investments across individuals, companies and HUFs.
The accountant uploads one Excel file each month. The client opens the tool in Chrome (desktop or mobile) and sees dashboards, period-to-period comparisons, a holdings register and a maturity calendar.

* Python 3 + Flask, SQLite database, no other software needed.
* All data stays on your RDP server in `C:\InvestmentTracker\data`.
* White, clean interface in blue and red. Works on desktop and mobile.

---

## 1. Install on the RDP server (about 10 minutes, one time)

1. Install **Python 3.9 or newer** from python.org. Tick **"Add python.exe to PATH"** and **"Install for all users"**.
2. Copy this whole folder to the server (anywhere, e.g. the Desktop) and unzip it.
3. Right-click **`INSTALL.bat` → Run as administrator**. It will:
   * copy the app to `C:\InvestmentTracker` and install the needed packages,
   * ask you to create the **administrator** login,
   * open the Windows Firewall for port **8080**,
   * register a background task so the app **starts automatically with Windows** (even if nobody is logged in),
   * put an **"Investment Tracker" icon on the desktop of every Windows user** (it starts the app if needed and opens it in **Chrome**).
4. Double-click the desktop icon. Log in with the administrator account.

> The icon works for **all Windows users** of the server, not only Administrator. The data folder is given write permission to the `Users` group.

Re-running `INSTALL.bat` later upgrades the program and **keeps your data**.

## 2. Open it from anywhere in the world (incl. mobile)

The app listens on port **8080**. Clients open `http://<server public IP>:8080`.

Do these two things once:

1. **Open the port outside Windows too.**
   * Cloud/VPS server: add an *inbound TCP 8080* rule in the provider's firewall / security group.
   * Office server behind a router: forward *TCP 8080* to the server's local IP.
2. **Use a static public IP**, or a dynamic-DNS name, so the address does not change.

The installer saves `C:\InvestmentTracker\SendToClient\Investment Tracker.url` (if the server could detect its public IP). Send this to the client; double-clicking it opens the site in their browser.

**On a phone:** open the address in Chrome → menu (⋮) → *Add to Home screen*. It then appears as an icon like an app.

The tool only works while the RDP server is switched on and connected to the internet.

### Security: please read
* Every page needs a login. Passwords are stored hashed; 5 wrong attempts lock that user/IP for 10 minutes; all uploads, deletions and logins are recorded under **Activity Log**.
* Plain `http` is **not encrypted**, so passwords and figures travel in readable form over the internet. For financial data it is strongly recommended to turn on HTTPS: run **`enable_https.bat`** as administrator and enter the public IP or domain name. This creates a self-signed certificate (browsers show a one-time "not secure" warning that the client must accept once). With a real domain name you can instead put a trusted certificate's `cert.pem` / `key.pem` into `C:\InvestmentTracker\data` and set `"https": true` in `data\config.json`.
* Use strong passwords, create a separate login for each person, and deactivate users who no longer need access (Masters → Users).

## 3. Monthly routine (for the accountant)

1. Log in → **Upload Data** → *Download blank template* (it always contains the latest dropdown lists).
2. Fill the **Data** sheet: enter the **Statement As-On Date** in cell **B2** (usually month-end) and the **date of upload** in B3, then **one row per account / investment**.
   *Entity = the first account holder.* Joint accounts go under the first holder; other holders are typed in "Joint Holder(s)".
3. Upload the file. A **preview** shows errors (must fix), warnings, totals by entity and the change versus the previous month, so a typing mistake is caught *before* saving.
4. Click **Save**. If that As-On date already exists you must tick *replace*; a backup is taken first.

Nothing needs to be re-keyed for old months; each upload is a snapshot, and reports compare snapshots.

## 4. What the client sees

| Page | What it shows |
|---|---|
| **Dashboard** | Total value, change vs previous month, gain/(loss), holdings count, average interest rate; allocation by group, total over time, group mix over time, by entity; entity-wise summary table (like the old *Summary* sheet); movement by type; top 10 holdings |
| **Compare Periods** | Choose any periods (Last 2/3/6/12/All or hand-picked). Compare by Investment Type, Group, Entity, Bank, Fund or Individual Holding. Use the filters to narrow to e.g. *only Mutual Funds of one entity*. Bar, trend and change charts, a detailed table, optional month-on-month deltas, **Excel export** |
| **All Holdings** | Full register for any date, search, filters, sortable columns, click a row for contacts, nominee, remarks; **Excel export** |
| **Maturities** | FDs/bonds maturing in the next 30 days to 3 years, maturity ladder, items already past their maturity date (to verify renewal) |

Amounts can be shown in **₹ / Lakhs / Crores** (button on each page), always with Indian digit grouping.

## 5. Masters (administrators)

**Masters** holds: Entities · Banks / Institutions · Funds / Securities · Investment Types · Investment Groups · **Users** · Settings (title, client name, database download).

* **Entities**: add / deactivate persons, companies, HUFs at any time. Old data stays.
* **Investment Types** belong to a **Group** (e.g. *Debt Fund → Mutual Funds*). Add types like Gold, Silver, Debentures as needed. Tick **Cost = value** for bank balances, FD, PPF, EPF (no market movement).
* New bank / fund names typed in the Excel are **added automatically** at upload (shown in the preview). Entity and Investment Type names must already exist.
* Items already used in data cannot be deleted. Deactivate them instead.
* **Roles:** *Administrator* = upload, masters, users, activity log. *Viewer* = reports only.

## 6. Gain / loss

The old sheet had only one balance figure. The template has **Invested Amount** and **Current Value**. For mutual funds, PMS, shares, bonds, gold etc. fill *Invested Amount* to see gain/(loss) and % return on the Dashboard and Holdings pages. Until then the tool shows "Not available" instead of guessing. For bank balances, FD, PPF and EPF the invested amount is taken equal to the value.

## 7. Backup and restore

* Automatic database copy at every server start and before every upload/replace/delete (last 30 kept) in `data\backups`.
* **Masters → Settings & Backup → Download database backup** gives a copy at any time.
* Every uploaded Excel is also kept in `data\uploaded_files` (downloadable from *Upload history*).
* Please also copy `C:\InvestmentTracker\data` to another place regularly (cloud drive / external disk).
* Restore: stop the task (`schtasks /end /tn InvestmentTracker`), replace `data\investments.db` with a backup, start the task again.

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| Icon opens a page that cannot be reached | Wait 10–20 seconds and refresh. Otherwise run `start_server.bat` and read the message. Log: `C:\InvestmentTracker\data\server.log` |
| Works on the server but not from outside | Port 8080 is not open in the router / cloud firewall, or the public IP changed |
| "No user accounts exist yet" | Run `setup_admin.bat` |
| Forgot administrator password | Run `setup_admin.bat` with the same username to reset it |
| Change the port | Edit `data\config.json` (`"port"`), run `INSTALL.bat` again so the firewall rule and icon follow |
| Upload says an Entity / Investment Type is not in Masters | Add it under Masters first, or correct the spelling in Excel (the preview suggests the closest name) |

## 9. Files

```
app.py            web application and APIs        importer.py     Excel reading + validation
db.py             SQLite schema and backups       reports.py      all report queries
run_server.py     production server               template_builder.py   Excel template
templates/ static/   pages, styling, scripts, Chart.js (bundled, works offline)
deploy/           installer and desktop-icon launcher
tools/            migrate_sample.py (old Excel → new format), make_cert.py (HTTPS)
data/             database, uploads, backups (created at run-time; never overwritten by upgrades)
```

`python tools/migrate_sample.py OLD.xlsx NEW.xlsx` converts a client's old multi-sheet tracker into the structured template and writes a *Review Notes* sheet listing every assumption and every figure that needs checking.

## Using a Cloudflare Tunnel (trusted HTTPS, no open ports)

1. Create the tunnel in Cloudflare (Zero Trust / Networking > Tunnels) and add a published application
   route: your host name -> `https://localhost:8080`, with "Disable TLS certificate verification" ON.
2. Run **use_tunnel.bat** as administrator and enter the host name. It makes the server listen on this
   computer only, removes the firewall rule for the port, and points the desktop icon at the public address.
3. The login lockout uses the visitor's real address supplied by Cloudflare (trusted only when the request
   comes from this computer). Search engines are told not to index the site (`robots.txt`, `X-Robots-Tag`).

## Search and reports export (v1.2)

- **Search** (box at the top of every page, or the Search menu): finds holdings by bank / institution, account or folio
  number (spaces and dashes are ignored), fund, investment type, entity, nominee, contact details, remarks etc.
  Every word typed must match. Search one date or **All dates** (history). Results can be exported.
- **Export**: Excel and PDF buttons on Dashboard, Compare Periods, All Holdings, Maturities and Search. PDF/Excel follow the
  filters, date and amount unit (₹ / Lakhs / Crores) currently selected on screen.
- PDFs use the bundled DejaVu Sans font (static/fonts, licence included) so the rupee sign prints correctly.
- Upgrading an existing installation: copy the new files over `C:\InvestmentTracker` (not the `data` folder), then run
  `update.bat` as administrator.
