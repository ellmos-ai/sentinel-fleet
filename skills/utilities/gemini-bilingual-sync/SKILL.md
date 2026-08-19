---
name: gemini-bilingual-sync
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: utilities
description: >
  Declared capability for an autonomous German/English cross-lingual document synchronizer covering tax rules, error reports, and UI strings. No execution backend is wired yet - there is no translation or locale-sync code in this repository.
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
Describes an intended path to keep German statutory compliance documents (§ 14 UStG, GoBD) and their English counterparts in parity.

## Implementation status
No translation function, i18n framework, or locale-sync job exists in `src/`; `query_memory_bank` in `required_tools` names an intended lookup step with nothing behind it. The Memory Bank and legal RAG corpus (`memory/bank.py`, `memory/gardener_rag.py`) are seeded in German only. "100% semantic fidelity" is not a measurable property of anything in this codebase and has been removed as a claim.
