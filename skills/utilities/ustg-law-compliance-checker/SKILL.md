---
name: ustg-law-compliance-checker
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: utilities
description: >
  Deterministic auditor for German § 14 UStG tax regulations: presence of the 8 mandatory invoice fields (VAT ID included, presence-only - no format regex) and mathematical invoice consistency.
fork_of: "skills/utilities/law-checker"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - validate_tax_compliance
tags:
  - tax
  - ustg
  - legal
  - compliance
  - utilities
---

# § 14 UStG Tax Compliance Auditor & Legal Sentry

## Purpose
Validates statutory requirements for European and German invoices under § 14 UStG, via `core/policies.py::PolicyEngine.evaluate_tax_compliance()` (the same function `tax-compliance-v1` describes).

## Mandatory Validations
1. **Supplier & Document Fields (presence only):** vendor name, vendor VAT ID, invoice number, issue date, delivery/service date, net amount, tax rate, gross amount. The check confirms each field is present and non-empty/non-zero (tax rate 0% is accepted if the key exists) - it does not validate the VAT ID against a `DE[0-9]{9}` or any other format pattern, and it does not check supplier legal form or address (`vendor_address` is not in the checked field list).
2. **Mathematical Parity:** `round(Net * Tax Rate / 100, 2)` compared to `Gross - Net`, with a tolerance of **0.02 EUR** (2 cents, for rounding) before it is flagged as an arithmetic inconsistency.
