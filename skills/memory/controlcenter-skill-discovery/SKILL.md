---
name: controlcenter-skill-discovery
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: memory
description: >
  ControlCenter-style keyword matcher over the skill registry: scores each skill by word overlap between the query and its name/description/tags/pillar, ranked highest-overlap first.
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
Enables an agent or operator to discover which registered skill best matches a free-text query, via `core/skills.py::SkillRegistry.find_skills()`.

## Implementation status
`find_skills()` tokenizes the query and each skill's searchable text into word sets and ranks by set-intersection size - literal keyword overlap, not semantic or embedding-based matching. A skill's `required_tools` list is returned as-is for the caller to read; nothing in this codebase validates it against an actual tool implementation or "binds" it to one, and there is no capability-bundle concept (bundling, versioned grouping) anywhere in `core/skills.py`.
