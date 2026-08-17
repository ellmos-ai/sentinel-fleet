---
name: cloud-pubsub-event-mesh
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Event-driven messaging bridge distributing asynchronous invoice arrivals, dispute triggers, and agent heartbeats across Google Cloud Pub/Sub topics.
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
Decouples document ingestion from long-running multi-agent reasoning loops using resilient Google Cloud Pub/Sub topics and dead-letter queues.
