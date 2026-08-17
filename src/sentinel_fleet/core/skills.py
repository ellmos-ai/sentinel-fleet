"""Skill Registry, Discovery & Governance Engine based on ellmos-ai/skills and ControlCenter-MCP."""

import re
import time
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SkillVersionRecord(BaseModel):
    version_id: str
    skill_id: str
    version_number: str
    change_summary: str
    required_tools: List[str]
    created_at: float = Field(default_factory=time.time)


class AgentSkill(BaseModel):
    skill_id: str
    name: str
    pillar: str  # control, memory, uas, domain, dev, assist, infrastructure, utilities
    version: str = "1.0.0"
    description: str
    required_tools: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    schema_version: str = "component-v1"
    status: str = "active"  # active, draft, deprecated
    fork_of: Optional[str] = None
    language: str = "en"
    # Permissions & Governance
    visibility: str = "organization"  # public | organization | restricted
    execution_gate: str = "auto"  # auto | ask_permission | locked
    allowed_agents: List[str] = Field(default_factory=lambda: ["*"])
    compatibility: Dict[str, bool] = Field(default_factory=lambda: {
        "google_adk": True,
        "gemini_3_5": True,
        "mcp_stdio": True,
        "cloud_run": True
    })
    versions: List[SkillVersionRecord] = Field(default_factory=list)
    updated_at: float = Field(default_factory=time.time)


class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, AgentSkill] = {}
        self._seed_default_skills()

    def _seed_default_skills(self):
        seeds = [
            # -------------------------------------------------------------
            # 1. PILLAR DOMAIN (Finance, § 14 UStG, Invoicing & Dispute)
            # -------------------------------------------------------------
            AgentSkill(
                skill_id="skill:tax-compliance-v1",
                name="§ 14 UStG Tax Compliance Auditor",
                pillar="domain",
                version="1.4.0",
                description="Automatische Prüfung gesetzlicher Pflichtangaben, USt-IdNr und mathematischer Konsistenz nach deutschem Steuerrecht.",
                required_tools=["validate_tax_compliance"],
                tags=["tax", "compliance", "ustg", "finance", "audit"]
            ),
            AgentSkill(
                skill_id="skill:pdf-vision-extractor",
                name="Multimodal PDF & Document Grabber",
                pillar="domain",
                version="2.1.0",
                description="Pixelgenaue Extraktion tabellarischer und unstrukturierter Daten mit Gemini 3.5 Flash Vision.",
                required_tools=["extract_invoice_multimodal"],
                tags=["vision", "ocr", "multimodal", "gemini", "pdf"]
            ),
            AgentSkill(
                skill_id="skill:multimodal-imap-grabber",
                name="Multimodal IMAP Grabber & Ingestion Pipeline",
                pillar="domain",
                version="1.0.0",
                fork_of="skills/utilities/mail-clean-grab",
                description="Autonomous document ingestion polling secure IMAP/Gmail API mailboxes for PDF invoices and queuing tasks.",
                required_tools=["create_task"],
                tags=["imap", "email", "invoices", "ingestion"]
            ),
            AgentSkill(
                skill_id="skill:autonomous-vendor-dispute",
                name="Autonomous Vendor Dispute & Correction Loop",
                pillar="domain",
                version="1.0.0",
                fork_of="skills/utilities/privat-mail-writer",
                description="Drafts legally grounded, polite discrepancy notices to vendors when statutory § 14 UStG errors are detected.",
                required_tools=["draft_vendor_dispute_email", "send_external_email"],
                tags=["dispute", "vendor", "self-healing", "legal"],
                execution_gate="ask_permission"
            ),
            AgentSkill(
                skill_id="skill:tax-reconciliation-ledger",
                name="Tax Reconciliation Ledger & Firestore Engine",
                pillar="domain",
                version="1.0.0",
                fork_of="skills/utilities/steuer-assistent",
                description="Reconciles validated invoices against purchase orders and posts immutable records to Google Cloud Firestore.",
                required_tools=["store_memory_bank", "create_reconciliation_draft"],
                tags=["tax", "ledger", "firestore", "reconciliation"]
            ),
            AgentSkill(
                skill_id="skill:ustg-law-compliance-checker",
                name="§ 14 UStG Statutory Tax Auditor",
                pillar="domain",
                version="1.0.0",
                fork_of="skills/utilities/law-checker",
                description="Deterministic auditor for statutory requirements under § 14 UStG with zero tolerance for math anomalies.",
                required_tools=["validate_tax_compliance"],
                tags=["tax", "ustg", "legal", "compliance"]
            ),

            # -------------------------------------------------------------
            # 2. PILLAR CONTROL (Security, Zero-Trust Armor & Routing)
            # -------------------------------------------------------------
            AgentSkill(
                skill_id="skill:model-armor-sentry",
                name="Zero-Trust Model Armor Guardrail",
                pillar="control",
                version="3.0.0",
                description="Inline Prompt Injection Scanner, Jailbreak-Blocker und PII-Maskierungsfilter (IBAN, API-Keys, Credentials).",
                required_tools=["inspect_prompt", "sanitize_pii"],
                tags=["security", "armor", "zero-trust", "guardrail"]
            ),
            AgentSkill(
                skill_id="skill:model-armor-defense-guard",
                name="Model Armor Defense Guard & Red-Team Sentry",
                pillar="control",
                version="1.0.0",
                fork_of="skills/infrastructure/metacognitive-injectors",
                description="Metacognitive red-teaming and prompt defense sentry protecting the fleet from indirect adversarial injections.",
                required_tools=["inspect_prompt"],
                tags=["security", "armor", "metacognitive", "redteaming"]
            ),
            AgentSkill(
                skill_id="skill:preflight-guardrail-enforcer",
                name="Preflight Guardrail Enforcer & Policy Gate",
                pillar="control",
                version="1.0.0",
                fork_of="skills/infrastructure/condition",
                description="Enforces deterministic pre- and post-condition invariants and transaction thresholds before tool execution.",
                required_tools=["inspect_prompt"],
                tags=["guardrails", "preflight", "invariants", "security"]
            ),
            AgentSkill(
                skill_id="skill:pii-redactor-and-sanitizer",
                name="PII Redactor & Zero-Leakage Sanitizer",
                pillar="control",
                version="1.0.0",
                fork_of="skills/utilities/llm-text-hygiene",
                description="Zero-leakage sanitization masking credit cards, IBANs, and API keys before logging to OpenTelemetry or Cloud Trace.",
                required_tools=["sanitize_pii"],
                tags=["pii", "dsgvo", "gdpr", "sanitization", "privacy"]
            ),
            AgentSkill(
                skill_id="skill:sentinel-persona-router",
                name="Sentinel Persona Router & Intent Dispatcher",
                pillar="control",
                version="1.0.0",
                fork_of="skills/infrastructure/semantic-persona-routing",
                description="Dynamic agent persona matching, tool scoping, and intent classification using the clutch routing algorithm.",
                required_tools=["query_memory_bank"],
                tags=["routing", "persona", "clutch"]
            ),
            AgentSkill(
                skill_id="skill:adaptive-llm-router",
                name="Adaptive LLM Router & Cost Optimizer",
                pillar="control",
                version="1.0.0",
                fork_of="skills/dev/model-strategy",
                description="Cost-, token-, and latency-optimized dynamic model routing between Gemini 3.5 Flash and Gemini Pro on GCP.",
                required_tools=["query_memory_bank"],
                tags=["routing", "model-strategy", "gemini", "token-optimization"]
            ),

            # -------------------------------------------------------------
            # 3. PILLAR UAS (Orchestration, Swarm, Scheduling & HITL)
            # -------------------------------------------------------------
            AgentSkill(
                skill_id="skill:task-lifecycle-maintainer",
                name="Task Lifecycle & Health Maintainer",
                pillar="uas",
                version="1.1.0",
                description="Asynchrone Task-Koordination, State-Tracking, Triage-Routing und automatische Re-Triagierung.",
                required_tools=["create_task", "update_task_state"],
                tags=["taskmaster", "lifecycle", "state", "triage"]
            ),
            AgentSkill(
                skill_id="skill:gemini-dag-orchestrator",
                name="Gemini DAG Orchestrator & Task Decomposer",
                pillar="uas",
                version="1.0.0",
                fork_of="skills/infrastructure/orchestrator",
                description="Decomposes ambiguous enterprise requests into directed acyclic graphs and coordinates parallel dispatch.",
                required_tools=["create_task", "assign_task", "dispatch_swarm"],
                tags=["orchestrator", "dag", "workflow", "decomposition"]
            ),
            AgentSkill(
                skill_id="skill:hitl-triage-master",
                name="Human-in-the-Loop Triage Master",
                pillar="uas",
                version="1.0.0",
                fork_of="skills/dev/ticket-master",
                description="Human-in-the-Loop priority queue, auto-escalation engine, and cryptographic audit receipts for ask-gates.",
                required_tools=["create_task", "verify_receipts"],
                tags=["hitl", "triage", "ticketmaster", "governance"]
            ),
            AgentSkill(
                skill_id="skill:cloudrun-swarm-conductor",
                name="Google Cloud Run Multi-Agent Swarm Conductor",
                pillar="uas",
                version="1.0.0",
                fork_of="skills/dev/swarm-operations",
                description="Orchestrates serverless multi-agent swarms, parallel map-reduce pipelines, and consensus rounds across Cloud Run.",
                required_tools=["dispatch_swarm", "assign_task"],
                tags=["swarm", "orchestration", "cloudrun", "parallel"]
            ),
            AgentSkill(
                skill_id="skill:cloudrun-adaptive-scheduler",
                name="Cloud Run Adaptive Scheduler & Workload Tuner",
                pillar="uas",
                version="1.0.0",
                fork_of="skills/infrastructure/cron-tuner",
                description="Dynamic rate-limiting, load leveling, and cron de-congestion scheduler for serverless background workflows.",
                required_tools=["update_task_state"],
                tags=["scheduler", "cron", "cloudrun", "rate-limiting"]
            ),
            AgentSkill(
                skill_id="skill:cloud-pubsub-event-mesh",
                name="Google Cloud Pub/Sub Event Mesh",
                pillar="uas",
                version="1.0.0",
                fork_of="skills/infrastructure/cloud-communication-protocols",
                description="Event-driven messaging bridge distributing asynchronous invoice arrivals and heartbeats across Pub/Sub topics.",
                required_tools=["dispatch_swarm"],
                tags=["pubsub", "event-mesh", "messaging", "google-cloud"]
            ),

            # -------------------------------------------------------------
            # 4. PILLAR MEMORY (USMC Bank, Dynamic Context & Evidence)
            # -------------------------------------------------------------
            AgentSkill(
                skill_id="skill:memory-bank-connector",
                name="USMC Memory Bank & Context Injector",
                pillar="memory",
                version="1.2.0",
                description="Kuratierte Faktenpersistenz und semantischer GARDENER RAG Dokumentenabruf mit dynamischer Prompt-Injektion.",
                required_tools=["query_memory_bank", "store_memory_bank"],
                tags=["memory", "usmc", "rag", "gardener", "context"]
            ),
            AgentSkill(
                skill_id="skill:dynamic-context-injector",
                name="Dynamic Context Injector & Policy Hooker",
                pillar="memory",
                version="1.0.0",
                fork_of="skills/infrastructure/letter-hooker",
                description="Just-in-time contextual injection of corporate policies and memory bank facts directly into agent prompts.",
                required_tools=["query_memory_bank"],
                tags=["context", "memory-hooker", "prompt-injection", "usmc"]
            ),
            AgentSkill(
                skill_id="skill:multimodal-document-chunker",
                name="Multimodal Document Chunker & Semantic Splitter",
                pillar="memory",
                version="1.0.0",
                fork_of="skills/utilities/document-chunker",
                description="Structured semantic chunking of multi-page invoices and contractual sheets for vector indexing and Gemini RAG.",
                required_tools=["store_memory_bank"],
                tags=["chunking", "rag", "documents", "memory"]
            ),
            AgentSkill(
                skill_id="skill:chain-of-evidence-reasoner",
                name="Chain of Evidence Reasoner & Synthesizer",
                pillar="memory",
                version="1.0.0",
                fork_of="skills/utilities/structured-thinking",
                description="Formal Tree-of-Thought reasoning synthesizer producing auditable step-by-step proofs and verifiable citations.",
                required_tools=["query_memory_bank"],
                tags=["reasoning", "evidence", "tree-of-thought", "audit"]
            ),
            AgentSkill(
                skill_id="skill:controlcenter-skill-discovery",
                name="ControlCenter Skill Discovery & Matcher",
                pillar="memory",
                version="1.0.0",
                fork_of="skills/infrastructure/skill-finder",
                description="ControlCenter-compliant skill discovery, keyword matcher, and dynamic capability bundler resolving agent intent.",
                required_tools=["query_memory_bank"],
                tags=["discovery", "controlcenter", "skills", "capabilities"]
            ),

            # -------------------------------------------------------------
            # 5. ASSIST, DEV & UTILITIES (Google Ecosystem & Operations)
            # -------------------------------------------------------------
            AgentSkill(
                skill_id="skill:google-calendar-scheduler",
                name="Google Calendar Scheduler & Deadline Sentry",
                pillar="assist",
                version="1.0.0",
                fork_of="skills/assist/kalender",
                description="Integrates with Google Calendar API to manage payment deadlines, Skonto discounts, and audit schedules.",
                required_tools=["query_memory_bank", "create_task"],
                tags=["calendar", "google-api", "deadlines", "skonto"]
            ),
            AgentSkill(
                skill_id="skill:gemini-audio-transcriber",
                name="Gemini Multimodal Audio Transcriber",
                pillar="assist",
                version="1.0.0",
                fork_of="skills/assist/transkription",
                description="Processes spoken voice notes and call recordings directly using Gemini 3.5 Flash Multimodal Audio capabilities.",
                required_tools=["query_memory_bank"],
                tags=["audio", "voice", "multimodal", "gemini"]
            ),
            AgentSkill(
                skill_id="skill:google-web-reading",
                name="Google Web Reading & Multimodal DOM Digester",
                pillar="domain",
                version="1.0.0",
                fork_of="skills/web/web-reading",
                description="Autonomous web extraction, DOM tree sanitization, and multimodal visual document digestion with Gemini.",
                required_tools=["extract_invoice_multimodal", "query_memory_bank"],
                tags=["web", "dom", "multimodal", "scraping"]
            ),
            AgentSkill(
                skill_id="skill:fleet-dossier-briefing",
                name="Fleet Dossier & Executive Briefing",
                pillar="assist",
                version="1.0.0",
                fork_of="skills/assist/dossier-briefing",
                description="Synthesizes multi-source financial, operational, and compliance telemetry into concise executive briefings.",
                required_tools=["query_memory_bank", "audit_telemetry"],
                tags=["briefing", "executive", "synthesis", "assist"]
            ),
            AgentSkill(
                skill_id="skill:canva-ui-stylist",
                name="Canva UI Stylist & Enterprise Token Engine",
                pillar="dev",
                version="1.0.0",
                fork_of="skills/dev/figma",
                description="Designs ultra-crisp, Canva/Stripe-inspired enterprise user interfaces, design tokens, and light/dark themes.",
                required_tools=["execute_calculation"],
                tags=["design", "ui", "ux", "css", "canva", "styling"]
            ),
            AgentSkill(
                skill_id="skill:audit-incident-protocol",
                name="Audit Incident Protocol & Receipt Sentry",
                pillar="dev",
                version="1.0.0",
                fork_of="skills/dev/bugfix-protocol",
                description="Creates immutable, cryptographically verifiable incident receipts for agent exceptions and policy blocks.",
                required_tools=["verify_receipts"],
                tags=["audit", "incident", "receipts", "compliance"]
            ),
            AgentSkill(
                skill_id="skill:runtime-anomaly-detector",
                name="Runtime Anomaly Detector & Circuit Breaker",
                pillar="dev",
                version="1.0.0",
                fork_of="skills/dev/bugsweep",
                description="Autonomous fleet health checker and loop breaker monitoring error spikes and repeated failed step executions.",
                required_tools=["audit_telemetry"],
                tags=["health", "anomaly", "circuit-breaker", "telemetry"]
            ),
            AgentSkill(
                skill_id="skill:enterprise-plugin-engine",
                name="Enterprise Plugin Engine & MCP Host",
                pillar="dev",
                version="1.0.0",
                fork_of="skills/dev/plugin-system",
                description="Dynamic MCP and tool plugin runtime loader enabling runtime discovery and hot-reloading of third-party tools.",
                required_tools=["query_memory_bank"],
                tags=["plugins", "mcp", "modularity", "tools"]
            ),
            AgentSkill(
                skill_id="skill:gemini-bilingual-sync",
                name="Gemini Bilingual Synchronizer (DE/EN)",
                pillar="utilities",
                version="1.0.0",
                fork_of="skills/utilities/bilingual-doc-sync",
                description="Cross-lingual document synchronizer translating complex tax rules and error reports with 100% semantic fidelity.",
                required_tools=["query_memory_bank"],
                tags=["bilingual", "translation", "internationalization", "gemini"]
            )
        ]
        for s in seeds:
            self._skills[s.skill_id] = s

    def list_all(self) -> List[AgentSkill]:
        return list(self._skills.values())

    def get_skill(self, skill_id: str) -> Optional[AgentSkill]:
        return self._skills.get(skill_id)

    def find_skills(self, query: str) -> List[AgentSkill]:
        """ControlCenter-style keyword and semantic intent matcher."""
        query_terms = set(re.findall(r"\w+", query.lower()))
        if not query_terms:
            return self.list_all()

        scored = []
        for s in self._skills.values():
            searchable = f"{s.name} {s.description} {' '.join(s.tags)} {s.pillar}".lower()
            s_terms = set(re.findall(r"\w+", searchable))
            overlap = len(query_terms.intersection(s_terms))
            if overlap > 0:
                scored.append((overlap, s))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored]

    def add_skill_version(
        self,
        skill_id: str,
        new_version_number: str,
        change_summary: str,
        required_tools: List[str]
    ) -> Optional[AgentSkill]:
        skill = self.get_skill(skill_id)
        if not skill:
            return None
        
        ver_rec = SkillVersionRecord(
            version_id=f"ver-skill-{int(time.time()*1000)}",
            skill_id=skill_id,
            version_number=new_version_number,
            change_summary=change_summary,
            required_tools=required_tools
        )
        skill.versions.append(ver_rec)
        skill.version = new_version_number
        skill.required_tools = required_tools
        skill.updated_at = time.time()
        return skill

    def update_permissions(
        self,
        skill_id: str,
        visibility: str,
        execution_gate: str
    ) -> Optional[AgentSkill]:
        skill = self.get_skill(skill_id)
        if not skill:
            return None
        skill.visibility = visibility
        skill.execution_gate = execution_gate
        skill.updated_at = time.time()
        return skill


skill_registry = SkillRegistry()
