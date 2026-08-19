---
name: multimodal-document-chunker
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: memory
description: >
  Declared capability for structured chunking of multi-page invoices and contractual annexes for vector indexing and Gemini-backed RAG. No execution backend is wired yet - no document is ever split into chunks or embedded in this codebase.
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
Describes an intended splitter that would deconstruct complex PDF documents and scanned invoices into cohesive chunks, preserving table headers and line-item context.

## Implementation status
`memory/gardener_rag.py::GardenerRAG.add_document()` is the only "chunk" concept in this codebase, and it does not split anything: each call stores one caller-supplied string as one whole `DocumentChunk`. It is invoked exactly three times, at startup, with three short hardcoded legal-corpus paragraphs (§ 14 UStG, GoBD, the dispute SOP) - no uploaded invoice is ever passed to it. `GardenerRAG.search()` is keyword/word-overlap matching (see `memory-bank-connector`), not vector similarity, and there is no embedding model or vector store anywhere in `src/`.
