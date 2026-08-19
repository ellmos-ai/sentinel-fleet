---
name: task-lifecycle-maintainer
type: skill
version: 1.1.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Asynchrone Task-Koordination und State-Tracking über eine erzwungene Zustandsmaschine (queued -> in_progress -> awaiting_approval -> completed/failed, terminale Zustände sind final).
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
Tracks a `TaskRecord` through its lifecycle (`uas/task_master.py::TaskMaster`), enforcing `ALLOWED_TASK_TRANSITIONS` so a completed or failed task can never be resurrected, and publishes each step as a plain-text status line on `run_log_bus` for the run's `/ws/run/{task_id}` subscriber.

## Implementation status
There is no "re-triage" or stalled-task recovery: nothing scans for a task stuck `in_progress` past a timeout and revives or reroutes it. There is also no dynamic triage-routing - `assigned_agent` is set once at task creation by the caller and never reassigned. What is real and enforced is the state machine itself and the async task/run coordination through `core/gateway.py` and `core/chain_runner.py`.
