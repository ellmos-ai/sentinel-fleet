---
name: google-web-reading
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Autonomous web extraction, DOM tree sanitization, and multimodal visual document digestion powered by Gemini 3.5 Flash and Google Cloud headless runners.
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
Enables SentinelFleet agents to inspect, extract, and structure live web pages, API documentation, and multimodal invoice portals with zero hallucination and strict PII protection.

## Execution Workflow
1. **Request Interception:** Filter outbound URLs against Model Armor whitelist.
2. **DOM / PDF Ingestion:** Fetch raw HTML or PDF buffers via Cloud Run headless browser instances.
3. **Multimodal Extraction:** Utilize Gemini 3.5 Flash Vision to parse complex tables, nested grids, and financial metadata.
4. **Memory Synchronization:** Ingest extracted entities directly into the USMC Memory Bank (`category: entity`).
