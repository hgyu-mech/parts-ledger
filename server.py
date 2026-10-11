"""Run with python server.py. No installation or external AI service required."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ledger import LedgerError, LedgerStore
from model import PartsClassifier
from paypal_adapter import PayPalError, configured_adapter

ROOT = Path(__file__).resolve().parent


def load_environment(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() in {"PAYPAL_MODE", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_INVOICER_EMAIL", "HOST", "PORT", "APP_ALLOWED_ORIGINS"}:
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PartsLedger/1.0"

        def log_message(self, format, *args):
            # Avoid putting source texts, recipients or credentials in access logs.
            pass

        def headers_common(self, content_type, length):
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
            self.end_headers()

        def respond(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.headers_common("application/json; charset=utf-8", len(data))
            self.wfile.write(data)

        def session(self):
            return self.headers.get("X-Ledger-Session", "")

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/state":
                    self.respond(200, store.get(self.session()))
                elif path == "/api/health":
                    self.respond(200, {"ok": True, "mode": store.adapter.mode, "sandbox_ready": store.adapter.ready if store.adapter.mode == "sandbox" else False, "external_ai": False})
                elif path == "/api/export":
                    # Source and audit remain inspectable; no token or client secret exists in state.
                    state = store.get(self.session())
                    self.respond(200, {"format": "parts-ledger-export-v1", "project": state})
                elif path in {"/", "/index.html", "/app.js", "/style.css", "/favicon.svg"}:
                    file = ROOT / "web" / ("index.html" if path == "/" else path[1:])
                    data = file.read_bytes()
                    kind = mimetypes.guess_type(file)[0] or "application/octet-stream"
                    self.send_response(200)
                    self.headers_common(kind + ("; charset=utf-8" if kind.startswith("text/") or file.suffix == ".js" else ""), len(data))
                    self.wfile.write(data)
                else:
                    self.respond(404, {"error": "Not found."})
            except LedgerError as exc:
                self.respond(exc.status, {"error": str(exc)})
            except Exception:
                self.respond(500, {"error": "The workspace could not be read. Check the local data directory."})

        def do_POST(self):
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            allowed = {"http://" + host, "https://" + host} | {x.strip() for x in os.environ.get("APP_ALLOWED_ORIGINS", "").split(",") if x.strip()}
            if origin and origin not in allowed:
                self.respond(403, {"error": "Cross-origin changes are not allowed."})
                return
            if "application/json" not in self.headers.get("Content-Type", ""):
                self.respond(415, {"error": "Send a JSON request."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 200_000:
                    raise LedgerError("Request too large or empty.", 413)
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise LedgerError("Request must be an object.")
                path = urlparse(self.path).path
                if not path.startswith("/api/action/"):
                    raise LedgerError("Not found.", 404)
                action = path.rsplit("/", 1)[-1]
                self.respond(200, store.mutate(self.session(), action, body))
            except LedgerError as exc:
                self.respond(exc.status, {"error": str(exc)})
            except PayPalError as exc:
                self.respond(502, {"error": str(exc)})
            except (json.JSONDecodeError, ValueError):
                self.respond(400, {"error": "Invalid JSON request."})
            except Exception:
                self.respond(500, {"error": "This action could not be completed. Reload to inspect the stored state."})
    return Handler


def main():
    load_environment(ROOT / ".env")
    adapter = configured_adapter()
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8814"))
    if adapter.mode == "sandbox" and host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Sandbox mode is local-only. Publish the credential-free fixture demo separately.")
    store = LedgerStore(ROOT / ".data", PartsClassifier(), adapter)
    server = ThreadingHTTPServer((host, port), make_handler(store))
    print(f"Parts Ledger: http://{host}:{port} · {adapter.mode} mode", flush=True)
    if adapter.mode == "fixture":
        print("Offline fixture responses; no PayPal calls or real payments.", flush=True)
    else:
        print("Sandbox endpoint only. Credentials ready: " + str(adapter.ready), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
