---
name: chain-of-evidence-reasoner
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: memory
description: >
  Prompt-level instruction shaping how an agent explains a decision: cite the statutory paragraph and the retrieved memory/legal-corpus snippet it relied on, in plain step-by-step prose.
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
Asks the model to explain an approval, tax rejection, or vendor dispute by naming the statutory paragraph and quoting the memory-bank/legal-corpus snippet it drew on - the same reference block `domains/omniledger/dispute_loop.py` already assembles from `memory_hooker.inject_context()` and attaches to a dispute draft.

## Implementation status
This is a prompt-behaviour skill: its body is injected verbatim into the agent's system prompt (`core/skills.py`), it does not run separate reasoning code. There is no formal Tree-of-Thought solver, no mathematical proof checker, and no document-coordinate (bounding box) extraction anywhere in this codebase - `InvoiceDocument` carries text fields only, no page/position data.
