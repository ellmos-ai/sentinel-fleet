<img src="assets/banner.svg" width="100%" alt="SentinelFleet — Fortified Enterprise Agent Platform">

# SentinelFleet — Fortified Enterprise Agent Platform & OmniLedger Taskmaster

[![Google Cloud Run](https://img.shields.io/badge/Google%20Cloud-Cloud%20Run-blue.svg?logo=google-cloud)](https://cloud.google.com/run)
[![Gemini 3.5](https://img.shields.io/badge/Gemini-3.5%20Flash%20Vision-orange.svg)](https://deepmind.google/technologies/gemini/)
[![Zero-Trust Model Armor](https://img.shields.io/badge/Security-Model%20Armor%20%26%20Zero--Trust-green.svg)](#security--governance)
[![Google GenAI SDK](https://img.shields.io/badge/SDK-google--genai-4285F4.svg)](https://googleapis.github.io/python-genai/)
[![Pytest](https://img.shields.io/badge/pytest-passing-brightgreen.svg)](tests/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)

> Built for the **Google Cloud All Things Agentic Hackathon** (Track 3: The Fortified Enterprise Fleet & Track 1: The Taskmaster).

---

## 🌟 Executive Summary

**SentinelFleet** is a hackathon-ready demonstration of an enterprise AI agent control plane and autonomous taskmaster, built with **Gemini 3.5 Flash Vision** via the **Google GenAI SDK (`google-genai`)**, **Google Cloud Run**, and **Google Cloud Firestore**. The controls are real and tested; authentication is deliberately not claimed by this public demo.

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
* **S1–S4 Protection Levels:** Configured retention-audit windows (S1: 183 days, S2: 365 days, S3: 1095 days, S4: until revocation). Due records are reported for human review; the software does not make a legal deletion decision automatically.
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

## 💬 Governed Chat Console & Model Race

The operator console carries a chat tab in which **every model call takes the same path as the
document pipeline**: `model_armor.inspect_prompt` scans the message, then
`gateway.execute_tool_call` runs it under a registered agent identity with that agent's
least-privilege scope, PII sanitisation and permission gate. There is no second, unguarded route
to a model.

* **Composed system prompt:** fleet base prompt + the bodies of the skills you select from the
  registry + one **pinned version** of a prompt template. Pinning matters: a later version bump
  cannot silently change what a recorded conversation ran on.
* **Race mode:** one prompt, two or more models, dispatched with `asyncio.gather`. Each lane runs
  under its **own agent identity** (`agent:race-lane-1..4`) because the gateway locks per agent —
  lanes sharing an identity would queue and the latencies would measure the queue. Optional judge
  scores the lanes on quality, correctness, completeness, instruction fidelity and latency;
  latency is one dimension, not the ranking.
* **Export:** any transcript as Markdown, plain text, styled HTML or PDF. Every exported turn
  carries the mode it ran in, so provenance survives leaving the console.
* **Honest demo mode:** without `GEMINI_API_KEY` the console answers with the request it actually
  assembled and labels the turn `demo`, rather than presenting invented text as a model reply.
  The judge refuses to score demo lanes outright — a labelled simulated latency is still a number,
  an invented quality rating would be fabricated evidence.

---

## 🗓️ Tasks & Routines

Everything the fleet runs is a `TaskTemplate` — a prompt (custom or a pinned library version)
plus a skill selection, an assigned agent and an approval flag. A template describes *what*
should happen, never *when*. Attaching a `RoutineBinding` (recurring: interval / daily / cron)
or a `ScheduleBinding` (a one-off `due_at`) turns it recurring or dated; removing both bindings
leaves a bare, deletable template again — a template never migrates between object types. The
gear/clock badges (from the bindings) and the running/preparing/idle status dot (from this
template's own `TaskRecord`s, never a next-due lookahead) in the **Tasks** table (Fleet tab,
next to the existing Task queue table) are all derived on every read, never stored.

Running a template goes through the same `SovereignGateway` path as the chat console — an agent
identity, model armor, permission gate — and produces a real `TaskRecord` in the existing Task
queue (tagged with its `source_template_id`, so a template run is a view of that one queue, not
a second list). Without `GEMINI_API_KEY` it answers in the same honest deterministic-demo mode
as everywhere else in this app.

Templates may contain a validated linear chain of steps. The step editor supports `single`
model calls and `race` steps; outputs are handed to the next step as clearly marked untrusted
user context. Multi-step templates and one-step races use the audited chain runner. A one-step
`single` template keeps the original direct execution path and response shape. Parallel groups
and loops are schema-reserved but rejected until they have an executor.

**`POST /api/routines/fire`** is the trigger target for **Google Cloud Scheduler**: SentinelFleet
runs on Cloud Run with scale-to-zero, so there is no in-process tick loop — Cloud Scheduler wakes
the service and calls `/fire`, which enqueues whatever routine or one-off schedule is due and
applies each binding's `skip`/`catch_up` policy to anything missed while the service was scaled
down. The endpoint is idempotent by construction (firing always pushes the next due time
forward) and, for local development, open with a logged warning unless `ROUTINES_FIRE_TOKEN` is
set — a real deployment should set it and have Cloud Scheduler send it as `X-Fire-Token`, or call
the endpoint through an OIDC-authenticated Cloud Run invocation instead. `fire_due()` serialises
concurrent calls inside one process. The documented Cloud Run deployment therefore uses one
maximum instance; there is no claim of a cross-instance Firestore lease yet.

---

## 👤 Users & Federated Policy Governance

The Governance tab projects tool permissions, code-level PolicyEngine checks and user-authored
policies into one catalogue without copying their enforcement state. Permission and engine
entries are read-only. The only writable slot accepts advisory user declarations and labels
them `not-enforced (user declaration)` until a real executor exists.

Four role profiles (administrator, operator, member and viewer) and reasoned per-user deviations
feed one `explain_binding()` decision function. Its R1–R7 verdict is used by the API, the
5-target × 4-scope matrix and the binding ledger: `allow` activates, `forward` creates a ticket
for the target user or an administrator, and `deny` refuses. Process bindings remain visible as
a planned matrix dimension but are not writable until a process registry exists.

In `DEMO_MODE=true`, `?user=` and legacy `?viewer=` are ignored for display, reads and writes;
safe writes are pinned server-side to `member:demo`, and security-root administration remains
locked. In `DEMO_MODE=false`, every HTTP request and run-log WebSocket validates IAP's signed JWT,
its audience and issuer, then resolves `sub` or `email` through the explicit `IAP_USER_MAP` to one
registered user. Missing, forged, suspended or unmapped identities fail closed; unsigned identity
headers are never trusted.

User deletion writes an irreversible, PII-minimized identity tombstone instead of freeing the
identifier for reuse. This prevents a later account with the same ID from inheriting historical
owner-scoped records. Suspension is the reversible offboarding path; owned business-data transfer
or erasure remains a separate, explicit administrative workflow.

Private demo data does not use the display alias. Each browser receives an unguessable HttpOnly
workspace token; record ownership and named sharing use only a domain-separated SHA-256 handle,
never the cookie secret. Private chat histories, contacts, memory and documents are filtered by
that derived owner handle.
All scoped record types support department and deployment-wide visibility. Chats and generated
results additionally support named shares; only the creator changes chat/document sharing or
writes to a shared chat. Chat sessions currently have no self-service delete, retention or legal-hold
workflow; that lifecycle remains an explicit post-MVP boundary. Generated chat exports and correction letters are stored before download, private by default,
and may be downloaded or deleted only after their record-level access check. The
Governance tab lists these storage and access boundaries explicitly.

---

## ⌁ Architecture Blueprint: Two Views

`/blueprint` serves the pipeline walkthrough and a **module interdependency circuit**. The circuit
is not drawn by hand: every node is a module under `src/sentinel_fleet` and every trace is an
import statement parsed out of it with `ast` on each request, laid out so an importer sits left of
everything it imports. Hover a module to isolate what it wires into. The diagram cannot drift from
the code, and the test suite checks every edge back against the importing module's source.

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
Open **`http://localhost:8080`** for the operator console, the chat and race tabs, and the architecture blueprint.

### 2. Run Tests
```bash
python -m pytest tests/ -v
```

### 3. Reset the demo data

Every local metadata store the console writes to lives as JSON under `data/`; result-document
bytes live under `data/artifacts/`. Both are gitignored. Deleting them puts the deployment back
to its first-run state: the seeded agents, skills, prompts, contacts and task templates are
recreated on the next start, and everything a session added is gone.

```bash
rm data/*.json
rm -rf data/artifacts     # then restart: python app.py
```

There is no script and no reset button on purpose. Wiping a governed system's evidence should
take a deliberate act at the filesystem, not a click in the surface that produced the evidence.

### 4. Deploy to Google Cloud Run

This deployment template matches the current source requirements (project ID and file paths
generalised; secret values never leave Secret Manager). Running it changes the live service;
the repository update itself does not deploy anything:

```bash
# One-time: create a dedicated runtime identity, store secrets, and create a private
# uniform-access result bucket. Do not use the project's default Editor identity.
gcloud iam service-accounts create sentinel-fleet-runtime
gcloud secrets create gemini-api-key --data-file=gemini_api_key.txt
gcloud secrets create routines-fire-token --data-file=fire_token.txt
gcloud storage buckets create gs://<your-result-bucket> --location=europe-west3 --uniform-bucket-level-access
gcloud projects add-iam-policy-binding <project-id> \
  --member="serviceAccount:sentinel-fleet-runtime@<project-id>.iam.gserviceaccount.com" --role="roles/datastore.user"
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:sentinel-fleet-runtime@<project-id>.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding routines-fire-token \
  --member="serviceAccount:sentinel-fleet-runtime@<project-id>.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding <project-id> \
  --member="serviceAccount:sentinel-fleet-runtime@<project-id>.iam.gserviceaccount.com" --role="roles/cloudtrace.agent"
gcloud storage buckets update gs://<your-result-bucket> --public-access-prevention=enforced
gcloud storage buckets add-iam-policy-binding gs://<your-result-bucket> \
  --member="serviceAccount:sentinel-fleet-runtime@<project-id>.iam.gserviceaccount.com" --role="roles/storage.objectUser"

# Build from source (the Dockerfile copies sources BEFORE `pip install .`) and deploy
gcloud run deploy sentinel-fleet --source . --region europe-west3 \
  --service-account "sentinel-fleet-runtime@<project-id>.iam.gserviceaccount.com" \
  --set-env-vars "DEMO_MODE=true,ENABLE_CLOUD_TRACE=true,RESULT_BUCKET=<your-result-bucket>,DEMO_WORKSPACE_WRITES_PER_HOUR=30,DEMO_GLOBAL_WRITES_PER_HOUR=240,DEMO_WORKSPACE_EXTERNAL_PER_HOUR=5,DEMO_GLOBAL_EXTERNAL_PER_HOUR=60" \
  --update-secrets "GEMINI_API_KEY=gemini-api-key:latest,ROUTINES_FIRE_TOKEN=routines-fire-token:latest" \
  --max-instances 1

# Authenticated deployments only: ONE idempotent Cloud Scheduler job walks all due bindings.
# Persistent automation is disabled while DEMO_MODE=true, so anonymous visitors cannot create
# recurring model or web costs.
# Note the explicit empty JSON body — Google's front end answers 411 to body-less POSTs.
gcloud scheduler jobs create http routines-fire --location europe-west3 \
  --schedule "*/5 * * * *" --http-method POST \
  --uri "https://<your-service-url>/api/routines/fire" \
  --headers "X-Fire-Token=<your-token>,Content-Type=application/json" \
  --message-body "{}"
```

Before removing a legacy `roles/editor` grant, read back the runtime service account's project,
secret and bucket bindings and verify the narrow grants above. Only then remove Editor and read
the policy back again:

```bash
gcloud projects get-iam-policy <project-id> --flatten="bindings[].members" \
  --filter="bindings.members:sentinel-fleet-runtime@<project-id>.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
gcloud projects remove-iam-policy-binding <project-id> \
  --member="serviceAccount:sentinel-fleet-runtime@<project-id>.iam.gserviceaccount.com" --role="roles/editor"
```

For a private deployment, configure IAP for the service, set `DEMO_MODE=false`, set the exact
signed-header audience as `IAP_AUDIENCE`, and map immutable claims to existing registry IDs, for
example `IAP_USER_MAP={"email:operator@example.org":"operator"}`. The app verifies the JWT; merely
setting `X-Goog-Authenticated-User-Email` never authenticates a request.

Scale-to-zero stays intact: there is no in-process tick loop, the Scheduler wakes the
service only when bindings may be due. One process-wide lock plus `--max-instances 1` prevents
overlapping claims in this deployment. Scaling beyond one instance requires a distributed
Firestore lease/transaction first.

---

## 🔒 Security & Model Armor

* **Zero-Trust Tool Scoping:** Agents only have access to their assigned tools via `gateway.py`.
* **Fail-closed permissions:** Every seeded tool has an explicit rule; unknown tools are denied.
* **Adversarial Injection Detection:** Canonicalised boundary matching scans nested string arguments, selected prompts and skills, previous outputs and web context before model use.
* **Quarantine Protocol:** Malicious inputs immediately quarantine the executing agent. In the public demo that lock is isolated to the originating browser workspace, preventing one anonymous visitor from disabling the shared deployment; authenticated deployments retain the operator-controlled deployment quarantine.
* **Bounded public showcase:** In the single-instance public demo, rolling workspace and service-wide hourly ceilings bound persistent writes and model/web workflows. A template contains at most eight steps; each race has at most four models and each research step at most five named fetches. The global workflow ceiling cannot be bypassed by rotating the workspace cookie. This in-process guard is not a substitute for distributed rate limiting when scaling beyond one instance.
* **Bounded document intake:** Upload size, type, PDF page count, extracted text and Gemini concurrency are capped. RED, UNSCREENED or truncated privacy screens stay on the local extraction path and are never sent as raw files to Gemini.
* **Separated document retention:** Uploaded source bytes are request-scoped and not retained. Extracted/audited records are durable in Firestore (JSON locally). Generated results use creator-managed retention with no silent automatic expiry: the creator may delete them, bytes are removed and a non-content tombstone records the deletion. A legal hold blocks deletion.
* **Encrypted result storage:** Production result bytes use Cloud Storage's Google-managed AES-256 server-side encryption and HTTPS transport. Local development files are explicitly labelled plaintext and must contain synthetic data only. Downloads are proxied through the authorized API; the bucket is never made public.
* **Pinned web transport:** Every redirect hop is revalidated and the HTTP/TLS connection is pinned to the validated public IP, closing DNS-rebinding TOCTOU.
* **Deployment boundary:** The public interactive build has no login. Use only synthetic demo data. Non-demo access fails closed unless a signed IAP assertion maps to an active registered user.

---

## License

Copyright (C) 2026 Lukas Geiger.

SentinelFleet is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0-only) — see [LICENSE](LICENSE). If you run a modified version of this software as a network service, the AGPL requires you to offer its source to your users. For commercial licensing outside the AGPL terms, contact the author.

## Scope, Provenance & Data Notes

* **Demo, not advice.** The OmniLedger domain validates demo invoices against German statutory rules (§ 14 UStG, GoBD) as a technical showcase. It is an AI-assisted engineering demo — not tax, accounting or legal advice; whether any concrete use meets statutory requirements depends on the individual case.
* **Provenance.** Built by Lukas Geiger for the Google Cloud All Things Agentic Hackathon with substantial AI coding assistance (Google Gemini, Anthropic Claude); all AI-generated code was human-directed and is covered by the currently verified full test suite. Some skill definitions are English rebrands of the author's private skills library.
* **Data.** Chat messages and privacy-screened GREEN/YELLOW document uploads may be sent to the Gemini API when a `GEMINI_API_KEY` is configured. RED, UNSCREENED and truncated documents stay on the local extraction path; without a key, no model payload is sent to Gemini. Raw upload bytes are not retained; structured records, chat sessions, prompts, skills, logs and telemetry use Firestore in production, while generated result bytes use the configured private Cloud Storage bucket. The Web reader still performs operator-requested external GETs, and configured Cloud Trace receives its documented spans. Do not upload real invoices or personal data to a demo deployment, and please do not post case data in issues.
