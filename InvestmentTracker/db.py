"""Database layer (SQLite) for the Investment Tracker."""
import os
import sqlite3
import shutil
import datetime as dt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("IT_DATA_DIR") or os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "investments.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploaded_files")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
TMP_DIR = os.path.join(DATA_DIR, "tmp")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin','viewer')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    entity_type TEXT NOT NULL DEFAULT 'Individual',
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS banks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS investment_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS investment_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    group_id INTEGER NOT NULL REFERENCES investment_groups(id),
    cost_equals_value INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_on_date TEXT NOT NULL UNIQUE,
    prepared_on TEXT,
    uploaded_at TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    filename TEXT,
    stored_file TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    total_value REAL NOT NULL DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    as_on_date TEXT NOT NULL,
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    type_id INTEGER NOT NULL REFERENCES investment_types(id),
    bank_id INTEGER REFERENCES banks(id),
    fund_id INTEGER REFERENCES funds(id),
    joint_holder TEXT,
    nominee TEXT,
    managed_by TEXT,
    account_no TEXT,
    quantity REAL,
    start_date TEXT,
    invested_amount REAL,
    current_value REAL NOT NULL DEFAULT 0,
    maturity_date TEXT,
    maturity_amount REAL,
    interest_rate REAL,
    auto_renewal TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    last_updated TEXT,
    contact_person TEXT,
    contact_no TEXT,
    contact_email TEXT,
    remarks TEXT,
    holding_key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_h_date ON holdings(as_on_date);
CREATE INDEX IF NOT EXISTS ix_h_upload ON holdings(upload_id);
CREATE INDEX IF NOT EXISTS ix_h_key ON holdings(holding_key);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    username TEXT,
    ip TEXT,
    action TEXT NOT NULL,
    detail TEXT
);
"""

# Default masters ---------------------------------------------------------
DEFAULT_GROUPS = [
    "Cash & Bank", "Fixed Deposits", "Debt Instruments", "Mutual Funds",
    "Equity & Shares", "PMS / AIF", "Retirement Funds", "Precious Metals",
    "Real Estate", "Other",
]
# (name, group, cost_equals_value)
DEFAULT_TYPES = [
    ("Savings Account", "Cash & Bank", 1),
    ("Current Account", "Cash & Bank", 1),
    ("Fixed Deposit", "Fixed Deposits", 1),
    ("Bond", "Debt Instruments", 0),
    ("Debenture", "Debt Instruments", 0),
    ("Debt Fund", "Mutual Funds", 0),
    ("Liquid Fund", "Mutual Funds", 0),
    ("Equity Fund", "Mutual Funds", 0),
    ("Equity Shares", "Equity & Shares", 0),
    ("PMS", "PMS / AIF", 0),
    ("PPF", "Retirement Funds", 1),
    ("EPF", "Retirement Funds", 1),
    ("Gold", "Precious Metals", 0),
    ("Silver", "Precious Metals", 0),
    ("Immovable Property", "Real Estate", 0),
]
ENTITY_TYPES = ["Individual", "Company", "HUF", "Firm / LLP", "Trust", "Other"]


def ensure_dirs():
    for d in (DATA_DIR, UPLOAD_DIR, BACKUP_DIR, TMP_DIR):
        os.makedirs(d, exist_ok=True)


def connect():
    ensure_dirs()
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def init_db():
    con = connect()
    con.executescript(SCHEMA)
    cur = con.cursor()
    if cur.execute("SELECT COUNT(*) FROM investment_groups").fetchone()[0] == 0:
        for i, g in enumerate(DEFAULT_GROUPS):
            cur.execute("INSERT INTO investment_groups(name, sort_order) VALUES (?,?)", (g, (i + 1) * 10))
    if cur.execute("SELECT COUNT(*) FROM investment_types").fetchone()[0] == 0:
        gid = {r["name"]: r["id"] for r in cur.execute("SELECT id,name FROM investment_groups")}
        for i, (n, g, c) in enumerate(DEFAULT_TYPES):
            cur.execute(
                "INSERT INTO investment_types(name, group_id, cost_equals_value, sort_order) VALUES (?,?,?,?)",
                (n, gid[g], c, (i + 1) * 10),
            )
    defaults = {"app_title": "Investment Tracker", "client_name": "Client Name",
                "amount_unit": "full"}
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (k, v))
    con.commit()
    con.close()


def get_settings(con):
    return {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM settings")}


def audit(con, username, ip, action, detail=""):
    con.execute("INSERT INTO audit_log(username, ip, action, detail) VALUES (?,?,?,?)",
                (username, ip, action, detail))


def backup_db(keep=30):
    """Copy the database to data/backups using SQLite's online backup API."""
    ensure_dirs()
    if not os.path.exists(DB_PATH):
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"investments_{stamp}.db")
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("investments_") and f.endswith(".db"))
    for old in files[:-keep]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass
    return dest
