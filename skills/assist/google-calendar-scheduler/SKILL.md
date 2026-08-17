---
name: google-calendar-scheduler
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: assist
description: >
  Integrates with Google Calendar API to manage payment deadlines, early-payment discounts (Skonto), statutory audit appointments, and follow-up schedules.
fork_of: "skills/assist/kalender"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
  - create_task
tags:
  - calendar
  - google-api
  - deadlines
  - skonto
  - scheduling
---

# Google Calendar Scheduler & Deadline Sentry

## Purpose
Automates time-sensitive business events, including early-payment discount (Skonto) deadlines, tax filing due dates, vendor follow-ups, and scheduled audit reviews via the Google Calendar API.

## Core Workflows
1. **Invoice Due Date Extraction:** Extract payment term (e.g., "14 days 3% Skonto, 30 days net").
2. **Event Creation:** Schedule reminder events on the corporate Google Calendar before Skonto expiration.
3. **Escalation Notification:** Alert operator if a disputed invoice deadline approaches.
