"""Run meaningful tests and record reproducible, explicitly offline verification."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import random
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ledger import LedgerStore, split_cents
from model import PartsClassifier
from paypal_adapter import FixturePayPal

ROOT = Path(__file__).resolve().parent


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    classifier = PartsClassifier()
    rng = random.Random(17)
    checks = 1500
    for _ in range(checks):
        amount = rng.randrange(0, 10_000_000)
        weights = {str(i): rng.randrange(1, 1001) for i in range(rng.randrange(1, 8))}
        assert sum(split_cents(amount, weights).values()) == amount
    with tempfile.TemporaryDirectory() as temporary:
        store = LedgerStore(Path(temporary), classifier, FixturePayPal())
        session = uuid.uuid4().hex
        state = store.get(session)
        for pid, category, owners, excluded, reason in [
            ("L08", "fastener", {"alex": 1, "mina": 1, "jules": 1}, True, "Duplicate source entry; exclude this repeated screw row."),
            ("L02", "drive", {"alex": 1}, False, "An extra belt is approved as a motion-project spare."),
            ("L07", "consumables", {"alex": 1, "mina": 1, "jules": 1}, False, "Shared bench supplies; all three builders use this kit."),
        ]:
            state = store.mutate(session, "review", {"revision": state["revision"], "item_id": pid, "category": category, "weights": owners, "excluded": excluded, "reason": reason})
        state = store.mutate(session, "approve_clear", {"revision": state["revision"]})
        state = store.mutate(session, "create_invoices", {"revision": state["revision"], "confirmed": True})
        draft_statuses = [x["status"] for x in state["invoices"]]
        state = store.mutate(session, "send_invoice", {"revision": state["revision"], "invoice_id": "alex", "confirmed": True})
        issued_status = state["invoices"][0]["status"]
        state = store.mutate(session, "simulate_payment", {"revision": state["revision"], "invoice_id": "alex"})
        summary = state["totals"]
        workflow = {
            "mode": "fixture",
            "currency": "USD",
            "receipt_cents": summary["receipt_cents"],
            "excluded_cents": summary["excluded_cents"],
            "billable_cents": summary["billable_cents"],
            "shares_cents": {s["member"]["id"]: s["amount_cents"] for s in summary["members"]},
            "unallocated_cents": summary["billable_cents"] - sum(s["amount_cents"] for s in summary["members"]),
            "draft_statuses": draft_statuses,
            "issued_fixture_status": issued_status,
            "simulated_payment_status": state["invoices"][0]["status"],
            "runtime_ambiguous_item": classifier.predict("Bench tidy kit"),
            "audit_events": len(state["audit"]),
        }
    checked_files = ["server.py", "model.py", "ledger.py", "paypal_adapter.py", "fixtures.py", "training_data.json", "web/index.html", "web/style.css", "web/app.js", "tests/test_parts_ledger.py"]
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "test_result": "pass" if result.wasSuccessful() else "fail",
        "tests_run": result.testsRun,
        "test_failures": len(result.failures),
        "test_errors": len(result.errors),
        "randomized_allocation_checks": checks,
        "model": classifier.information(),
        "fixture_workflow": workflow,
        "actual_external_ai_calls": 0,
        "actual_paypal_sandbox_api_calls": 0,
        "sandbox_verification": "Mocked transport tests only; real credentials and execution still required.",
        "source_sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in checked_files},
        "record_scope": "Automated local checks. No user purchase, user savings, revenue, remote Sandbox transaction, public deployment or contest submission is claimed.",
    }
    (ROOT / "docs" / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.getvalue().strip())
    print("Verification: docs/verification.json · actual Sandbox calls: 0")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
