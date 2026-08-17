---
name: runtime-anomaly-detector
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: dev
description: >
  Autonomous fleet health checker and loop breaker monitoring error spikes, memory bloat, and repeated failed step executions.
fork_of: "skills/dev/bugsweep"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - audit_telemetry
tags:
  - health
  - anomaly
  - circuit-breaker
  - telemetry
---

# Runtime Anomaly Detector & Fleet Circuit Breaker

## Purpose
Monitors OpenTelemetry spans in real-time, automatically quarantining unstable sub-agents and tripping circuit breakers to protect upstream APIs.
