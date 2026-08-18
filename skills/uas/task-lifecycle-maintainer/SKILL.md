---
name: task-lifecycle-maintainer
type: skill
version: 1.1.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Asynchrone Task-Koordination, State-Tracking, Triage-Routing und automatische Re-Triagierung.
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - create_task
  - update_task_state
tags:
  - taskmaster
  - lifecycle
  - state
  - triage
---

# Task Lifecycle & Health Maintainer

## Purpose
Oversees the complete execution lifecycle of background tasks across Google Cloud Run, coordinating asynchronous states, re-triaging stalled tasks, and publishing status events.
