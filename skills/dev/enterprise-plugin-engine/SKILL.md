---
name: enterprise-plugin-engine
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: dev
description: >
  Declared capability for a dynamic MCP/tool plugin runtime with hot-reloading of third-party enterprise tools. No execution backend is wired yet - this app hosts no MCP server and loads no plugins at runtime.
fork_of: "skills/dev/plugin-system"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
tags:
  - plugins
  - mcp
  - modularity
  - tools
---

# Enterprise Plugin Engine & MCP Host

## Purpose
Describes an intended runtime that would dynamically load and scope external MCP servers (e.g., banking gateways, ERP connectors) under least-privilege permissions.

## Implementation status
There is no MCP client or server code anywhere in `src/`, and no plugin-loading mechanism. The `compatibility.mcp_stdio: true` flag on every skill in this registry is a static capability label, not evidence of an MCP host - `core/skills.py` never resolves it to a connection. The PoLP enforcement that does exist (`AgentIdentity.is_tool_scoped()`, checked in `core/gateway.py`) governs the fleet's own fixed, hand-registered tool names; it has nothing to scope for a dynamically loaded plugin.
