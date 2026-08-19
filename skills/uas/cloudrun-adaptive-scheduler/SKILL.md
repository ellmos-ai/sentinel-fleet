---
name: cloudrun-adaptive-scheduler
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Fixed-schedule engine for background agent workflows: interval/daily/cron next-occurrence calculation, DST-safe, triggered by an external caller hitting `POST /api/routines/fire` (e.g. a Cloud Scheduler job).
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
Computes each `RoutineBinding`'s next due time from an interval/daily/cron spec (`core/schedule_math.py::next_after()`, DST-safe via `zoneinfo`), and fires every due `RoutineBinding`/`ScheduleBinding` as a TaskMaster task when `fire_due()` is called (`uas/routines.py`).

## Implementation status
The schedule math is fixed, not adaptive: it returns the next occurrence of a spec, it does not read system load or reprioritize based on it. There is no rate-limiting, no token-budget accounting (no token quota exists anywhere in this codebase), and no "80+ sidecars" concept - that figure does not correspond to anything measurable here. What the engine does provide is a real per-binding `miss_policy` (`skip` or `catch_up`) for runs that were missed while the app was down.
