---
name: gemini-audio-transcriber
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: assist
description: >
  Processes spoken voice notes, vendor call recordings, and audio briefings directly using Gemini 3.5 Flash Multimodal Audio capabilities.
fork_of: "skills/assist/transkription"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
tags:
  - audio
  - voice
  - multimodal
  - gemini
  - speech
---

# Gemini Multimodal Audio Transcriber & Voice Sentry

## Purpose
Enables SentinelFleet agents to accept voice instructions, parse phone-call summaries with suppliers, and extract structured meeting agreements directly without third-party speech pipelines.
