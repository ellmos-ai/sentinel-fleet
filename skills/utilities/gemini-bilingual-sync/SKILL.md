---
name: gemini-bilingual-sync
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: utilities
description: >
  Autonomous German/English cross-lingual document synchronizer translating complex tax rules, error reports, and UI strings with 100% semantic fidelity.
fork_of: "skills/utilities/bilingual-doc-sync"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
tags:
  - bilingual
  - translation
  - internationalization
  - gemini
---

# Gemini Bilingual Synchronizer (DE/EN)

## Purpose
Ensures complete parity between German statutory compliance documents (§ 14 UStG, GoBD) and English international accounting reports and executive digests.
