"""Source-preserving review, integer-cent allocation and invoice state machine."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import re
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fixtures import DEMO_BOM, DEMO_MEMBERS, DEMO_RECEIPT
from model import CATEGORIES, PartsClassifier, words
from paypal_adapter import PayPalError


class LedgerError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def money(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def unit_cents(value):
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", str(value).strip()):
        raise LedgerError("Unit prices must be non-negative numbers with at most two decimal places.")
    cents = int(Decimal(str(value).strip()) * 100)
    if not 0 < cents <= 1_000_000:
        raise LedgerError("Unit prices must be between 0.01 and 10,000.00.")
    return cents


def read_csv(text, bom=False):
    if not isinstance(text, str) or len(text) > 50_000:
        raise LedgerError("A source must be CSV text, at most 50,000 characters.")
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    expected = {"description", "quantity"} | (set() if bom else {"unit_price"})
    if not reader.fieldnames or not expected.issubset(set(reader.fieldnames)):
        raise LedgerError("CSV headers must include " + ", ".join(sorted(expected)) + ".")
    rows = []
    for number, row in enumerate(reader, 2):
        description = (row.get("description") or "").strip()
        qty = (row.get("quantity") or "").strip()
        if not description or len(description) > 127 or "\n" in description or "\r" in description or not re.fullmatch(r"\d{1,6}", qty) or not 0 < int(qty) <= 100_000:
            raise LedgerError(f"Line {number}: use a description (1–127 characters) and a positive whole-number quantity.")
        item = {"description": description, "quantity": int(qty), "source_line": number}
        if not bom:
            item["unit_cents"] = unit_cents(row.get("unit_price", ""))
            item["amount_cents"] = int(qty) * item["unit_cents"]
            if item["amount_cents"] > 10_000_000:
                raise LedgerError(f"Line {number}: amount exceeds the prototype limit of 100,000.00.")
        rows.append(item)
        if len(rows) > 40:
            raise LedgerError("This prototype accepts up to 40 parts per source.")
    return rows


def split_cents(total, weights):
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise LedgerError("Allocation totals must be non-negative integer cents.")
    if not weights or any(isinstance(w, bool) or not isinstance(w, int) or not 1 <= w <= 1000 for w in weights.values()):
        raise LedgerError("Select at least one member; shares must be whole-number weights from 1 to 1000.")
    denominator = sum(weights.values())
    result = {k: total * w // denominator for k, w in weights.items()}
    # Largest-remainder allocation: exact conservation, deterministic tie breaking.
    remainder = total - sum(result.values())
    ranking = sorted(weights, key=lambda k: (-(total * weights[k] % denominator), k))
    for k in ranking[:remainder]:
        result[k] += 1
    return result


def similarity(a, b):
    aa, bb = set(words(a)), set(words(b))
    return len(aa & bb) / math.sqrt(len(aa) * len(bb)) if aa and bb else 0


def event(state, kind, detail):
    state["audit"].append({"id": uuid.uuid4().hex, "time": now(), "kind": kind, "detail": detail})


def refresh_flags(state):
    active = [i for i in state["items"] if not i["excluded"]]
    for item in state["items"]:
        flags = []
        if item["model"]["needs_review"]:
            flags.append({"kind": "uncertain", "label": "Unclear description"})
        earlier = next((x for x in active if x["id"] < item["id"] and x["description"].casefold() == item["description"].casefold() and x["quantity"] == item["quantity"] and x["unit_cents"] == item["unit_cents"]), None)
        if earlier and not item["excluded"]:
            flags.append({"kind": "duplicate", "label": "Possible duplicate of " + earlier["id"]})
        bom = state["bom"]
        if bom:
            ranked = sorted(((similarity(item["description"], b["description"]), b) for b in bom), key=lambda x: -x[0])
            if ranked[0][0] < 0.55:
                flags.append({"kind": "unplanned", "label": "Not matched to the BOM"})
            else:
                match = ranked[0][1]
                quantity = sum(x["quantity"] for x in active if similarity(x["description"], match["description"]) >= 0.55)
                if quantity != match["quantity"]:
                    flags.append({"kind": "quantity", "label": f"BOM: {match['quantity']} · receipt: {quantity}"})
        item["flags"] = flags


def import_sources(state, receipt, bom, classifier):
    raw = read_csv(receipt)
    if not raw:
        raise LedgerError("Add at least one receipt item.")
    state["sources"] = {"receipt": receipt, "bom": bom}
    state["bom"] = read_csv(bom, bom=True)
    state["items"] = []
    member_ids = [p["id"] for p in state["members"]]
    for n, item in enumerate(raw, 1):
        prediction = classifier.predict(item["description"])
        scope = {"drive": "alex", "electronics": "mina", "fabrication": "jules"}.get(prediction["category"])
        weights = {scope: 1} if scope in member_ids else {p: 1 for p in member_ids}
        item.update(id=f"L{n:02d}", model=prediction, category=prediction["category"], weights=weights, reviewed=False, excluded=False, reason="", flags=[])
        state["items"].append(item)
    refresh_flags(state)
    event(state, "source_imported", {"lines": len(raw), "receipt_sha256": hashlib.sha256(receipt.encode()).hexdigest(), "bom_sha256": hashlib.sha256(bom.encode()).hexdigest(), "runtime_model": "local-multinomial-naive-bayes-v1"})


def new_state(classifier):
    state = {"project_id": uuid.uuid4().hex, "title": "Two-axis plotter", "currency": "USD", "revision": 1, "created": now(), "members": copy.deepcopy(DEMO_MEMBERS), "items": [], "bom": [], "sources": {}, "audit": [], "invoices": []}
    import_sources(state, DEMO_RECEIPT, DEMO_BOM, classifier)
    return state


def totals(state):
    pending = sum(not i["reviewed"] for i in state["items"])
    members = {p["id"]: {"member": p, "amount_cents": 0, "items": []} for p in state["members"]}
    for item in state["items"]:
        if item["excluded"]:
            continue
        for pid, cents in split_cents(item["amount_cents"], item["weights"]).items():
            if pid not in members:
                raise LedgerError("An allocation references an unknown member.")
            members[pid]["amount_cents"] += cents
            members[pid]["items"].append({"source_id": item["id"], "description": item["description"], "category": item["category"], "share_cents": cents})
    amount = sum(x["amount_cents"] for x in members.values())
    return {"receipt_cents": sum(x["amount_cents"] for x in state["items"]), "billable_cents": amount, "excluded_cents": sum(x["amount_cents"] for x in state["items"] if x["excluded"]), "pending": pending, "reviewed": len(state["items"]) - pending, "flagged": sum(bool(x["flags"]) and not x["reviewed"] for x in state["items"]), "members": list(members.values()), "ready": pending == 0 and amount > 0}


def invoice_payload(state, share):
    member = share["member"]
    return {
        "detail": {"invoice_number": "PL-" + state["project_id"][:12] + "-" + member["id"], "reference": state["title"][:120], "currency_code": state["currency"], "invoice_date": now()[:10], "note": "Reviewed project parts allocation. Source IDs are retained in each line. Sandbox test only.", "payment_term": {"term_type": "DUE_ON_RECEIPT"}},
        "primary_recipients": [{"billing_info": {"email_address": member["email"], "name": {"given_name": member["name"]}}}],
        "items": [{"name": x["description"][:127], "description": "Parts Ledger " + x["source_id"] + " · reviewed share", "quantity": "1", "unit_amount": {"currency_code": state["currency"], "value": money(x["share_cents"])} } for x in share["items"] if x["share_cents"] > 0],
        "configuration": {"allow_tip": False, "partial_payment": {"allow_partial_payment": False}},
    }


class LedgerStore:
    def __init__(self, directory: Path, classifier, adapter):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.classifier, self.adapter = classifier, adapter
        self.lock = threading.RLock()

    def path(self, session):
        if not re.fullmatch(r"[a-f0-9]{32}", session or ""):
            raise LedgerError("A valid workspace session is required.")
        return self.directory / (session + ".json")

    def load(self, session):
        path = self.path(session)
        if not path.exists():
            state = new_state(self.classifier)
            self.save(session, state)
            return state
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, session, state):
        path = self.path(session)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def public(self, state):
        return dict(state, totals=totals(state), categories=CATEGORIES, connection={"mode": self.adapter.mode, "ready": self.adapter.ready, "sandbox_endpoint": "https://api-m.sandbox.paypal.com" if self.adapter.mode == "sandbox" else None}, model=self.classifier.information())

    def get(self, session):
        with self.lock:
            return self.public(self.load(session))

    def mutate(self, session, action, payload):
        with self.lock:
            state = self.load(session)
            if payload.get("revision") != state["revision"]:
                raise LedgerError("This workspace changed in another tab. Reload before making this change.", 409)
            if action in {"review", "import", "members", "approve_clear"} and state["invoices"]:
                raise LedgerError("This allocation is locked to its invoices. Start a new project to change source costs.", 409)
            if action == "reset":
                archive = self.directory / "archive"
                archive.mkdir(exist_ok=True)
                (archive / (state["project_id"] + ".json")).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                state = new_state(self.classifier)
                state["revision"] = payload["revision"]
            elif action == "import":
                title = str(payload.get("title", state["title"])).strip()
                if not title or len(title) > 100:
                    raise LedgerError("Use a project title of 1–100 characters.")
                state["title"] = title
                import_sources(state, payload.get("receipt", ""), payload.get("bom", ""), self.classifier)
            elif action == "review":
                item = next((x for x in state["items"] if x["id"] == payload.get("item_id")), None)
                if not item:
                    raise LedgerError("Part not found.", 404)
                category = payload.get("category", item["category"])
                if category not in CATEGORIES:
                    raise LedgerError("Choose a valid part category.")
                weights = payload.get("weights", item["weights"])
                split_cents(item["amount_cents"], weights)
                if not set(weights).issubset({p["id"] for p in state["members"]}):
                    raise LedgerError("Choose project members for the split.")
                reason = str(payload.get("reason", "")).strip()
                if not 8 <= len(reason) <= 400:
                    raise LedgerError("Leave a review reason of 8–400 characters.")
                before = {k: copy.deepcopy(item[k]) for k in ("category", "weights", "reviewed", "excluded", "reason")}
                item.update(category=category, weights=weights, reviewed=True, excluded=payload.get("excluded") is True, reason=reason)
                event(state, "part_reviewed", {"source_id": item["id"], "source_line": item["source_line"], "before": before, "after": {k: item[k] for k in before}, "original_model_category": item["model"]["category"]})
                refresh_flags(state)
            elif action == "approve_clear":
                accepted = []
                for item in state["items"]:
                    if not item["reviewed"] and not item["flags"]:
                        item.update(reviewed=True, reason="Confirmed model category and suggested cost owners.")
                        accepted.append(item["id"])
                if not accepted:
                    raise LedgerError("No clear suggestions remain. Open the flagged parts individually.")
                event(state, "clear_suggestions_confirmed", {"source_ids": accepted, "human_confirmation": True})
            elif action == "members":
                members = payload.get("members", [])
                if {p.get("id") for p in members} != {p["id"] for p in state["members"]} or len(members) != 3:
                    raise LedgerError("Keep the three project member IDs.")
                for p in members:
                    if not isinstance(p.get("name"), str) or not 1 <= len(p["name"].strip()) <= 40 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(p.get("email", ""))):
                        raise LedgerError("Members need a short name and valid test email.")
                    p["name"] = p["name"].strip()
                    p["role"] = str(p.get("role", "Member"))[:40]
                state["members"] = members
                event(state, "member_details_updated", {"member_ids": [p["id"] for p in members]})
            elif action == "create_invoices":
                if state["invoices"] and any(i["mode"] != self.adapter.mode for i in state["invoices"]):
                    raise LedgerError("Invoice mode changed. Start a fresh project before using a different adapter.", 409)
                if payload.get("confirmed") is not True:
                    raise LedgerError("Confirm the invoice recipients and amounts before creating drafts.")
                summary = totals(state)
                if not summary["ready"]:
                    raise LedgerError("Review every part, including exclusions, before creating invoices.")
                if not self.adapter.ready:
                    raise LedgerError("Sandbox is not configured. Add server-side credentials; no API call or fixture fallback was made.", 409)
                # Preserve pending request IDs before a network call, so retry reuses them.
                if not state["invoices"]:
                    state["invoices"] = [{"id": x["member"]["id"], "member_name": x["member"]["name"], "recipient_email": x["member"]["email"], "amount_cents": x["amount_cents"], "request_id": uuid.uuid4().hex, "payload": invoice_payload(state, x), "status": "PENDING", "mode": self.adapter.mode, "provider_id": None, "payment_url": None, "error": None} for x in summary["members"] if x["amount_cents"] > 0]
                    self.save(session, state)
                for invoice in state["invoices"]:
                    if invoice["provider_id"]:
                        continue
                    try:
                        invoice.update(self.adapter.create(invoice["payload"], invoice["request_id"]), error=None)
                        event(state, "invoice_draft_created", {"member_id": invoice["id"], "invoice_id": invoice["provider_id"], "amount_cents": invoice["amount_cents"], "mode": self.adapter.mode})
                    except PayPalError as exc:
                        invoice["error"] = str(exc)
                        event(state, "invoice_create_failed", {"member_id": invoice["id"], "error": str(exc), "mode": self.adapter.mode})
                    self.save(session, state)
            elif action in {"send_invoice", "refresh_invoice", "simulate_payment"}:
                invoice = next((x for x in state["invoices"] if x["id"] == payload.get("invoice_id")), None)
                if not invoice or not invoice["provider_id"]:
                    raise LedgerError("Create this invoice draft first.")
                if invoice["mode"] != self.adapter.mode:
                    raise LedgerError("Invoice mode changed. Start a fresh project before using a different adapter.", 409)
                before = invoice["status"]
                if action == "send_invoice":
                    if payload.get("confirmed") is not True or invoice["status"] != "DRAFT":
                        raise LedgerError("Confirm an unsent invoice before issuing it.")
                    invoice.update(self.adapter.send(invoice["provider_id"], invoice["request_id"] + "-send"))
                elif action == "simulate_payment":
                    if self.adapter.mode != "fixture" or invoice["status"] != "SENT":
                        raise LedgerError("Payment simulation is only available for an issued offline fixture invoice.")
                    invoice["status"] = "PAID"
                elif self.adapter.mode == "sandbox":
                    invoice.update(self.adapter.get(invoice["provider_id"]))
                event(state, "invoice_status_checked" if before == invoice["status"] else "invoice_status_changed", {"member_id": invoice["id"], "before": before, "after": invoice["status"], "mode": self.adapter.mode, "source": "offline simulation" if self.adapter.mode == "fixture" else "PayPal Sandbox response"})
            else:
                raise LedgerError("Unknown action.", 404)
            state["revision"] += 1
            self.save(session, state)
            return self.public(state)
