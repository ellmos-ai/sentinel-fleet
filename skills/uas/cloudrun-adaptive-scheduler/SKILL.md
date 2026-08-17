---
name: cloudrun-adaptive-scheduler
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Dynamic rate-limiting, load leveling, and cron de-congestion scheduler for serverless background agent workflows on Google Cloud.
fork_of: "skills/infrastructure/cron-tuner"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - update_task_state
tags:
  - scheduler
  - cron
  - cloudrun
  - rate-limiting
---

# Cloud Run Adaptive Scheduler & Workload Tuner

## Purpose
Prevents compute throttling and token congestion across 80+ fleet automation sidecars by adaptively spacing out scheduled runs and background reconciliations.
