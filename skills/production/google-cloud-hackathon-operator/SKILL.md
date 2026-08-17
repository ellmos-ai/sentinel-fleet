---
name: google-cloud-hackathon-operator
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: production
description: >
  Drives the 10-phase hackathon submission lifecycle, DevPost compliance checks, architecture blueprints, and GCP demonstration proof.
fork_of: "skills/production/hackathon-operator"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - verify_receipts
tags:
  - hackathon
  - devpost
  - production
  - lifecycle
---

# Google Cloud Hackathon Submission Operator

## Purpose
Automates the rigor, phase transitions, and governance checks for the "All Things Agentic" DevPost Hackathon (Tracks 1–4, Google Cloud Run deployment, Gemini 3.5 Flash integration).

## 10-Phase Gate Lifecycle
1. **Intake & Brief:** Extract rules, rubrics, bonus criteria.
2. **Portfolio Audit:** Gap analysis against track specifications.
3. **Concept & Plan:** Architecture diagrams, wireframes, and video storyboard.
4. **Build & Package:** Clean repo, zero hardcoded secrets, Dockerfile, tests.
5. **Verify & Deploy:** Cloud Run verification, OpenTelemetry spans.
6. **Video & Story:** 4-minute demo with live GCP traces.
7. **Release Gate:** Public repository switch (HITL Gate).
8. **DevPost Submission:** Form filling and validation.
9. **Amplify:** Technical blog post and social dissemination.
