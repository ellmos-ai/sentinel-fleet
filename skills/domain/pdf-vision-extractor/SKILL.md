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
