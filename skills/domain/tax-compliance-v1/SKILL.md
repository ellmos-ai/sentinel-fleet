---
name: tax-compliance-v1
type: skill
version: 1.4.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Automated check of statutory mandatory fields, VAT ID and arithmetic consistency under German tax law (§ 14 UStG).
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - validate_tax_compliance
tags:
  - tax
  - compliance
  - ustg
  - finance
  - audit
---

# § 14 UStG Tax Compliance Auditor

## Purpose
Deterministic statutory tax compliance auditor enforcing all 8 mandatory invoice criteria under § 14 UStG with zero tolerance for mathematical anomalies or missing VAT IDs.
