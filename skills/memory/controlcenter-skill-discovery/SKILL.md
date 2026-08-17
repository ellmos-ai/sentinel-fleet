---
name: controlcenter-skill-discovery
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: memory
description: >
  ControlCenter-compliant skill discovery, keyword matcher, and dynamic capability bundler resolving agent intent to toolsets.
fork_of: "skills/infrastructure/skill-finder"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
tags:
  - discovery
  - controlcenter
  - skills
  - capabilities
---

# ControlCenter Skill Discovery & Capability Matcher

## Purpose
Enables autonomous agents to discover available enterprise skills, inspect required tool contracts, and bind dynamically to capability bundles.
