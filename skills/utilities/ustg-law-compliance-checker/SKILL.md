---
name: ustg-law-compliance-checker
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: utilities
description: >
  Deterministic auditor for German § 14 UStG tax regulations, VAT ID format checks, and mathematical invoice consistency.
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
Validates statutory requirements for European and German invoices under § 14 UStG with zero tolerance for math anomalies or missing supplier identification.

## Mandatory Validations
1. **Full Supplier Details:** Name, legal form, address.
2. **Tax Identification:** Valid German Steuernummer or EU USt-IdNr (`DE[0-9]{9}`).
3. **Date Stamps:** Issue date and delivery/service period.
4. **Mathematical Parity:** `Net + (Net * Tax Rate) == Gross` within ±0.01 EUR rounding tolerance.
