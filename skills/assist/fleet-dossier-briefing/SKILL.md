---
name: fleet-dossier-briefing
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: assist
description: >
  Synthesizes multi-source financial, operational, and compliance telemetry into concise, decision-ready executive briefings for human operators.
fork_of: "skills/assist/dossier-briefing"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
  - audit_telemetry
tags:
  - briefing
  - executive
  - synthesis
  - assist
---

# Fleet Dossier & Executive Briefing

## Purpose
Generates high-density executive briefings and audit digests across all fleet actions, § 14 UStG compliance violations, and OpenTelemetry trace metrics.

## Key Sections
1. **Executive Summary:** Bullet-point digest of recent fleet milestones and pending HITL tickets.
2. **Compliance & Risk Matrix:** Breakdown of flagged invoices and vendor dispute timelines.
3. **Infrastructure Health:** Per-call span status (`OK`/`BLOCKED`/`SECURITY_VIOLATION`/`DENIED`/`ERROR`) and latency from `core/telemetry.py`'s OpenTelemetry spans. No percentile aggregation (e.g. P95) or token-quota accounting exists in this codebase; a briefing built on this skill reports raw span figures, not derived statistics.
