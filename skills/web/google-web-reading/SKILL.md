---
name: google-web-reading
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Declared capability for autonomous web extraction and DOM sanitization powered by Gemini 3.5 Flash and a Cloud Run headless browser. No execution backend is wired yet - the fleet has no outbound web-fetch or browser-automation code today.
fork_of: "skills/web/web-reading"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - extract_invoice_multimodal
  - query_memory_bank
tags:
  - web
  - scraping
  - dom
  - multimodal
  - gemini
---

# Google Web Reading & Multimodal DOM Digestion

## Purpose
Describes an intended path for agents to inspect, extract, and structure live web pages and multimodal invoice portals.

## Implementation status
There is no HTTP client, headless browser, or scraper anywhere in `src/` - `extract_invoice_multimodal` (see `pdf-vision-extractor`) only accepts a file the operator uploads through the console, it never fetches a URL. The workflow below is the intended design, not a running pipeline:
1. **Request Interception:** Filter outbound URLs against Model Armor before any fetch is attempted.
2. **DOM / PDF Ingestion:** Fetch raw HTML or PDF buffers via a Cloud Run headless browser instance.
3. **Multimodal Extraction:** Reuse the Gemini 3.5 Flash Vision call `extract_invoice_multimodal` already uses for uploads.
4. **Memory Synchronization:** Store extracted entities via `memory_bank.store_memory(category="entity", ...)`, the same call `ledger_reconciler.book_invoice()` already makes.
