---
name: cloud-pubsub-event-mesh
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Declared capability for an event-driven messaging bridge distributing invoice arrivals and dispute triggers across Google Cloud Pub/Sub topics. No execution backend is wired yet - there is no Pub/Sub client in this codebase.
fork_of: "skills/infrastructure/cloud-communication-protocols"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - dispatch_swarm
tags:
  - pubsub
  - event-mesh
  - messaging
  - google-cloud
---

# Google Cloud Pub/Sub Event Mesh & Telemetry Distributor

## Purpose
Describes an intended decoupling of document ingestion from long-running agent work using Google Cloud Pub/Sub topics and dead-letter queues.

## Implementation status
No `google-cloud-pubsub` import or topic/subscription handling exists anywhere in `src/`. The `dispatch_swarm` entry in `required_tools` points at the same unwired `conductor/swarm.py` stub described in `cloudrun-swarm-conductor`. The fleet's actual asynchronous coordination is in-process: `core/storage.py` optionally backs the data stores with Firestore (only when `GOOGLE_APPLICATION_CREDENTIALS` or `K_SERVICE` is set), and `uas/routines.py`'s `fire_due()` is a plain HTTP-callable function - a design compatible with an external Cloud Scheduler hitting it, but that is polling/scheduling, not a Pub/Sub event mesh.
