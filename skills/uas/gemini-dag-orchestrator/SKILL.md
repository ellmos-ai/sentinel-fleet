---
name: gemini-dag-orchestrator
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Runs a TaskTemplate's steps as a linear, position-ordered chain, each step's output feeding the next as context; a "race" step fans out to up to four models concurrently via `asyncio.gather`.
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
Executes a multi-step `TaskTemplate` (`core/chain_runner.py::run_chain()`): steps run strictly in `position` order, and each step receives the previous step's output as injected context (`input_spec` is fixed to `previous_output`).

## Implementation status
This is a linear chain, not a directed acyclic graph: there is no dependency declaration between steps, no branching, and no cycle validation to enforce (a chain cannot fan out or merge). The one real parallel-execution pattern is the `race` step type, which dispatches one prompt to up to `MAX_RACE_LANES` (4) models concurrently via `asyncio.gather` in `ChatService.race()` - a genuine concurrent fan-out, but across models racing the same step, not across independent task nodes with dependencies.
