---
name: pdf-vision-extractor
type: skill
version: 3.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Invoice extraction with three declared backends: Gemini 3.5 Flash vision, the document's own
  text layer read locally, and three fixed demo documents for the console presets. Every result
  names the backend that produced it, and a rule-based privacy screen classifies the content
  before anything reaches the model.
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - extract_invoice_multimodal
tags:
  - vision
  - ocr
  - multimodal
  - gemini
  - pdf
  - privacy
---

# Multimodal PDF & Document Grabber

## Purpose
Turn an invoice document into the structured fields the § 14 UStG audit needs, and state how it
was read. A field that is not in the document must not appear in the result.

## Implementation status
Backed by `domains/omniledger/extractor.py::MultimodalExtractor`, `domains/omniledger/local_text.py`
and `core/privacy_screen.py`. Three backends, each labelled in `extraction_mode`:

1. **`gemini-3.5`** — multimodal vision call via the google-genai SDK. Runs when `GEMINI_API_KEY`
   is set and the call returns valid JSON. This is the only backend that reads line items and
   scanned pages.
2. **`local-text-layer`** — the document's own text layer, read locally with `pypdf` (PDF) or a
   decoding chain (`.txt`, `.md`, `.csv`, `.json`, `.html`, `.xml`, `.eml`). Runs for real
   uploads when no key is configured or the model call fails. A deterministic parser reads vendor
   name, VAT ID, mailbox, invoice number, invoice and delivery date, net/tax/gross amounts, tax
   rate and currency, in German or English notation. Whatever it cannot find stays empty and is
   named in `extraction_notes`; **no value is ever computed to fill a gap** — in particular the
   gross amount is never derived from net plus tax, because that would manufacture the arithmetic
   consistency the audit is meant to test.
3. **`deterministic-demo`** — three fixed demo invoices, selected by filename or text hint. These
   belong to the console's preset buttons, which send a filename and no document. A real upload
   never comes back as one of them.

**What the local backend cannot do**, stated because it matters: no OCR. A scanned PDF or an
image carries pixels, not text; this build ships no Tesseract on purpose (container size), so such
an upload is reported as unreadable with the reason, not guessed at. It also does not read line
items — only invoice totals.

## Privacy screen before the model call
`core/privacy_screen.py` classifies the document's local text view **before** it can be dispatched
to Gemini, and writes its verdict onto the gate-ledger row of that very tool call
(`privacy_screen` span event) as well as into `extraction_notes`:

- **red** — IBAN, payment card number, tax number or tax ID, social insurance number, private key
  block, API token, credential assignment
- **amber** — email address, phone number, date of birth, postal address (on an invoice these are
  expected, which is why amber states a fact rather than raising an alarm)
- **green** — none of the above in the screened window (200k characters)
- **unscreened** — there was no readable text to look at. Reported as its own verdict, never as
  green: "found nothing" and "could not look" are different answers.

Findings are masked (`DE...00`) so the verdict itself cannot leak what it reports. The screen
**records, it does not block**: refusing a call on a regex hit would be a new policy, and policy in
this fleet lives in the permission registry and the approval gate.

## Provenance
The local backend and the screen are adapted from the author's `doc-services` module (MIT):
its preference-chain shape and its content-based (not filename-based) privacy classification.
Not adopted: its OCR path, its subprocess backends and its fail-closed gate.
