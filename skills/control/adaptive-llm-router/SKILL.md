---
name: adaptive-llm-router
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: control
description: >
  Two-tier model selector between Gemini 3.5 Flash and Gemini 3.5 Pro, keyed on a caller-supplied complexity label. Not wired into the live request path; the console's model dropdown decides the model in practice. No cost, token, or latency measurement feeds the selection, and no local/edge model is deployed.
fork_of: "skills/dev/model-strategy"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
tags:
  - routing
  - model-strategy
  - gemini
  - token-optimization
---

# Adaptive LLM Router & Cost Optimizer

## Purpose
Selects between two Gemini model tiers - Flash or Pro - given a `task_complexity` label ("high" routes to Pro, anything else to Flash).

## Implementation status
`conductor/router.py::ModelRouter.select_model()` implements exactly that two-way branch and nothing else: no cost, token-count, or latency signal is read anywhere in the class, and `RoutingStrategy.cost_budget_usd`/`max_retries` are declared fields that are never read. `ModelRouter`/`model_router` are also never called from anywhere else in `src/` - the console's chat and race features let the operator pick the model directly from `SUPPORTED_MODELS` instead. `ModelTier.LOCAL_FALLBACK = "gemma-2-9b"` is declared but `select_model()` never returns it, and no local model is deployed.
