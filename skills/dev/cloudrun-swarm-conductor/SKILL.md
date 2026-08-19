---
name: cloudrun-swarm-conductor
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: dev
description: >
  Declared capability for orchestrating serverless multi-agent swarms and consensus rounds across Google Cloud Run workers. No execution backend is wired yet - the conductor module is an unconnected stub with no map-reduce, voting, or retry logic.
fork_of: "skills/dev/swarm-operations"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - dispatch_swarm
  - assign_task
tags:
  - swarm
  - orchestration
  - cloudrun
  - parallel
---

# Google Cloud Run Multi-Agent Swarm Conductor

## Purpose
Describes an intended dynamic task decomposition and parallel-execution layer across stateless Cloud Run instances.

## Implementation status
`conductor/swarm.py` defines `SwarmConductor.dispatch_collaborative_workflow()`, but its body opens a telemetry span and immediately returns a hardcoded `{"status": "COMPLETED", "steps": []}` - no dispatch, fan-out, voting, or retry happens, and the class is never called from anywhere else in `src/`. The capabilities below are the intended design, not running code:
- **Parallel Fan-out:** Distribute bulk document processing across N concurrent Gemini 3.5 Flash instances.
- **Consensus Voting:** Multiple auditor agents cross-validate tax calculations before settlement.
- **Failover & Re-dispatch:** Automatic retry with exponential backoff on transient quota limits.

The one real parallel-fan-out path in this codebase is `ChatService.race()` (`chat/service.py`), which dispatches one prompt to up to four models concurrently via `asyncio.gather` - a chat/model-comparison feature, not a swarm conductor.
