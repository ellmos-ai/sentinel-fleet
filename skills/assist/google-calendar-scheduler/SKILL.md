---
name: google-calendar-scheduler
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: assist
description: >
  Declared capability for Google Calendar API integration to manage payment deadlines, early-payment discounts (Skonto), and follow-up schedules. No execution backend is wired yet - there is no Calendar API client in this codebase.
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
Describes an intended path for scheduling time-sensitive business events - Skonto deadlines, tax filing due dates, vendor follow-ups - via the Google Calendar API.

## Implementation status
No Google Calendar (or any other calendar) API client exists in `src/`. The fleet's real time-based automation is `uas/routines.py` (`RoutineBinding`/`ScheduleBinding` plus `core/schedule_math.py`), which fires internal TaskMaster tasks on a cron/interval/one-off schedule - it does not read invoice payment terms and does not write to an external calendar. The workflow below is the intended design, not a running pipeline:
1. **Invoice Due Date Extraction:** Extract payment term (e.g., "14 days 3% Skonto, 30 days net").
2. **Event Creation:** Schedule reminder events on the corporate Google Calendar before Skonto expiration.
3. **Escalation Notification:** Alert operator if a disputed invoice deadline approaches.
