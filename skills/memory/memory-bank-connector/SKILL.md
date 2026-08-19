---
name: memory-bank-connector
type: skill
version: 1.2.0
schema_version: component-v1
status: active
language: en
pillar: memory
description: >
  Curated fact persistence (substring search) and keyword-based GARDENER-RAG document retrieval (word overlap, no embeddings) with dynamic prompt injection.
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
Connects agents to persistent corporate memory (facts, lessons, policies, entities) and injects the top matches directly into the prompt before inference, via `memory/hooker.py::MemoryHooker.inject_context()`.

## Implementation status
"Semantic" retrieval here means word-overlap scoring, not embeddings: `memory/bank.py::MemoryBank.search_memories()` is a case-insensitive substring match, and `memory/gardener_rag.py::GardenerRAG.search()` scores chunks by the size of the word-set intersection between query and content. There is no embedding model or vector store in this codebase. The GARDENER corpus itself is three short, hardcoded German legal paragraphs seeded at startup - no document ingestion pipeline feeds it.
