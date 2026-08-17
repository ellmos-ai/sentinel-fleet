---
name: dynamic-context-injector
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: memory
description: >
  Just-in-time contextual injection of corporate policies, vendor contracts, and USMC memory bank facts directly into agent execution prompts.
fork_of: "skills/infrastructure/letter-hooker"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
tags:
  - context
  - memory-hooker
  - prompt-injection
  - usmc
---

# Dynamic Context Injector & Policy Hooker

## Purpose
Enriches sub-agent prompts dynamically with relevant organizational rules, vendor discount agreements, and past dispute resolutions retrieved from the USMC Memory Bank.
