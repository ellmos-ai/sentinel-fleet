---
name: multimodal-imap-grabber
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Declared capability for an autonomous document ingestion pipeline polling secure IMAP/Gmail API mailboxes for PDF invoices. No execution backend is wired yet; the skill only governs how an agent talks about mail ingestion, it does not perform it.
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
Describes an intended mailbox ingestion path: monitor inbound accounting mailboxes via IMAP/Gmail API, extract PDF invoices, verify SPF/DKIM origin, and feed the result into the OmniLedger pipeline.

## Implementation status
No mail client is implemented in this codebase - there is no IMAP or Gmail API integration anywhere in `src/`. The `create_task` entry in `required_tools` names the intended hand-off into TaskMaster; nothing currently produces that task from an inbound mailbox. Today, invoices only enter OmniLedger through the console's manual upload endpoint (`extract_invoice_multimodal`, see `pdf-vision-extractor`).
