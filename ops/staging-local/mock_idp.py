"""Minimal OIDC-style token issuer for LOCAL staging-mode verification only (never deploy).

Serves the JWKS at http://localhost:9000/jwks.json and mints RS256 access tokens:
  python mock_idp.py serve            # serve JWKS
  python mock_idp.py token alice      # print a token for subject 'alice'
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY = Path("/tmp/claude-0/mock_idp_key.pem")
ISS, AUD, KID = "http://localhost:9000", "election-api", "mock-1"


def key():
    if not KEY.exists():
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        KEY.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
        KEY.chmod(0o600)
    return serialization.load_pem_private_key(KEY.read_bytes(), None)


def jwks():
    pub = jwt.algorithms.RSAAlgorithm.to_jwk(key().public_key(), as_dict=True)
    return {"keys": [{**pub, "kid": KID, "use": "sig", "alg": "RS256"}]}


class H(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps(jwks()).encode()
        self.send_response(200 if self.path == "/jwks.json" else 404)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body if self.path == "/jwks.json" else b"{}")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        key()
        HTTPServer(("127.0.0.1", 9000), H).serve_forever()
    else:
        now = int(time.time())
        print(jwt.encode({"iss": ISS, "aud": AUD, "sub": sys.argv[2], "email": f"{sys.argv[2]}@staging.invalid",
                          "iat": now, "exp": now + 3600}, key(), algorithm="RS256", headers={"kid": KID}))
