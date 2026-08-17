---
name: cloudrun-swarm-conductor
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: dev
description: >
  Orchestrates serverless multi-agent swarms, parallel map-reduce pipelines, and consensus rounds across Google Cloud Run workers.
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
Enables dynamic task decomposition and parallel execution across stateless Google Cloud Run instances using the Roshambo stigmergy and consensus protocols.

## Capabilities
- **Parallel Fan-out:** Distribute bulk document processing across N concurrent Gemini 3.5 Flash instances.
- **Consensus Voting:** Multiple auditor agents cross-validate tax calculations before settlement.
- **Failover & Re-dispatch:** Automatic retry with exponential backoff on transient quota limits.
