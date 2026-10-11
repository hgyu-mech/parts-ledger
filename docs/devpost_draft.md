# Parts Ledger

## Tagline

Review a shared parts receipt, split every cent, and create PayPal invoices tied to the source.

## Inspiration

Student project teams and makerspace groups buy hardware together, then divide costs according to who needs each part. A motor may belong to one person's work, while workshop supplies serve everyone. An extra spare or duplicate receipt row needs a decision before the total is split.

Parts Ledger connects those decisions to PayPal invoice drafts. Its demonstration follows a two-axis plotter team using an original synthetic receipt with ambiguous descriptions, a quantity mismatch and a possible duplicate.

## What it does

Import a typed receipt and an optional bill of materials. A trained local classifier suggests five workshop categories. Source checks flag possible duplicates, unmatched parts and quantity differences. The review drawer brings together the original row, model suggestion, supporting terms, proposed owners and the reason for a change.

The sample's “Bench tidy kit” has an uncertain electronics suggestion. The reviewer can change it to Shop supplies, assign all three members and record the shared use. The original prediction stays visible alongside the reviewed category. A model score supplies a starting point; the reviewer determines who should bear the cost.

The same review identifies a second screw entry as a duplicate. Excluding its $2.80 leaves the original receipt row intact while reducing the billable total from $112.95 to $110.15. Confirming the extra timing belt as a project spare records another decision instead of changing the source quantity.

The approved sample splits into $52.58, $32.69 and $24.88, with zero unallocated cents. Each PayPal invoice item carries its source-row ID in the description. The trail runs from receipt row to reviewed decision, allocated cents and invoice item. Activity and JSON export preserve that record.

Every source line requires confirmation before draft creation. Recipients and amounts have their own confirmation step; issuance is a separate operation, distinct from buyer payment.

## How it was built

The backend uses Python's standard library, with an HTML, CSS and JavaScript interface. A multinomial Naive Bayes model trains locally on 100 original synthetic labelled descriptions. Word and word-pair features drive runtime suggestions; low confidence or limited vocabulary coverage triggers review.

OpenAI Codex assisted implementation, documentation and preparation of the labelled examples. Runtime inference uses the local model.

Amounts use integer cents after strict decimal validation. Largest-remainder allocation preserves an odd cent when a line is shared. The PayPal Invoicing v2 adapter keeps OAuth credentials on the server and accepts only Sandbox endpoints. Stable invoice numbers and persisted request records support recovery after an uncertain creation response. Reconciliation checks the recipient, currency and amount before adopting an existing invoice.

## Verification

Genuine PayPal OAuth and Invoicing v2 calls created and issued three distinct Sandbox invoices for $52.58, $32.69 and $24.88. Each send was followed by retrieval returning SENT. A separate refresh returned SENT for Alex's invoice; its PayPal buyer page displayed L01, L02, L03 and L07 with $52.58 due. The reviewed total is $110.15, with zero unallocated cents. Sanitized export checks and evidence hashes are in `docs/sandbox-verification.json`. Buyer payment has not been verified, and no remote PAID result is claimed.

The suite passes 39 tests, including 1,500 randomized cent allocations, and the browser script passes its syntax check. Checks cover preserved source values, ambiguous model input, review overrides, stale edits, lost-response recovery, safe diagnostics, send/GET status preservation, session isolation and rejected live endpoints. Offline demonstrations remain explicitly labelled as fixtures, with simulated payment confined to that mode.

## Challenges during integration

A Sandbox send failure surfaced as a generic media-type error. Inspecting its protocol issue revealed a Korean merchant–Korean buyer restriction. Retesting with generated US buyers produced three provider-confirmed SENT invoices. The adapter now retains useful issue codes while removing addresses and token-like values from diagnostics. This also reinforced the separation between source data, reviewed decisions and provider state: an uncertain response must remain unresolved until it is checked.

## Scope and next steps

The prototype supports typed English receipts, three members and USD. The next steps are receipt-image extraction and a larger, independently evaluated parts dataset. The current demonstration establishes the reviewed source-to-invoice workflow; real-team outcomes have not been measured.

## Built with

Python · JavaScript · HTML/CSS · multinomial Naive Bayes · PayPal Sandbox Invoicing v2 · OpenAI Codex
