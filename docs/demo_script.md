# Parts Ledger — 2:40 demonstration

The source-review sequence uses the synthetic plotter project. A genuine Sandbox run created and issued all three invoices; subsequent GETs returned SENT. A separate refresh confirmed Alex's SENT status, and its buyer page showed four source-row IDs and $52.58 due. Buyer payment has not been verified. Record the Sandbox section from the actual app session and keep any Offline demo footage clearly labelled.

| Time | Screen/action | Spoken explanation |
| --- | --- | --- |
| 0:00–0:15 | Full project view; source total $112.95 and four flagged rows | “This plotter team shares a receipt, but not every part. Parts Ledger connects the source decision to each person's invoice.” |
| 0:15–0:30 | Open row 08. Show source line and possible duplicate; exclude it with reason | “The second screw row appears twice. I exclude $2.80 from billing while keeping its original source and the review reason.” |
| 0:30–0:45 | Open row 02. Show BOM two versus receipt three; retain Alex, explain project spare | “The BOM planned two belts. The receipt contains three. The reviewer confirms the spare rather than asking the model to invent an explanation.” |
| 0:45–1:10 | Open row 07. Show original model suggestion and uncertainty. Change to Shop supplies, choose all members, save | “The local model is uncertain about ‘Bench tidy kit.’ I correct the category and share it across the team. The original model output stays in the record.” |
| 1:10–1:20 | Confirm clear suggestions, then Cost split | “The remaining categories and cost owners still need an explicit confirmation. The reviewed total is $110.15.” |
| 1:20–1:35 | Show $52.58, $32.69, $24.88 and $0.00 difference | “Shared lines can have odd cents. The allocation preserves the total exactly and links each share to its source row.” |
| 1:35–1:55 | PayPal Sandbox badge; create reviewed drafts or show the actual returned drafts; show amounts and INV2 IDs | “The reviewed amounts become three PayPal Sandbox invoice drafts. Credentials stay on the server.” |
| 1:55–2:10 | Issue a reviewed invoice with its separate confirmation; show the three actual SENT statuses, then refresh Alex's invoice | “Each invoice is issued separately. PayPal returned SENT for all three, and a fresh status read confirms Alex's invoice.” |
| 2:10–2:20 | PayPal Sandbox buyer page: Alex's $52.58 due and L01, L02, L03, L07 source IDs | “The buyer page carries the four source IDs and the same $52.58 due. Buyer payment remains unverified.” |
| 2:20–2:35 | Activity: inspect corrected category and status event; export | “The ledger keeps the original suggestion, the reviewed decision, and the invoice status source. Its JSON export makes those decisions inspectable.” |
| 2:35–2:40 | Return full project; closing card | “Parts Ledger: a source, a reviewed share, and an invoice that can be traced back.” |

## Prepare the recording

- Record only the synthetic project and fictional aliases. Keep environment files, dashboard secrets and private accounts outside the frame.
- The current local suite passes 39 tests, and the browser script passes its syntax check. Those checks and fixture transitions are separate from the actual remote Sandbox evidence.
- For a Korean Sandbox business, use generated US Sandbox buyer accounts for the cross-border test. Korean merchant/payer pairs produced `KOREAN_MERCHANT_KOREAN_PAYER_RESTRICTED`; the app retained the DRAFT status.
- Use a fresh demo so the amounts match the script. Enter the three review reasons before their save clicks if the recording needs to stay below three minutes.
- Keep the cursor and important source text large enough to read. At mobile width, record a separate short responsive cut, replacing idle navigation time.
- Capture the actual application, not a static mockup. Use original interface artwork. No third-party music is necessary.
- Export a video under **3:00**, upload it to YouTube as **public**, and verify playback without signing in before entering its link.

## If adding a buyer-payment segment later

The recorded Sandbox scope is create, issue, GET status and buyer-page inspection. Extend it only after the matching generated Sandbox buyer completes a payment:

1. Avoid passwords, dashboard secrets and private account details in the footage.
2. Replace the buyer-page inspection at 2:10 with the actual Sandbox payment. Return to Parts Ledger and click Refresh status; describe only the status returned by PayPal.
3. Show the corresponding Activity event with source **PayPal Sandbox response**. Retain the source-review and exact-cent explanation.

Until then, the SENT sequence above is the verified endpoint of this demo. An optional fixture walkthrough must say Offline demo and identify its SENT/PAID changes as local simulation. Do not substitute fixture simulation or Record Payment for a verified buyer payment.
