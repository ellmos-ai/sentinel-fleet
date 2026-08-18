# SentinelFleet & OmniLedger — Technical System Manual & Architecture Guide

> **Project:** SentinelFleet (Enterprise Multi-Agent Platform & Autonomous Taskmaster)  
> **Repository:** [github.com/ellmos-ai/sentinel-fleet](https://github.com/ellmos-ai/sentinel-fleet)  
> **Google Cloud Hackathon 2026:** Track 1 (Autonomous Taskmaster) & Track 3 (Enterprise Multi-Agent Governance)  
> **Target Runtime:** Google Cloud Run, Gemini 3.5 Flash / Pro via the Google GenAI SDK (`google-genai`), Google Cloud Firestore, OpenTelemetry (Cloud Trace export optional)  

---

## 1. Executive Summary

**SentinelFleet** is a fortified, zero-trust enterprise agent operating system and taskmaster platform designed for mission-critical corporate workflows. Built upon a unified 4-pillars architecture (**Control, UAS, Memory, Domain**), it transforms autonomous AI agents from unpredictable chat bots into deterministic, auditable, and secure enterprise workers.

Paired with **OmniLedger**, its primary business domain pipeline, SentinelFleet automates complex, statutory-compliant accounts payable (AP) and tax compliance workflows under German and European law (**§ 14 UStG**, **§ 147 AO**, **GoBD**). It autonomously ingests multi-format invoices, audits statutory mandatory requirements, resolves math discrepancies, triggers Human-in-the-Loop (HITL) approval gates, and closes communication loops with suppliers via self-healing dispute notices.

```
+-----------------------------------------------------------------------------------+
|                           SENTINELFLEET CONTROL CENTER                            |
|             (Unified Operator GUI · Light-Default · Canva/Stripe Tokens)          |
+-----------------------------------------------------------------------------------+
       |                            |                           |
       v                            v                           v
+---------------+           +---------------+           +---------------+
| PILLAR CONTROL|           |  PILLAR UAS   |           | PILLAR MEMORY |
| - Zero-Trust  |           | - TaskMaster  |           | - USMC Bank   |
|   Gateway     | <=======> | - TicketMaster| <=======> | - GARDENER RAG|
| - Model Armor |  (Clutch) | - Swarm Mesh  |  (Hooker) | - Evidence    |
| - PII Filter  |           | - Event Bus   |           |   Reasoner    |
+---------------+           +---------------+           +---------------+
                                    |
                                    v
                        +-----------------------+
                        |     PILLAR DOMAIN     |
                        |   (OmniLedger Task)   |
                        | - Multimodal Vision   |
                        | - § 14 UStG Compliance|
                        | - Self-Healing Loop   |
                        | - DSGVO Contact Hub   |
                        +-----------------------+
```

---

## 2. Synthesis of Source Subsystems & Repositories

SentinelFleet unifies and hardens codebases, patterns, and research from several specialized internal and local repositories:

| Source Module / Subsystem | Canonical Local Path | Architectural Contribution to SentinelFleet |
|---|---|---|
| **`.CONTROL`** (`.armor`, `.gateway`, `.clutch`) | `OneDrive/.TOPICS/.AI/.CONTROL` | Zero-Trust Model Armor (regex + semantic injection detection), Agent Gateway scoping (PoLP), Dynamic Intent Dispatcher (`clutch`). |
| **`.RUNTIME` / UAS** (`.uas`) | `OneDrive/.TOPICS/.AI/.RUNTIME/.uas` | Universal Autonomous System: `task_master.py` (idempotent state tracking), `ticket_master.py` (HITL ask-gates), `lifecycle_manager.py`. |
| **`.MEMORY`** (`.bank`, `.gardener`, `.hooker`) | `OneDrive/.TOPICS/.AI/.MEMORY` | Curated USMC Memory Bank (`fact`, `lesson`, `policy`, `entity`), GARDENER RAG vector search, Just-in-Time Context Injector (`letter-hooker`). |
| **`.UMBRUCH` Mail** | `OneDrive/.TOPICS/.UMBRUCH/.UmbruchMail` | GDPR protection level model (S1-S4), statutory retention periods (§ 147 AO), automated deletion and deadline checks (`dsgvo-check`). |
| **`DEV_PrivacyMailDesk_SOCIAL`** | `OneDrive/.TOPICS/.SOFTWARE/MAIL/...` | Local-first zero-cloud CRM architecture, **tombstone principle** (locked deletion markers prevent re-ingestion and unauthorised mail dispatch). |
| **`.SKILLS` Repository** | `OneDrive/.TOPICS/.AI/.SKILLS/skills` | 32 standardised, bilingual, Google-Cloud-branded enterprise skills following the **Component-v1** schema. |
| **`ProfiPrompt` Library** | `OneDrive/.TOPICS/.AI/.PROMPTS` | ProfiPrompt v1 schema with SemVer versioning, change history and role-based visibility (`organization`, `restricted`, `public`). |

---

## 3. The 4-Pillars Architecture

### Pillar 1: Control (Security & Zero-Trust Defense)
* **Model Armor (`model_armor.py`):** Real-time interception engine analyzing inbound user prompts, document OCR text, and sub-agent thought trajectories for indirect prompt injection attacks, delimiter hijacking (`---END---`), and role tampering. Triggers automated agent quarantining and circuit breaking.
* **Agent Gateway (`gateway.py`):** Enforces the Principle of Least Privilege (PoLP). Each agent has an immutable allowlist of tools (`allowed_tools`). Any invocation of sensitive tools (e.g., `send_external_email`, `execute_payout`) is trapped by an `ask`-gate.
* **PII & Secrets Redaction (`model_armor.py`):** Replaces IBANs, credit card numbers and API keys in tool arguments with fixed redaction markers (`[REDACTED_IBAN]`, `[REDACTED_CREDIT_CARD]`, `[REDACTED_API_KEY]`) before the call is executed or traced.

### Pillar 2: UAS (Universal Autonomous System & Taskmaster)
* **Lifecycle Manager (`lifecycle.py`):** Controls the state machine of 9 fleet agents (`IDLE`, `ACTIVE`, `WAITING_APPROVAL`, `QUARANTINED`, `ERROR`).
* **TaskMaster (`task_master.py`):** Manages task records and guards their state machine (`QUEUED` ➔ `IN_PROGRESS` ➔ `AWAITING_APPROVAL` ➔ `COMPLETED` / `FAILED`); terminal states are final. Operator-created tasks are queued — no worker executes them in this build.
* **TicketMaster (`ticket_master.py`):** The Human-in-the-Loop (HITL) gatekeeper. Whenever an agent requires permission, an immutable ticket with priority (`NORMAL`, `HIGH`, `CRITICAL`) and structured payload is created for the operator.
* **Swarm Conductor (`swarm.py`):** Scaffold for multi-agent fan-out on Cloud Run. The current build dispatches the OmniLedger workflow sequentially through the gateway and traces every step; parallel Pub/Sub distribution is designed for, not yet implemented.

### Pillar 3: Memory (USMC Bank & Context Hooker)
* **USMC Memory Bank (`bank.py`):** Persistent corporate memory partitioned into four core taxonomies:
  * `fact`: Verified operational facts and company constants.
  * `lesson`: Learnings from past runs (e.g., supplier payment terms, discount habits).
  * `policy`: Statutory rules (e.g., § 14 UStG, GoBD requirements).
  * `entity`: Vendor and customer master profiles.
* **GARDENER RAG (`gardener_rag.py`):** In-memory retrieval engine over tax law and accounting guideline chunks. The shipped implementation ranks by keyword overlap; the chunk model is prepared for a vector index but no embeddings are computed in this build.
* **Dynamic Context Injector (`hooker.py`):** Injects matching policies and memory clues directly into agent system prompts just-in-time before inference.

### Pillar 4: Domain (OmniLedger AP Finance Taskmaster)
* **Multimodal PDF Vision Extractor (`extractor.py`):** Leverages Gemini 3.5 Flash Multimodal Vision to extract header metadata, line items, VAT rates, and gross/net values with pixel precision.
* **§ 14 UStG Compliance Auditor (`compliance.py`):** Deterministic legal validator checking 8 mandatory German statutory invoice requirements (valid VAT ID format, mandatory address, invoice date, sequential number, math consistency).
* **Autonomous Self-Healing Dispute Loop (`dispute_loop.py`):** If a compliance breach is detected, the agent drafts a polite, statutory correction request to the supplier, pauses the automated payment run, and generates an approval ticket.
* **Firestore Ledger Reconciler (`reconciliation.py`):** Posts audited invoices to Google Cloud Firestore with DATEV-compatible booking keys.

---

## 4. DSGVO Privacy Contacts Hub & Address Book

SentinelFleet features a dedicated privacy and address book layer synthesizing `.UMBRUCH/.UmbruchMail` and `DEV_PrivacyMailDesk_SOCIAL`:

```
+---------------------------------------------------------------------------------+
|                       DSGVO PRIVACY CONTACTS HUB                                |
+---------------------------------------------------------------------------------+
| Protection Level | Retention Period  | Statutory / Business Justification       |
|------------------|-------------------|------------------------------------------|
| S1               | 6 Months          | Ad-hoc project inquiries / tenders       |
| S2               | 12 Months         | Business development & pre-contractual   |
| S3 (Default)     | 36 Months / 3 Yrs | Tax & accounting records (§ 147 AO)      |
| S4               | Permanent         | Key institutional partners until revoke  |
+---------------------------------------------------------------------------------+
| Safe Gate: validate_send_permission() -> Checks Opt-Out & Tombstone status      |
| Tombstone Guard: Unsubscribed contacts are locked to prevent re-contacting      |
+---------------------------------------------------------------------------------+
```

### Key Capabilities:
1. **Pre-Send Verification:** Before any dispute email is dispatched by `agent:vendor-dispute`, `validate_send_permission()` verifies that the recipient has not opted out.
2. **Tombstone Principle:** When a contact revokes consent, their entry is marked with `is_tombstone = True`. The email is blocked permanently, preventing sub-agents from re-adding the contact from future parsed emails.
3. **Automated Retention Audit:** `run_dsgvo_retention_audit()` regularly verifies that stored contacts comply with European data protection regulations.

---

## 5. Enterprise Skills & Governance (32 Skills)

All 32 skills in SentinelFleet follow the **ControlCenter Component-v1** specification:

```yaml
---
name: ustg-statutory-auditor
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Deterministic statutory compliance validator checking § 14 UStG requirements.
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
required_tools:
  - validate_tax_compliance
tags: [tax, ustg, compliance, legal]
---
```

### Full Skill Catalog (32 Skills):
* **Domain (7):** `tax-compliance-v1`, `pdf-vision-extractor`, `multimodal-imap-grabber`, `autonomous-vendor-dispute`, `tax-reconciliation-ledger`, `ustg-law-compliance-checker`, `google-web-reading`.
* **Control (6):** `model-armor-sentry`, `model-armor-defense-guard`, `preflight-guardrail-enforcer`, `pii-redactor-and-sanitizer`, `sentinel-persona-router`, `adaptive-llm-router`.
* **UAS (6):** `task-lifecycle-maintainer`, `gemini-dag-orchestrator`, `hitl-triage-master`, `cloudrun-swarm-conductor`, `cloudrun-adaptive-scheduler`, `cloud-pubsub-event-mesh`.
* **Memory (5):** `memory-bank-connector`, `dynamic-context-injector`, `multimodal-document-chunker`, `chain-of-evidence-reasoner`, `controlcenter-skill-discovery`.
* **Assist, Dev & Utilities (8):** `google-calendar-scheduler`, `gemini-audio-transcriber`, `fleet-dossier-briefing`, `canva-ui-stylist`, `audit-incident-protocol`, `runtime-anomaly-detector`, `enterprise-plugin-engine`, `gemini-bilingual-sync`.

---

## 6. Operator Control Center Web Dashboard

The frontend is served directly via FastAPI + Jinja2 and vanilla JavaScript/CSS (`style.css`), adhering strictly to the Canva/Stripe light-default enterprise aesthetics:

* **8 Navigation Tabs:**
  1. `🎛️ 4-Pillars Overview` — Live demo trigger buttons and 4-column architecture health.
  2. `🏢 Enterprise Domains (4)` — Multi-tenant domain hub (OmniLedger, CloudOps, Legal Sentry, Vendor Ops).
  3. `📇 Privacy Contacts (4)` — DSGVO address book with protection levels, tombstone indicators, and opt-out buttons.
  4. `👥 Fleet & Tasks (9)` — Fleet directory, quarantine release actions, and TaskMaster execution table.
  5. `📥 Tickets & Approvals` — HITL queue for operator triage, approval, and rejection.
  6. `🧠 Memory Bank` — USMC facts, policies, lessons, and entities.
  7. `📝 Prompts & Skills (32)` — ProfiPrompt v1 and Skill governance with version bumping and permission modals.
  8. `📊 OpenTelemetry Spans` — Distributed traces and audit logs.
* **Live Interactive Demo Trigger Panel:**
  * **Scenario 1 (Valid Invoice):** Extracts data, passes audit, books to Firestore ledger.
  * **Scenario 2 (Missing VAT ID):** Detects violation, triggers dispute email generation, creates approval ticket.
  * **Scenario 3 (Math Inconsistency):** Identifies net/tax gross mismatch, pauses payment.
  * **Scenario 4 (Prompt Injection Attack):** Model Armor intercepts adversarial payload, quarantines agent.

---

## 7. Verification & Automated Test Suite

The entire codebase is validated by a rigorous Pytest test suite covering unit logic, security guardrails, memory RAG, and web APIs:

```bash
python -m pytest tests -v
```

### Test Results (62/62 Passed — 100% Green):

The roster below lists 56 test functions; the seven parametrised cases of
`test_settings_read_environment_overrides` are named once and counted individually above.

* `test_gateway_enforces_tool_scoping` — PASSED
* `test_gateway_denies_forbidden_tool_by_permission_registry` — PASSED
* `test_gateway_locks_quarantined_agent` — PASSED
* `test_gateway_triggers_hitl_approval_for_ask_permission` — PASSED
* `test_sources_contain_no_german_outside_whitelist` — PASSED
* `test_whitelist_has_no_stale_entries` — PASSED
* `test_templates_declare_english_language` — PASSED
* `test_component_v1_yaml_loader_and_32_skills` — PASSED
* `test_skill_not_found_error` — PASSED
* `test_async_model_armor_non_blocking_and_recursion` — PASSED
* `test_strict_task_master_errors_and_persistence` — PASSED
* `test_strict_ticket_master_errors_and_persistence` — PASSED
* `test_privacy_contacts_strict_errors_and_tombstones` — PASSED
* `test_gateway_concurrency_lock` — PASSED
* `test_create_custom_ticket` — PASSED
* `test_create_custom_task` — PASSED
* `test_create_custom_memory` — PASSED
* `test_prompt_version_bump_and_permissions` — PASSED
* `test_get_domains` — PASSED
* `test_privacy_contacts_crud_and_opt_out` — PASSED
* `test_memory_bank_store_and_search` — PASSED
* `test_gardener_rag_search` — PASSED
* `test_memory_hooker_injects_context` — PASSED
* `test_model_armor_detects_prompt_injection` — PASSED
* `test_model_armor_allows_benign_prompt` — PASSED
* `test_model_armor_sanitizes_pii_and_secrets` — PASSED
* `test_valid_invoice_flow` — PASSED
* `test_missing_vat_triggers_dispute_loop` — PASSED
* `test_dispute_draft_embeds_retrieved_memory_context` — PASSED
* `test_math_error_triggers_compliance_block` — PASSED
* `test_model_tiers_are_gemini_35_or_newer` — PASSED
* `test_router_selects_fast_tier_by_default` — PASSED
* `test_router_escalates_on_high_complexity` — PASSED
* `test_router_honours_a_custom_strategy` — PASSED
* `test_default_model_setting_is_gemini_35` — PASSED
* `test_settings_read_environment_overrides` — PASSED
* `test_cloud_trace_flag_defaults_to_false` — PASSED
* `test_local_store_crud_roundtrip` — PASSED
* `test_local_store_persists_and_reloads` — PASSED
* `test_get_store_returns_local_store_outside_production` — PASSED
* `test_firestore_store_uses_the_cloud_client` — PASSED
* `test_firestore_store_falls_back_when_the_client_is_unavailable` — PASSED
* `test_firestore_store_survives_a_failing_client` — PASSED
* `test_spans_reach_the_opentelemetry_exporter` — PASSED
* `test_error_status_is_propagated_to_the_span` — PASSED
* `test_both_buffers_are_bounded_and_ids_stay_unique` — PASSED
* `test_health_endpoint` — PASSED
* `test_blueprint_renders_html` — PASSED
* `test_omniledger_process_api` — PASSED
* `test_ticket_create_and_approve` — PASSED
* `test_contact_create` — PASSED
* `test_prompt_create_and_version` — PASSED
* `test_skills_listing` — PASSED
* `test_task_create_is_queued_not_executed` — PASSED
* `test_quarantine_release_after_model_armor_block` — PASSED
* `test_telemetry_status_reports_real_exporter` — PASSED

---

## 8. Deployment & Quickstart

```bash
# 1. Clone repository
git clone https://github.com/ellmos-ai/sentinel-fleet.git
cd sentinel-fleet

# 2. Install dependencies
pip install -e .

# 3. Start Control Center
python app.py

# 4. Open Control Center in Browser
# http://localhost:8080
```
