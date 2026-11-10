"""Create a self-signed HTTPS certificate and switch the server to HTTPS.
Usage: python tools/make_cert.py <public-ip-or-domain>
"""
import os, sys, json, ipaddress, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
db.ensure_dirs()
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
try:
    names.append(x509.IPAddress(ipaddress.ip_address(host)))
except ValueError:
    names.append(x509.DNSName(host))
subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
now = dt.datetime.utcnow()
cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .sign(key, hashes.SHA256()))
open(os.path.join(db.DATA_DIR, "cert.pem"), "wb").write(cert.public_bytes(serialization.Encoding.PEM))
open(os.path.join(db.DATA_DIR, "key.pem"), "wb").write(key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
cfgp = os.path.join(db.DATA_DIR, "config.json")
cfg = json.load(open(cfgp)) if os.path.exists(cfgp) else {"host": "0.0.0.0", "port": 8080}
cfg["https"] = True
json.dump(cfg, open(cfgp, "w"))
lc = os.path.join(db.BASE_DIR, "deploy", "launcher.cfg")
if os.path.exists(lc):
    extra = f"set PUBLIC_URL={cfg['public_url']}\r\n" if cfg.get("public_url") else ""
    open(lc, "w").write(f"set PORT={cfg['port']}\r\nset SCHEME=https\r\n" + extra)
print("Certificate created and HTTPS enabled. Browsers will show a one-time 'not secure' warning for a self-signed certificate.")
