# Parts Ledger

Review workshop purchases, split shared costs, and issue PayPal Sandbox invoices from the approved ledger.

Parts Ledger follows a small team building a two-axis plotter. A typed receipt includes an extra timing belt, an ambiguous shop-supply item, and a possible duplicate screw row. A local trained model suggests categories. The reviewer checks the source, changes a suggestion when needed, assigns cost owners, and records a reason. Every billable cent then has a source line and an owner.

## Run from the repository root

Requirements: Python 3.10 or newer and a current browser. No packages, paid AI service, or API key are needed for the offline demo.

```sh
python server.py
```

Open **http://127.0.0.1:8814**. The default badge says **Offline demo**. Invoice responses and the payment simulation in this mode are local fixtures: they are never presented as a PayPal connection.

## Try the complete workflow

1. Open source row **08**, the second M3 screw entry. Select **Exclude this source row from billing**, explain that it duplicates row 03, and save. The original row and its $2.80 remain visible in the ledger.
2. Open row **02**, the timing belts. The BOM requests two; the receipt contains three. Confirm the extra belt as a project spare, retain Alex as its cost owner, and record the reason.
3. Open row **07**, **Bench tidy kit**. The model is uncertain. Change its category to **Shop supplies**, select all three members, and explain the shared use.
4. Click **Confirm clear suggestions**. This confirms the remaining categories and suggested cost owners; it does not silently approve flagged parts.
5. Open **Cost split**. The $112.95 source receipt, less the $2.80 excluded row, produces **$110.15**: Alex **$52.58**, Mina **$32.69**, Jules **$24.88**. Unallocated difference: **$0.00**.
6. Open **Invoices**, click **Create reviewed drafts**, inspect the recipients and shares, and check the confirmation box. This creates three offline drafts.
7. Click **Issue test invoice** on a card and confirm it separately. Its local status becomes SENT. **Simulate payment** then changes that fixture status to PAID.
8. Open **Activity** to inspect decisions, source IDs, the original model suggestion, and invoice status changes. **Export ledger** downloads the current source and audit record as JSON.

The demo names, emails, descriptions, and prices are synthetic. They do not describe actual purchases or people.

## What the AI does

`model.py` fits a multinomial Naive Bayes model at startup from **100 original, labelled workshop descriptions**, across five categories. It learns word and word-pair likelihoods and predicts the category of the imported descriptions at runtime. The review drawer exposes the original prediction, its score, supporting terms, and whether it needs attention. Editing a reviewed category preserves the model's original output.

OpenAI Codex assisted implementation, documentation and preparation of the synthetic labelled examples. Runtime classification uses the local Naive Bayes model.

There are **20 separately authored holdout descriptions**, none identical to a training description. The current model classifies 20 of those 20 correctly. This is a small development check, not a real-world accuracy claim or an independent benchmark. The displayed scores are uncalibrated. The ambiguous demo item intentionally requires human review.

The model does **not** read images, invent quantities or prices, determine who actually bought a part, or approve a purchase. CSV parsing, BOM text overlap, duplicate checks, default cost owners, and integer-cent allocation are deterministic helpers. They are not represented as AI. There are no external AI calls, model downloads, or subscription charges.

## Connect the genuine PayPal Sandbox adapter

The app uses PayPal's OAuth and Invoicing v2 REST APIs. A genuine Sandbox run created and issued three invoices for $52.58, $32.69 and $24.88. Each send was followed by GET returning SENT; a separate refresh also returned SENT for Alex's invoice. Its PayPal buyer page displayed four source-row IDs and $52.58 due. Buyer payment has not been verified. Sanitized results and evidence hashes are in `docs/sandbox-verification.json`; adapter unit tests remain separate mocked checks.

1. In the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/), create or select a **Sandbox** REST app attached to a Sandbox business account. Prepare three generated US Sandbox personal buyer accounts when testing with a Korean Sandbox business account. Korean merchant/payer pairs return `KOREAN_MERCHANT_KOREAN_PAYER_RESTRICTED`; use the generated test accounts for a cross-border Sandbox scenario.
2. Copy `.env.example` to `.env` in the app directory. Keep this file local; it is ignored by Git.
3. Set the values below. Use the client ID and secret from the **Sandbox** app, and the generated business Sandbox email shown in the dashboard.

```dotenv
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=your_sandbox_client_id
PAYPAL_CLIENT_SECRET=your_sandbox_secret
PAYPAL_INVOICER_EMAIL=sb-example@business.example.com
HOST=127.0.0.1
PORT=8814
```

4. Restart `python server.py`. The interface now says **PayPal Sandbox**, or clearly reports missing configuration.
5. Start a fresh project. Open the member avatars and replace the fixture emails with the generated `...@personal.example.com` buyer emails. Ordinary personal emails are rejected by the Sandbox adapter. Finish the source review and allocation.
6. Create the confirmed drafts. The server obtains OAuth credentials and calls **POST `/v2/invoicing/invoices`**. Real Sandbox IDs begin with `INV2-`. Creating a draft does not issue or pay it.
7. Issue each reviewed invoice with its separate confirmation. This calls **POST `/v2/invoicing/invoices/{id}/send`**, followed by **GET** of the invoice. Issuing does not pay it.
8. Where PayPal returns a buyer URL, open **Sandbox payment page** and sign in as the matching Sandbox buyer. The buyer completes the Sandbox payment there. Return to Parts Ledger and click **Refresh status**. The app displays the status returned by **GET `/v2/invoicing/invoices/{id}`**.

Only `https://api-m.sandbox.paypal.com` is supported. `PAYPAL_MODE=live` is rejected. Redirects are refused, and only HTTPS Sandbox buyer links are shown. The application has no API for executing a buyer payment or marking a real invoice paid. The offline **Simulate payment** button does not exist in Sandbox mode.

Credentials and OAuth tokens stay in the server process. No credential is included in browser state, exports, invoice records, or the repository. Error diagnostics retain a short message, field and protocol issue code; addresses and long token-like strings are removed. Request bodies and detail values are omitted.

### Retry behavior

The ledger persists a request ID and a unique invoice number before creation. Successfully created drafts are skipped on retry. If a create response is lost, the adapter searches the exact invoice number and checks its currency, amount, and recipient before adopting an existing ID. It does not rely on a blanket guarantee that every Invoicing endpoint honors `PayPal-Request-Id`. A failed call is shown as a failure, never converted into fixture success.

## Architecture and data

```text
Typed receipt + optional BOM
          ↓
Trained local classifier + deterministic source checks
          ↓
Reviewer: category / owners / exclusion / reason
          ↓
Integer-cent split + separate draft confirmation
          ↓
PayPal Sandbox REST adapter  OR  explicit offline fixture
          ↓
Separate issue confirmation → provider status → audit/export
```

| File | Role |
| --- | --- |
| `server.py` | Standard-library HTTP server; static allowlist and JSON endpoints |
| `model.py`, `training_data.json` | Runtime model, original labelled data and authored holdout |
| `ledger.py` | CSV validation, review state, source checks, exact allocation and audit |
| `paypal_adapter.py` | Fixed-host OAuth/Invoicing adapter and separately labelled fixtures |
| `fixtures.py` | Synthetic plotter receipt, BOM and member aliases |
| `web/` | Responsive browser interface; no external scripts, fonts or trackers |
| `tests/` | Model, arithmetic, workflow, adapter and real local HTTP tests |

Each tab gets a random 128-bit workspace session in `sessionStorage`. Project state is saved under ignored `.data/`; updates use atomic replacement and a revision check. Changing the source or owners is blocked after invoice creation. Starting fresh archives the previous project locally and does not cancel external invoices. Importing new CSV replaces the current source and review decisions; prior imports' checksums remain in the activity history. This prototype does not provide accounts, cross-device sync, or an authenticated multi-tenant deployment.

Receipt CSV headers: `description,quantity,unit_price`. BOM CSV headers: `description,quantity`. The current scope is **USD, up to 40 receipt rows, three project members, integer quantities, and prices with at most two decimal places**. The UI selects equal owners; the internal allocation function also validates integer weights. Odd cents use largest-remainder allocation with a stable tie break. The current model's small English parts vocabulary can misclassify unfamiliar descriptions; all lines must be confirmed before billing.

### Local API

All workspace requests use `X-Ledger-Session: <32 lowercase hex characters>`. Mutations include the current `revision`; stale changes return HTTP 409.

| Request | Purpose |
| --- | --- |
| `GET /api/health` | Current adapter mode and readiness |
| `GET /api/state` | Current source, suggestions, decisions, totals and invoice records |
| `GET /api/export` | Current source and audit as JSON |
| `POST /api/action/import` | Typed source and project title |
| `POST /api/action/review` | One source-line review with a recorded reason |
| `POST /api/action/approve_clear` | Explicitly confirm unflagged suggestions |
| `POST /api/action/members` | Three recipient details before invoice creation |
| `POST /api/action/create_invoices` | Create reviewed drafts, requiring `confirmed: true` |
| `POST /api/action/send_invoice` | Issue a draft, requiring `confirmed: true` |
| `POST /api/action/refresh_invoice` | Read its current Sandbox status |
| `POST /api/action/simulate_payment` | Fixture-only SENT-to-PAID simulation |
| `POST /api/action/reset` | Archive this project and load a fresh synthetic sample |

## Verification

```sh
python -B -m unittest discover -s tests
node --check web/app.js
```

The test suite currently passes **39 tests**, and `web/app.js` passes the Node syntax check. The suite checks 1,500 randomized cent allocations; malformed amounts; immutable source amounts; ambiguous and unfamiliar model input; reviewed overrides; exclusion/BOM changes; the complete fixture state transition; stale edits; retries; OAuth headers and token reuse; send/GET status preservation; exact recovery of a lost create response; safe error diagnostics; rejected live URLs and redirects; session isolation; and the actual local HTTP server's static-file and cross-origin boundaries. The local results and source hashes are in `docs/verification.json`.

The automated local verification makes zero remote Sandbox calls. Its historical fixture result and mocked adapter tests remain separate from the genuine create/send/GET evidence in `docs/sandbox-verification.json`. All three remote invoices returned SENT, and their amounts sum to the reviewed $110.15. There is no verified remote PAID result. The buyer-page check established the item trail and amount due; it did not execute a payment. Keep credentials and login screens out of the video and public evidence.

## Hosting for judges

The public, key-free fixture demo can bind with `HOST=0.0.0.0 PAYPAL_MODE=fixture` (set environment variables using your shell). Put it behind HTTPS on a trusted host, with writable temporary/local `.data/` storage. If a reverse proxy changes the visible host, set `APP_ALLOWED_ORIGINS` to the exact public HTTPS origin. Do not use `*`.

Sandbox mode deliberately accepts only a localhost bind. The public fixture deployment is a judge walkthrough; the complete local setup provides the reproducible Sandbox path. Public fixture state is synthetic and session-based. Keep hosted judge access available through **December 15, 2026**, and avoid adding personal or confidential source data to the public demo.

## Submission materials

`docs/devpost_draft.md` is an editable submission draft. `docs/demo_script.md` supplies a sub-three-minute walkthrough and distinguishes offline footage from credential-based Sandbox footage. Repository, hosted URL, YouTube URL, and remote verification must be filled from actual published results. No contest submission has been made by this repository.

## Official references

- [PayPal AI Hackathon rules](https://paypalaihackathon.devpost.com/rules)
- [Hackathon resources](https://paypalaihackathon.devpost.com/resources)
- [Sandbox overview](https://developer.paypal.com/sandbox-testing/overview)
- [REST authentication](https://developer.paypal.com/api/rest/authentication/)
- [Create invoice](https://developer.paypal.com/api/invoicing/v2/invoices-create)
- [Send invoice](https://developer.paypal.com/api/invoicing/v2/invoices-send)
- [Get invoice](https://developer.paypal.com/api/invoicing/v2/invoices-get)
- [Korean account payment restrictions](https://www.paypal.com/kr/digital-wallet/system-enhancement-faq?locale.x=en_KR)

Licensed under MIT. The classifier data, interface artwork and sample descriptions are original project assets.
