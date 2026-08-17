---
name: gemini-dag-orchestrator
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Decomposes ambiguous enterprise requests into acyclic directed graphs (DAGs) and coordinates parallel agent dispatch across SentinelFleet workers.
fork_of: "skills/infrastructure/orchestrator"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - create_task
  - assign_task
  - dispatch_swarm
tags:
  - orchestrator
  - dag
  - workflow
  - decomposition
---

# Gemini DAG Orchestrator & Task Decomposer

## Purpose
Transforms high-level business goals (e.g., "Audit and reconcile Q2 invoices from Acme Corp") into discrete, executable task nodes with strict dependency tracking.
