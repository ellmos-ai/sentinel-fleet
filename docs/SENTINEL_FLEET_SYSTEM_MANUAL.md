# SentinelFleet & OmniLedger — Technical System Manual & Architecture Guide

> **Project:** SentinelFleet (Enterprise Multi-Agent Platform & Autonomous Taskmaster)  
> **Repository:** [github.com/ellmos-ai/sentinel-fleet](https://github.com/ellmos-ai/sentinel-fleet)  
> **Google Cloud Hackathon 2026:** Track 1 (Autonomous Taskmaster) & Track 3 (Enterprise Multi-Agent Governance)  
> **Target Runtime:** Google Cloud Run, Gemini 3.5 to 3.7 Flash via the Google GenAI SDK (`google-genai`), Google Cloud Firestore, OpenTelemetry with Cloud Trace export in the documented deployment profile
> **Public Demo:** [Cloud Run control center](https://sentinel-fleet-kcdkv76yqq-ey.a.run.app) · [3:20 guided video](https://youtu.be/Ab5kHsHo2fQ) · [Devpost project](https://devpost.com/software/sentinelfleet-o3v56y)

---

## 1. Executive Summary

**SentinelFleet** is a fortified enterprise-agent control-plane and taskmaster demonstration. Built upon a unified 4-pillars architecture (**Control, UAS, Memory, Domain**), it makes model calls, policy decisions and task hand-offs inspectable and fail-closed at their implemented gates. The public hackathon build deliberately has no human login and isolates anonymous browser workspaces. Non-demo mode verifies signed Google IAP assertions and maps immutable claims to registered, active users; deployment still requires the operator to configure IAP and its explicit user map.

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
| **`.MEMORY`** (`.bank`, `.gardener`, `.hooker`) | `OneDrive/.TOPICS/.AI/.MEMORY` | Original visible USMC taxonomy (`Fact`, `Lesson`, `Entity`, `Policy`), now migrated on read to `facts`, `lessons`, `working`, `sessions`; GARDENER RAG and Just-in-Time Context Injector (`letter-hooker`). |
| **`.UMBRUCH` Mail** | `OneDrive/.TOPICS/.UMBRUCH/.UmbruchMail` | Source concept for the S1-S4 protection model and deadline review. SentinelFleet reports due records for human review; it does not make an automatic legal deletion decision. |
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
* **TaskMaster (`task_master.py`):** Manages task records and guards their state machine (`QUEUED` ➔ `IN_PROGRESS` ➔ `AWAITING_APPROVAL` ➔ `COMPLETED` / `FAILED` / `CANCELLED`); terminal states are final. An operator may cancel a task that has not started; a running one may not be cancelled, because a run here is synchronous. Operator-created tasks are queued — no worker executes them in this build.
* **TicketMaster (`ticket_master.py`):** The Human-in-the-Loop (HITL) gatekeeper. Whenever an agent requires permission, an immutable ticket with priority (`NORMAL`, `HIGH`, `CRITICAL`) and structured payload is created for the operator.
* **Swarm Conductor (`swarm.py`):** Scaffold for multi-agent fan-out on Cloud Run. The current build dispatches the OmniLedger workflow sequentially through the gateway and traces every step; parallel Pub/Sub distribution is designed for, not yet implemented.

### Pillar 3: Memory (USMC Bank & Context Hooker)
* **USMC Memory Bank (`bank.py`):** Persistent corporate memory partitioned into the current four core taxonomies:
  * `facts`: Verified operational facts; legacy `fact`, `policy` and `entity` records map here.
  * `lessons`: Learnings from past runs; legacy `lesson` maps here.
  * `working`: Active working context and the fail-safe target for unknown legacy categories.
  * `sessions`: Session checkpoints and reconciliation write-backs; legacy `session` and `session_checkpoint` map here.
  The legacy source/UI vocabulary was `Fact`, `Lesson`, `Entity`, `Policy`; the earliest internal bank comment used `session_checkpoint` instead of `policy`. The original label is retained as migration metadata where applicable.
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
| S4               | Until revocation  | Key institutional partners                |
+---------------------------------------------------------------------------------+
| Safe Gate: validate_send_permission() -> Checks Opt-Out & Tombstone status      |
| Tombstone Guard: Unsubscribed contacts are locked to prevent re-contacting      |
+---------------------------------------------------------------------------------+
```

### Key Capabilities:
1. **Pre-Send Verification:** Before any dispute email is dispatched by `agent:vendor-dispute`, `validate_send_permission()` verifies that the recipient has not opted out.
2. **Tombstone Principle:** When a contact revokes consent, their entry is marked with `is_tombstone = True`. The email is blocked permanently, preventing sub-agents from re-adding the contact from future parsed emails.
3. **Operational Retention Audit:** `run_dsgvo_retention_audit()` reports S1-S4 records whose configured review window is due. It does not delete automatically and is not itself a legal-compliance determination.

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
  6. `🧠 Memory Bank` — USMC `facts`, `lessons`, `working`, and `sessions`, with legacy labels mapped on read.
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
### Test Results: 560 passed (full suite, verified 2026-08-22)

The suite covers the gateway (scoping, quarantine, HITL), model armor, the
OmniLedger workflow, chat and race (including live-path failure modes), task
templates with routine/schedule bindings and the `/api/routines/fire` trigger,
storage (local and mocked Firestore), i18n regression, and every dashboard
surface. One upstream Starlette/httpx deprecation warning remains visible and does not fail the
suite. Run it yourself to reproduce the stated count.

The same generated architecture circuit is live at
[`/blueprint`](https://sentinel-fleet-kcdkv76yqq-ey.a.run.app/blueprint); the current source and
public deployment both expose 51 modules and 157 internal imports.

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

---

## 9. Task Templates, Routines & the Cloud Scheduler Trigger

A `TaskTemplate` (`uas/task_templates.py`) is the "everything is a task" foundation: a prompt
(custom text, or a pinned `PromptItem` version), a skill selection, an assigned agent and an
approval flag. It describes *what* runs, never *when*. Two independent bindings
(`uas/routines.py`) can be attached to make it recurring or dated:

* **`RoutineBinding`** — `schedule_spec` in the interval/daily/cron format (`{"kind": "interval",
  "seconds": 3600}`, `{"kind": "daily", "time": "04:00", "timezone": "Europe/Berlin"}`,
  `{"kind": "cron", "expression": "*/15 * * * *"}`), an `enabled` flag, and a `miss_policy` of
  `skip` or `catch_up` for occurrences missed while Cloud Run was scaled to zero.
* **`ScheduleBinding`** — a one-off `due_at`, kept around after it fires or is skipped as a
  run-history row.

Neither binding is a stored "template type" — both the gear/clock badges and the
running/preparing/idle runtime colour in the dashboard's **Tasks** table (next to the existing
Task queue table, both in the Fleet tab) are derived on
every read, never stored, the same principle the Routinika desktop app uses to derive
`item_type` from two flags instead of storing it. The two derivations read different sources,
though: `routines.derive_symbols` reads the current bindings (a routine attached → gear; a
still-`pending`, not-yet-due `ScheduleBinding` → clock, so the clock disappears on its own once
`due_at` passes, with nothing to update it), while `routines.derive_runtime_status` reads only
this template's own `TaskRecord`s — green if any is `IN_PROGRESS`, yellow if any is `QUEUED` or
`AWAITING_APPROVAL`, otherwise no colour, running always beating preparing. This is deliberately
not a `next_due_at` lookahead: an immediately "enqueue now" run and a routine- or
schedule-triggered one go through the identical `QUEUED → IN_PROGRESS → terminal` path on the
same `TaskRecord`, so the colour rule needs no special case for either origin. A template becomes
deletable again only once both bindings are gone (`routines.delete_template`,
`TemplateHasBindingsError` otherwise); only its `owner` may delete it at all, while any other
viewer can remove it from their own listing without touching it for anyone else
(`remove_for_viewer`).

`TaskTemplate.steps` is the canonical storage shape for both a single task and a linear chain.
`TaskTemplate.assigned_agent`/`prompt_source`/`prompt_id`/`prompt_version`/
`custom_prompt_text`/`skill_ids` remain computed compatibility properties over `steps[0]`, not a
second copy. `POST /api/task-templates` accepts either the flat single-step form or an explicit
`steps` JSON array; the step editor can then edit the ordered chain.

The chain runner supports three validated execution patterns: `single`, `race` and bounded
`research` (one to five operator-named URLs). Multi-step
templates and even a one-step race go through `core/chain_runner.py`; a one-step `single` task
keeps the original direct path and response shape. Every model call still crosses the Sovereign
Gateway. Previous output and research-source content are handed on as clearly marked untrusted
user context, never promoted into system instructions. `parallel_group`, loops and unsupported
input specifications are rejected before persistence because no executor exists for them yet.

**Execution** (`routines.enqueue_template`) creates a real `TaskRecord` — not a second, parallel
run object — carrying `source_template_id`/`source_binding_id`/`triggered_by`, and drives it
through the same `SovereignGateway.execute_tool_call` path the chat console uses: an agent
identity, Model Armor, the permission registry, and the same `chat_service` backend seam, tagged
with the tool name `execute_template`. Without `GEMINI_API_KEY` it answers in the same
deterministic-demo mode as every other model call in this app. A template with
`requires_approval=True` is queued straight into `AWAITING_APPROVAL` and opens a
`ticket_master` approval ticket instead of calling a model — the same Human-in-the-Loop gate
`send_external_email` uses, applied per-template rather than per tool name.

**`POST /api/routines/fire`** (`web/server.py`) is the trigger endpoint for **Google Cloud
Scheduler**. SentinelFleet runs on Cloud Run with scale-to-zero (`core/storage.py` reads
`K_SERVICE` as its production signal), so an in-process tick loop would lose its state on every
scale-down and would need an external wakeup anyway — Cloud Scheduler's HTTP trigger is that
wakeup and the trigger source at once. A process-wide async lock serialises each call before it
claims due work. Each call enqueues every `RoutineBinding` whose
`next_due_at` has passed and every `pending` `ScheduleBinding` whose `due_at` has passed, then
recomputes `next_due_at` strictly forward. With the documented Cloud Run limit of one instance,
two overlapping triggers cannot enqueue the same tick twice. This is deliberately not presented
as a distributed Firestore transaction: scaling beyond one instance first requires a durable
lease/idempotency claim. A
`ScheduleBinding` more than 15 minutes past due is treated as missed and follows its
`miss_policy` (`skip` marks it `skipped` without a run, `catch_up` still fires it late); a
`RoutineBinding`'s backlog is drained one run per `/fire` call under `catch_up`, or dropped
entirely (resuming from "now") under `skip`. The date math itself (`core/schedule_math.py`) is a
small, dependency-free `next_after()` implementing the same `interval`/`daily`/`cron` contract as
`ellmos_scheduler.schedules` — that package is internal and not published to PyPI, so this is a
vendored copy of the pure date-math function, not an import of its SQLite job store or tick loop.

For a local demo the endpoint stays open (with a logged warning) when `ROUTINES_FIRE_TOKEN` is
unset; setting it requires callers to send the same value as the `X-Fire-Token` header. A real
deployment must set that token in the Cloud Scheduler job's HTTP target, or invoke the endpoint
through an OIDC-authenticated Cloud Run service-to-service call. Cloud Run without a token fails
closed with HTTP 503.

The binding matrix reserves `process` as an **optional extension point**. It is not required for
ordinary execution: Task Templates own validated steps, Task Records represent runs, and
Routine/Schedule bindings trigger those templates. A Process Registry is only needed when an
organization wants one durable business-process object to span multiple templates or runs. The
future registry connects at this point and must provide stable process IDs, version and status,
owner/organization/department scope, links to templates and runs, policy-binding validation,
runtime enforcement and audit evidence. No such registry is installed in this MVP, so process
binding requests fail closed.

**Not in this MVP:** an installed process registry for process-policy bindings, parallel chain groups,
executable loops, a distributed scheduler
lease for multi-instance operation, the `idle_window` trigger kind, and a console/COMA execution
path as an alternative to the Gemini chat backend. Public-demo administration remains locked;
non-demo administration is available only through a verified IAP principal with the relevant
capability. Chat sessions are private/shareable/exportable but do not yet have a self-service
delete, retention or legal-hold lifecycle.

Two further declared boundaries from the 2026-08-22 security review: gateway scope violations
raise and are logged/traced, but only the invoice workflow path additionally quarantines the
offending demo workspace — a fleet-wide automatic quarantine policy is a design decision left
open on purpose. And the very first parallel requests of a cookie-less browser session may mint
competing workspace tokens; the browser settles on one, and the loser's (empty) workspace simply
expires with the demo data.
