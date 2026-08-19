---
name: task-lifecycle-maintainer
type: skill
version: 1.1.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Asynchronous task coordination and state tracking through an enforced state machine (queued -> in_progress -> awaiting_approval -> completed/failed/cancelled, terminal states are final). An operator may cancel a task that has not run; a running one may not be cancelled, because a run here is synchronous.
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
Tracks a `TaskRecord` through its lifecycle (`uas/task_master.py::TaskMaster`), enforcing `ALLOWED_TASK_TRANSITIONS` so a completed, failed or cancelled task can never be resurrected, and publishes each step as a plain-text status line on `run_log_bus` for the run's `/ws/run/{task_id}` subscriber.

## Implementation status
There is no "re-triage" or stalled-task recovery: nothing scans for a task stuck `in_progress` past a timeout and revives or reroutes it. There is also no dynamic triage-routing - `assigned_agent` is set once at task creation by the caller and never reassigned. What is real and enforced is the state machine itself and the async task/run coordination through `core/gateway.py` and `core/chain_runner.py`.

## Cancelling and removing

`CANCELLED` is its own terminal state rather than `FAILED` with a reason: nothing went wrong,
somebody decided, and a queue that cannot tell those apart reports every abandoned duplicate as a
defect. It is reachable from `QUEUED` and `AWAITING_APPROVAL` only. `IN_PROGRESS` deliberately has
no cancel edge - a run there is synchronous and over in seconds, so the button would offer control
that does not exist.

`TaskMaster.delete_task()` is the one operation that erases rather than transitions, and it accepts
only a terminal record. Deleting a queued or running task would drop work the fleet still owns and
leave the queue describing something other than what the fleet is doing.
