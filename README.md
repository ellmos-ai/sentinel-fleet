# SentinelFleet — Fortified Enterprise Agent Platform & OmniLedger Taskmaster

[![Google Cloud Run](https://img.shields.io/badge/Google%20Cloud-Cloud%20Run-blue.svg?logo=google-cloud)](https://cloud.google.com/run)
[![Gemini 3.5](https://img.shields.io/badge/Gemini-3.5%20Flash%20Vision-orange.svg)](https://deepmind.google/technologies/gemini/)
[![Zero-Trust Model Armor](https://img.shields.io/badge/Security-Model%20Armor%20%26%20Zero--Trust-green.svg)](#security--governance)
[![Pytest 100% Passed](https://img.shields.io/badge/pytest-100%25%20passed-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Built for the **All Things Agentic Hackathon** (Track 3: The Fortified Enterprise Fleet & Track 1: The Taskmaster).

---

## 🌟 Executive Summary

**SentinelFleet** is an enterprise-grade AI agent control plane and autonomous taskmaster platform built with **Gemini 3.5 Flash Vision**, **Google ADK**, and **Google Cloud (Cloud Run & Firestore)**.

It solves the two largest challenges of enterprise agent adoption:
1. **Governance & Zero-Trust Security (Platform Layer):** Centralized Agent Registry, Model Armor against Prompt Injections, granular Principle of Least Privilege (PoLP) tool isolation, USMC Memory Bank, and OpenTelemetry reasoning traces.
2. **Autonomous Messy Chores (Domain Layer — OmniLedger Taskmaster):** An end-to-end background document and invoice reconciliation workflow with § 14 UStG tax compliance validation and a **Self-Healing Vendor Dispute Loop**.

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
│ • OpenTelemetry Spans    │ • Firestore Persistence  │ • Circuit Blueprint Map │ • Auto-Booking   │
└──────────────────────────┴──────────────────────────┴─────────────────────────┴──────────────────┘
```

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
pytest tests/ -v
```

### 3. Deploy to Google Cloud Run
```bash
# Build and deploy directly to Cloud Run
gcloud run deploy sentinel-fleet \
  --source . \
  --platform managed \
  --region europe-west3 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY="your-gemini-api-key"
```

---

## 🔒 Security & Governance (Model Armor & Zero-Trust)

* **Adversarial Prompt Injection Defense:** Model Armor scans and intercepts system prompt overrides, jailbreaks, and hidden injection attempts fail-closed.
* **PII & Data Sanitization:** Automatically masks IBANs, Credit Cards, and API keys before sending to LLM APIs.
* **Human-in-the-Loop (`ask`-Gates):** Actions with external side effects (e.g. sending emails to vendors or financial payouts) are queued as Tickets in TicketMaster for human operator signoff.

---

## 📄 License
MIT License. Copyright (c) 2026 SentinelFleet Contributors.
