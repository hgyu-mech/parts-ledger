# Public video title

Parts Ledger — reviewed workshop costs to PayPal Sandbox invoices

# Public description

A workshop receipt can include a duplicate part, an extra spare and an uncertain description. Parts Ledger combines a local trained classifier with source-preserving review, exact-cent shared allocation and PayPal Sandbox invoicing.

This 2:40 silent demo uses actual captured browser interaction states, edited into a sequence with separate English captions. The project and receipt are synthetic. OAuth and three genuine Sandbox invoices were created for the reviewed shares: $52.58, $32.69 and $24.88.

Draft creation, issuance and buyer payment are separate states. Genuine send requests followed by GET returned SENT for all three invoices. A separate Alex refresh also returned SENT. The PayPal Sandbox buyer page shows $52.58 still due and the original source IDs on its invoice items. No buyer payment was performed; no PAID state or live-money transaction is claimed.

The local model suggests categories; the reviewer decides the category, cost owners and exclusions. Original source values and model outputs remain inspectable. Activity records the provider-sourced status changes, and the ledger was exported through the actual UI. Credentials stay on the server; the adapter supports the Sandbox endpoint only.
