---
name: runtime-anomaly-detector
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: dev
description: >
  Declared capability for an autonomous fleet health checker monitoring error spikes, memory bloat, and repeated failed steps. No execution backend is wired yet - nothing in this codebase watches spans for anomalies or trips a circuit breaker.
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
Describes an intended real-time OpenTelemetry span watcher that would quarantine unstable sub-agents and trip circuit breakers to protect upstream APIs.

## Implementation status
`audit_telemetry` in `required_tools` names an intended function; none exists, and nothing reads `telemetry.spans` to compute error-rate spikes or memory usage. Two adjacent real mechanisms exist under different triggers, not this skill's: `core/gateway.py` quarantines an agent immediately when it calls a tool outside its scope (a permission violation, not a health signal), and `core/policies.py::evaluate_step_budget` defines a consecutive-step loop limit that is never actually called anywhere in `src/`. The Gemini backend also has no retry/circuit-breaker state - a failed call simply falls back to the demo backend on every single request.
