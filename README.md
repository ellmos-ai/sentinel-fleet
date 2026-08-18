# SentinelFleet — Fortified Enterprise Agent Platform & OmniLedger Taskmaster

[![Google Cloud Run](https://img.shields.io/badge/Google%20Cloud-Cloud%20Run-blue.svg?logo=google-cloud)](https://cloud.google.com/run)
[![Gemini 3.5](https://img.shields.io/badge/Gemini-3.5%20Flash%20Vision-orange.svg)](https://deepmind.google/technologies/gemini/)
[![Zero-Trust Model Armor](https://img.shields.io/badge/Security-Model%20Armor%20%26%20Zero--Trust-green.svg)](#security--governance)
[![Google GenAI SDK](https://img.shields.io/badge/SDK-google--genai-4285F4.svg)](https://googleapis.github.io/python-genai/)
[![Pytest](https://img.shields.io/badge/pytest-59%2F59%20passed-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Built for the **Google Cloud All Things Agentic Hackathon** (Track 3: The Fortified Enterprise Fleet & Track 1: The Taskmaster).

---

## 🌟 Executive Summary

**SentinelFleet** is an enterprise-grade AI agent control plane and autonomous taskmaster platform built with **Gemini 3.5 Flash Vision** via the **Google GenAI SDK (`google-genai`)**, **Google Cloud Run**, and **Google Cloud Firestore**.

It solves the two largest challenges of enterprise agent adoption:
1. **Governance & Zero-Trust Security (Platform Layer):** Centralized Agent Lifecycle Registry, Zero-Trust Model Armor against Prompt Injections, granular Principle of Least Privilege (PoLP) tool isolation, USMC Memory Bank, DSGVO Privacy Contact Hub, and OpenTelemetry reasoning traces.
2. **Autonomous Messy Chores (Domain Layer — OmniLedger Taskmaster):** An end-to-end background document and invoice reconciliation workflow with § 14 UStG tax compliance validation, automated Human-in-the-Loop approval gates, and a **Self-Healing Vendor Dispute Loop**.

📖 **Full Technical Manual:** See [docs/SENTINEL_FLEET_SYSTEM_MANUAL.md](docs/SENTINEL_FLEET_SYSTEM_MANUAL.md) for deep architectural specifications.

---

## 🏛️ The 4 Pillars Architecture

SentinelFleet is architected across four modular pillars:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     SENTINEL FLEET ARCHITECTURE                                  │
├──────────────────────────┬──────────────────────────┬─────────────────────────┬──────────────────┤
│ 1. CONTROL (Governance)  │ 2. MEMORY (State & RAG)  │ 3. UAS (Human Interface)│ 4. DOMAIN (Task) │
├──────────────────────────┼──────────────────────────┼─────────────────────────┼──────────────────┤
│ • Zero-Trust Gateway     │ • USMC Memory Bank       │ • TicketMaster (HITL)   │ • OmniLedger     │
│ • Model Armor Defense    │ • GARDENER FTS & RAG     │ • TaskMaster State      │ • § 14 UStG      │
│ • Clutch Model Router    │ • MemoryHooker Clues     │ • Interactive Dashboard │ • Dispute Loop   │
│ • PII Sanitization       │ • Evidence Synthesizer   │ • Swarm Conductor       │ • Auto-Booking   │
│ • OpenTelemetry Spans    │ • Firestore Persistence  │ • Circuit Blueprint Map │ • DSGVO Contacts │
└──────────────────────────┴──────────────────────────┴─────────────────────────┴──────────────────┘
```

---

## 📇 DSGVO Privacy Contact Hub & Address Book

Synthesizing proven local privacy concepts, SentinelFleet includes a GDPR / DSGVO-compliant address book:
* **S1–S4 Protection Levels:** Strict retention timers (S1: 6m, S2: 12m, S3: 36m for tax records under § 147 AO, S4: permanent partner).
* **Tombstone Protection:** Deleted or unsubscribed contacts remain locked as tombstones to prevent autonomous agents from re-adding them or sending unrequested emails.
* **Pre-Send Verification:** Every automated supplier notice is audited against the contact hub before dispatch.

---

## 📝 32 Enterprise Skills Catalog (Component-v1)

SentinelFleet ships with 32 canonical, Google-Cloud-branded enterprise skills across all 4 pillars:
* **Domain (7):** `tax-compliance-v1`, `pdf-vision-extractor`, `multimodal-imap-grabber`, `autonomous-vendor-dispute`, `tax-reconciliation-ledger`, `ustg-law-compliance-checker`, `google-web-reading`.
* **Control (6):** `model-armor-sentry`, `model-armor-defense-guard`, `preflight-guardrail-enforcer`, `pii-redactor-and-sanitizer`, `sentinel-persona-router`, `adaptive-llm-router`.
* **UAS (6):** `task-lifecycle-maintainer`, `gemini-dag-orchestrator`, `hitl-triage-master`, `cloudrun-swarm-conductor`, `cloudrun-adaptive-scheduler`, `cloud-pubsub-event-mesh`.
* **Memory (5):** `memory-bank-connector`, `dynamic-context-injector`, `multimodal-document-chunker`, `chain-of-evidence-reasoner`, `controlcenter-skill-discovery`.
* **Assist, Dev & Utilities (8):** `google-calendar-scheduler`, `gemini-audio-transcriber`, `fleet-dossier-briefing`, `canva-ui-stylist`, `audit-incident-protocol`, `runtime-anomaly-detector`, `enterprise-plugin-engine`, `gemini-bilingual-sync`.

---

## ⚡ Quickstart (Local & Google Cloud Run)

### 1. Local Run
```bash
# Clone the repository
git clone https://github.com/ellmos-ai/sentinel-fleet.git
cd sentinel-fleet

# Install dependencies
pip install -e .

# Start the Control Center Web App
python app.py
```
Open **`http://localhost:8080`** in your browser to access the Operator Dashboard and Circuit Blueprint!

### 2. Run Tests
```bash
python -m pytest tests/ -v
```

---

## 🔒 Security & Model Armor

* **Zero-Trust Tool Scoping:** Agents only have access to their assigned tools via `gateway.py`.
* **Adversarial Injection Detection:** Regex and semantic boundary matching in `model_armor.py`.
* **Quarantine Protocol:** Malicious inputs immediately quarantine the executing agent and notify the operator via high-priority TicketMaster tickets.
