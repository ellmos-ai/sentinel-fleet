---
name: memory-bank-connector
type: skill
version: 1.2.0
schema_version: component-v1
status: active
language: en
pillar: memory
description: >
  Kuratierte Faktenpersistenz und semantischer GARDENER RAG Dokumentenabruf mit dynamischer Prompt-Injektion.
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
  - store_memory_bank
tags:
  - memory
  - usmc
  - rag
  - gardener
  - context
---

# USMC Memory Bank & Context Injector

## Purpose
Connects agents to persistent corporate memory (facts, lessons, policies, entities), performing semantic RAG retrieval via GARDENER and dynamic context injection directly before inference.
