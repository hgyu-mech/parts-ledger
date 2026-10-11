# Parts Ledger captured-state demonstration

This 160-second silent English demo uses real browser captures. The persistent heading discloses “Working browser demo · captured interaction states.” It does not simulate clicks, claim a continuous recording, or measure processing time.

`scripts/assemble-demo.py` is adapted from the project's own ShareProof assembly approach. The entire capture is fitted inside a neutral frame, without UI retouching or a fake pointer. Separate editorial typography uses the Parts Ledger palette: warm neutral, charcoal and orange. Actual PNG/JPEG formats are detected and included in the source-hash report.

The final sequence maps 13 real states: `qa/01-source-review.jpg` through `qa/12-activity-and-export.jpg`, including `qa/11b-paypal-source-items.jpg`. Scenes 11 and 11b each run for seven seconds; the complete sequence remains 160 seconds. Captures 07–09 were replaced with the final US Sandbox-recipient workflow, so the confirmation, returned draft IDs and issued invoices match.

Genuine Sandbox OAuth, three invoice creations and three send requests followed by GET are confirmed. All three returned `SENT`. A separate Alex refresh also returned `SENT`. The reviewed USD shares are $52.58, $32.69 and $24.88, totaling $110.15. The final IDs are `INV2-9HT5-JLGT-7DCC-VM3R`, `INV2-BEDE-9S4L-D2M8-SCE3` and `INV2-CNP3-CJA3-5K3N-CJ9L`. The buyer invoice still displays $52.58 due, with source IDs retained in four invoice lines. No buyer payment or `PAID` operation was performed. The actual UI ledger JSON export was downloaded. A fixture's Simulate payment is not part of this demonstration.

## Run

From the project directory, with Python and Pillow installed:

```sh
python scripts/assemble-demo.py --plan
python scripts/assemble-demo.py --check
python scripts/assemble-demo.py --render --ffmpeg /path/to/ffmpeg
```

ffmpeg can be found on PATH or supplied explicitly. The current fonts are the standard Windows Segoe UI files. No personal interpreter path is stored in the script or instructions. `--plan` and `--check` write no files. Rendering stops before creating frames if sources are missing, ambiguous or invalid, or any outcome remains unconfirmed.

Output is `video/rendered/parts-ledger-demo-160s.mp4`, 1920 × 1080, H.264, 30 fps, no audio. This ignored folder also contains captions, chapter timestamps, editorial frames and exact input/output hashes. Encoding does not upload or submit the project.

## Final review

Inspect every editorial frame and the encoded video's duration, dimensions, codec and source mapping. Keep dashboard client IDs, secrets, passwords, private account screens and unrelated personal data out of every source capture. Generated Sandbox example addresses, fictional workshop aliases and returned test invoice IDs can appear when they are necessary to explain the demonstrated workflow. Do not claim live payments, real buyers, user savings, independent accuracy or production reliability.

If a capture shows only part of a claimed state, narrow the caption to what is actually visible or obtain a genuine better capture. Never repair a failed request or missing result by drawing application UI. Show failures honestly, and distinguish source review, draft creation, issuance and buyer payment throughout.

The public video description records the confirmed `SENT` result and unpaid state. A public YouTube link must come from the eventual authorized upload, not this assembly process.
