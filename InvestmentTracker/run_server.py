"""Start the Investment Tracker server (production-grade, works on Windows and Linux).

Usage:
    python run_server.py                  start the server
    python run_server.py --create-admin   create (or reset) an administrator account interactively
    python run_server.py --port 9000      override port
"""
import os
import sys
import getpass
import argparse
import datetime as dt


def create_admin():
    import db
    from werkzeug.security import generate_password_hash
    db.init_db()
    con = db.connect()
    username = input("Administrator username [admin]: ").strip() or "admin"
    while True:
        pw = getpass.getpass("Password (min 8 characters): ")
        if len(pw) < 8:
            print("Too short, try again.")
            continue
        if pw != getpass.getpass("Repeat password: "):
            print("Passwords do not match, try again.")
            continue
        break
    h = generate_password_hash(pw, method="pbkdf2:sha256")
    row = con.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if row:
        con.execute("UPDATE users SET password_hash=?, role='admin', active=1 WHERE id=?", (h, row["id"]))
        print(f"Password reset and administrator rights confirmed for '{username}'.")
    else:
        con.execute("INSERT INTO users(username, full_name, password_hash, role) VALUES (?,?,?, 'admin')",
                    (username, "Administrator", h))
        print(f"Administrator '{username}' created.")
    con.commit()
    con.close()


def _setup_logging():
    """pythonw.exe has no console: send output to data/server.log instead."""
    import db
    db.ensure_dirs()
    if sys.stdout is None or sys.stderr is None or not sys.stdout.isatty():
        log = open(os.path.join(db.DATA_DIR, "server.log"), "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--create-admin", action="store_true")
    ap.add_argument("--port", type=int)
    ap.add_argument("--host")
    args = ap.parse_args()

    if args.create_admin:
        create_admin()
        return
    _setup_logging()

    from cheroot.wsgi import Server
    import app as appmod
    import db

    cfg = appmod.CONFIG
    host = args.host or cfg.get("host", "0.0.0.0")
    port = args.port or int(cfg.get("port", 8080))

    # daily safety backup at start-up
    try:
        db.backup_db()
    except Exception as e:  # noqa
        print("Backup skipped:", e)

    server = Server((host, port), appmod.app, numthreads=12, request_queue_size=64, timeout=30)
    scheme = "http"
    cert, key = os.path.join(db.DATA_DIR, "cert.pem"), os.path.join(db.DATA_DIR, "key.pem")
    if cfg.get("https") and os.path.exists(cert) and os.path.exists(key):
        from cheroot.ssl.builtin import BuiltinSSLAdapter
        server.ssl_adapter = BuiltinSSLAdapter(cert, key)
        scheme = "https"
    elif cfg.get("https"):
        print("WARNING: 'https' is true in config.json but data/cert.pem / key.pem not found. Serving plain HTTP.")
        appmod.app.config["SESSION_COOKIE_SECURE"] = False

    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] Investment Tracker {appmod.APP_VERSION} running on "
          f"{scheme}://{host}:{port}  (data folder: {db.DATA_DIR})")
    try:
        server.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()
