"""Create a self-signed HTTPS certificate so cameras work from other devices on your Wi-Fi.

    pip install cryptography
    python scripts/make_dev_cert.py

Browsers will show a one-time warning for a self-signed certificate; choose Advanced → Continue.
Keep certs/ private and never commit it. For development only.
"""
import datetime
import ipaddress
import socket
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    print("Install the helper first:  pip install cryptography")
    sys.exit(1)

OUT = Path(__file__).resolve().parent.parent / "certs"


def lan_ips() -> list:
    ips = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))     # no packets are sent; just picks the LAN interface
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ips)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Universal Translator (dev)")])
    ips = lan_ips()
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    (OUT / "key.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    (OUT / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f"Created {OUT / 'cert.pem'} and key.pem (valid 1 year) for: localhost, {', '.join(ips)}")
    print("Now set LAN_MODE=1 in .env, restart run.py, and open https://<your-PC-IP>:8000 on each device.")


if __name__ == "__main__":
    main()
