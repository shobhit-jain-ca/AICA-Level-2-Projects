"""Switch the app to 'Cloudflare Tunnel only' mode.
Usage: python tools/use_tunnel.py <public-hostname>     e.g. tracker.capbridgegrowth.com
 - the server then listens on this computer only (127.0.0.1), so it cannot be reached directly
   from the internet or the local network; all access goes through the tunnel
 - the desktop icon and the SendToClient shortcut open the public address
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

if len(sys.argv) < 2:
    sys.exit("Give the public host name, e.g.  tracker.capbridgegrowth.com")
host = sys.argv[1].strip().replace("https://", "").replace("http://", "").strip("/")
if not host or " " in host or "." not in host:
    sys.exit("That does not look like a host name: " + host)
url = f"https://{host}/"

db.ensure_dirs()
cfgp = os.path.join(db.DATA_DIR, "config.json")
cfg = json.load(open(cfgp)) if os.path.exists(cfgp) else {"port": 8080}
cfg["host"] = "127.0.0.1"
cfg["public_url"] = url
json.dump(cfg, open(cfgp, "w"))

lc = os.path.join(db.BASE_DIR, "deploy", "launcher.cfg")
scheme = "https" if cfg.get("https") else "http"
open(lc, "w").write(f"set PORT={cfg.get('port', 8080)}\r\nset SCHEME={scheme}\r\nset PUBLIC_URL={url}\r\n")

sc = os.path.join(db.BASE_DIR, "SendToClient", "Investment Tracker.url")
if os.path.isdir(os.path.dirname(sc)):
    open(sc, "w").write(f"[InternetShortcut]\r\nURL={url}\r\n")

print("Done. The server now listens on this computer only; public address:", url)
