---
name: autonomous-vendor-dispute
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Drafts legally grounded, polite discrepancy notices and formal credit-note demands to vendors when statutory § 14 UStG errors are detected.
fork_of: "skills/utilities/privat-mail-writer"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - draft_vendor_dispute_email
  - send_external_email
tags:
  - dispute
  - vendor
  - self-healing
  - legal
---

# Autonomous Vendor Dispute & Correction Loop

## Purpose
Generates formal, legally precise discrepancy notices to suppliers under § 14 UStG, pauses payment orders, and routes draft emails to the human operator for approval.
