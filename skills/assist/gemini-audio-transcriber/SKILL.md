---
name: gemini-audio-transcriber
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: assist
description: >
  Declared capability for processing spoken voice notes and vendor call recordings using Gemini 3.5 Flash multimodal audio. No execution backend is wired yet - the fleet has no audio upload path or audio-capable model call today.
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
Describes an intended path for agents to accept voice instructions and parse phone-call summaries with suppliers.

## Implementation status
`chat/backends.py` and `domains/omniledger/extractor.py` cover text chat and document (PDF/image) uploads through the Gemini API; neither accepts an audio payload, and no other module in `src/` handles audio. The `query_memory_bank` entry in `required_tools` names an intended follow-up write into the Memory Bank once a transcript exists - there is no transcript today.
