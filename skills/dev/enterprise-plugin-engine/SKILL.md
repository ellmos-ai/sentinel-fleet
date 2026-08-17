---
name: enterprise-plugin-engine
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: dev
description: >
  Dynamic MCP and tool plugin runtime loader enabling runtime discovery and hot-reloading of third-party enterprise tools.
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
Dynamically loads and scopes external MCP servers (e.g., banking gateways, ERP connectors) under strict principle-of-least-privilege (PoLP) permissions.
