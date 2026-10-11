"""PayPal Invoicing v2 integration. Only the Sandbox host is reachable."""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from decimal import Decimal
from urllib.parse import urlparse, quote

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        # Credentials and requests can never follow a redirect to a live host.
        raise urllib.error.HTTPError(request.full_url, code, "Redirect refused", headers, file)


class PayPalError(Exception):
    pass


def safe_error_detail(error):
    """Keep protocol diagnostics while removing addresses and token-like strings."""
    parts = [str(error.get("message", ""))]
    issue_codes = []
    for detail in error.get("details", [])[:3]:
        if isinstance(detail, dict):
            issue = str(detail.get("issue", ""))
            if re.fullmatch(r"[A-Z][A-Z_]{1,90}", issue):
                issue_codes.append(issue)
            parts.append(str(detail.get("field", "")))
    text = " ".join(part for part in parts if part)
    text = re.sub(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+", "[address omitted]", text)
    text = re.sub(r"[A-Za-z0-9_-]{28,}", "[token omitted]", text)
    return (" ".join(text.split()) + (" " + ", ".join(issue_codes) if issue_codes else ""))[:300]


def safe_payment_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlparse(value)
        if parsed.scheme == "https" and parsed.hostname in {"www.sandbox.paypal.com", "sandbox.paypal.com"} and parsed.username is None and parsed.password is None and parsed.port in {None, 443}:
            return value
    except ValueError:
        pass
    return None


def sandbox_email(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._+-]+@(?:personal|business)\.example\.com", value))


class PayPalSandbox:
    mode = "sandbox"

    def __init__(self, client_id: str = "", client_secret: str = "", invoicer_email: str = "", transport=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.invoicer_email = invoicer_email
        self._transport = transport or self._http
        self._token = ""
        self._expires = 0.0
        self._token_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return bool(self.client_id and self.client_secret and sandbox_email(self.invoicer_email))

    def _http(self, method, path, body, headers):
        if not path.startswith("/") or ".." in path or "://" in path:
            raise PayPalError("Invalid Sandbox API path.")
        request = urllib.request.Request(SANDBOX_BASE + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
                data = response.read(2_000_000)
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as exc:
            try:
                error = json.loads(exc.read(30_000))
                issue = str(error.get("name", "REQUEST_FAILED"))[:70]
                diagnostic = safe_error_detail(error)
            except Exception:
                issue = "REQUEST_FAILED"
                diagnostic = ""
            # Never include tokens, secrets, request bodies or recipient information.
            raise PayPalError(f"PayPal Sandbox returned HTTP {exc.code}: {issue}." + (" " + diagnostic if diagnostic else "")) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise PayPalError("PayPal Sandbox could not be reached. Nothing was marked paid; retry with the same draft.") from None

    def _access_token(self):
        if not self.ready:
            raise PayPalError("Sandbox credentials and a generated Sandbox business email are required. No fixture fallback was made.")
        with self._token_lock:
            if self._token and self._expires > time.monotonic():
                return self._token
            basic = base64.b64encode((self.client_id + ":" + self.client_secret).encode()).decode()
            response = self._transport("POST", "/v1/oauth2/token", b"grant_type=client_credentials", {
                "Authorization": "Basic " + basic,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            })
            self._token = response.get("access_token", "")
            if not self._token:
                raise PayPalError("Sandbox authentication returned no access token.")
            self._expires = time.monotonic() + max(1, int(response.get("expires_in", 60)) - 30)
            return self._token

    def _request(self, method, path, payload=None, request_id=None, *, return_representation=False, accept_json=True):
        headers = {"Authorization": "Bearer " + self._access_token(), "Content-Type": "application/json"}
        if accept_json:
            headers["Accept"] = "application/json"
        if return_representation:
            headers["Prefer"] = "return=representation"
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        body = json.dumps(payload).encode() if payload is not None else None
        return self._transport(method, path, body, headers)

    def create(self, payload, request_id):
        for recipient in payload.get("primary_recipients", []):
            if not sandbox_email(recipient["billing_info"]["email_address"]):
                raise PayPalError("Use generated PayPal Sandbox recipient addresses ending in personal.example.com or business.example.com.")
        payload = dict(payload, invoicer={"email_address": self.invoicer_email})
        try:
            result = self._request("POST", "/v2/invoicing/invoices", payload, request_id, return_representation=True)
        except PayPalError as original_error:
            # Invoice numbers are stable and unique per project/member. If a response
            # was lost, reconcile an existing exact draft rather than blindly claiming
            # PayPal-Request-Id is supported by every Invoicing endpoint.
            number = payload["detail"]["invoice_number"]
            try:
                found = self._request("POST", "/v2/invoicing/search-invoices?page=1&page_size=20&total_required=false", {"invoice_number": number})
                expected_amount = sum(Decimal(x["unit_amount"]["value"]) * Decimal(x["quantity"]) for x in payload["items"])
                expected_email = payload["primary_recipients"][0]["billing_info"]["email_address"]
                result = next((x for x in found.get("items", []) if x.get("detail", {}).get("invoice_number") == number and x.get("amount", {}).get("currency_code") == payload["detail"]["currency_code"] and Decimal(x.get("amount", {}).get("value", "-1")) == expected_amount and x.get("primary_recipients", [{}])[0].get("billing_info", {}).get("email_address") == expected_email), None)
            except (PayPalError, ValueError, ArithmeticError, IndexError):
                result = None
            if result is None:
                raise original_error
        invoice_id = result.get("id")
        if not invoice_id:
            invoice_id = next((x["href"].rstrip("/").rsplit("/", 1)[-1] for x in result.get("links", []) if x.get("rel") == "self"), None)
        if not invoice_id or not re.fullmatch(r"INV2-[A-Z0-9-]+", invoice_id):
            raise PayPalError("Sandbox returned no valid invoice ID; the draft was not reported as created.")
        return {"provider_id": invoice_id, "status": result.get("status", "DRAFT"), "mode": self.mode, "payment_url": safe_payment_url(result.get("detail", {}).get("metadata", {}).get("recipient_view_url"))}

    def send(self, provider_id, request_id):
        # Request and response bodies use JSON; Prefer is create-only.
        # The subsequent GET supplies the provider's actual invoice status.
        self._request("POST", "/v2/invoicing/invoices/" + quote(provider_id, safe="") + "/send", {"send_to_recipient": True, "send_to_invoicer": False}, request_id)
        return self.get(provider_id)

    def get(self, provider_id):
        result = self._request("GET", "/v2/invoicing/invoices/" + quote(provider_id, safe=""))
        return {"provider_id": provider_id, "status": result.get("status", "UNKNOWN"), "mode": self.mode, "payment_url": safe_payment_url(result.get("detail", {}).get("metadata", {}).get("recipient_view_url"))}


class FixturePayPal:
    """Explicit offline simulator. It never invokes PayPal or reports Sandbox access."""
    mode = "fixture"
    ready = True

    def create(self, payload, request_id):
        return {"provider_id": "DEMO-" + request_id[:12].upper(), "status": "DRAFT", "mode": self.mode, "payment_url": None}

    def send(self, provider_id, request_id):
        return {"provider_id": provider_id, "status": "SENT", "mode": self.mode, "payment_url": None}

    def get(self, provider_id):
        raise PayPalError("Offline fixture status is stored locally, not fetched from PayPal.")


def configured_adapter():
    mode = os.environ.get("PAYPAL_MODE", "fixture").strip().lower()
    if mode == "fixture":
        return FixturePayPal()
    if mode == "sandbox":
        return PayPalSandbox(os.environ.get("PAYPAL_CLIENT_ID", ""), os.environ.get("PAYPAL_CLIENT_SECRET", ""), os.environ.get("PAYPAL_INVOICER_EMAIL", ""))
    raise ValueError("PAYPAL_MODE must be fixture or sandbox. Live PayPal is not supported.")
