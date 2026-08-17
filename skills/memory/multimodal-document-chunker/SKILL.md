---
name: multimodal-document-chunker
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: memory
description: >
  Structured semantic chunking of multi-page invoices, contractual annexes, and tabular financial sheets for vector indexing and Gemini 3.5 Flash RAG.
fork_of: "skills/utilities/document-chunker"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - store_memory_bank
tags:
  - chunking
  - rag
  - documents
  - memory
---

# Multimodal Document Chunker & Semantic Splitter

## Purpose
Deconstructs complex PDF documents and scanned invoices into cohesive semantic chunks preserving table headers, line-item contexts, and tax footnotes.
