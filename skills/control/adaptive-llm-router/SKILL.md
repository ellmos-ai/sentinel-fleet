---
name: adaptive-llm-router
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: control
description: >
  Cost-, token-, and latency-optimized dynamic model routing between Gemini 3.5 Flash, Gemini Pro, and local edge fallbacks on Google Cloud.
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
Dynamically selects the optimal Gemini model tier (Flash for speed/multimodal vision, Pro for deep multi-step legal reasoning) based on task complexity and token budget.
