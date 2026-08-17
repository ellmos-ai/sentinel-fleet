---
name: chain-of-evidence-reasoner
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: memory
description: >
  Formal Tree-of-Thought reasoning synthesizer producing auditable step-by-step proofs and verifiable citations for SystemAuditor inspections.
fork_of: "skills/utilities/structured-thinking"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
tags:
  - reasoning
  - evidence
  - tree-of-thought
  - audit
---

# Chain of Evidence Reasoner & Decision Synthesizer

## Purpose
Generates transparent, mathematically verifiable reasoning chains for every approval, tax rejection, or vendor dispute, linking directly to statutory paragraphs and document coordinates.
