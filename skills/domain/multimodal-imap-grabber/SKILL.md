---
name: multimodal-imap-grabber
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Autonomous document ingestion pipeline polling secure IMAP/Gmail API mailboxes for PDF invoices, sanitizing attachments, and queuing extraction tasks.
fork_of: "skills/utilities/mail-clean-grab"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - create_task
tags:
  - imap
  - email
  - invoices
  - ingestion
---

# Multimodal IMAP Grabber & Attachment Ingestion

## Purpose
Monitors inbound accounting mailboxes via IMAP/Gmail API, extracts PDF invoices, verifies SPF/DKIM origin, and feeds them into the OmniLedger pipeline.
