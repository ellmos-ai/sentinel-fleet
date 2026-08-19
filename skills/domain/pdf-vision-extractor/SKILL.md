---
name: pdf-vision-extractor
type: skill
version: 2.1.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Pixelgenaue Extraktion tabellarischer und unstrukturierter Daten mit Gemini 3.5 Flash Vision.
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - extract_invoice_multimodal
tags:
  - vision
  - ocr
  - multimodal
  - gemini
  - pdf
---

# Multimodal PDF & Document Grabber

## Purpose
High-precision multimodal invoice data extraction engine leveraging Gemini 3.5 Flash Multimodal Vision for pixel-perfect line-item parsing, gross/net separation, and tax rate identification.

## Implementation status
Backed by `domains/omniledger/extractor.py::MultimodalExtractor`. When `GEMINI_API_KEY` is unset, or a live call fails or returns invalid JSON, extraction does not degrade silently: it falls back to one of three fixed, clearly labelled demo documents (`extraction_mode: DETERMINISTIC_DEMO`) selected by filename/text hints, never a fabricated result presented as a live extraction.
