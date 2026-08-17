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
    pillar: str  # control, memory, uas, domain, dev, assist, infrastructure, production, utilities
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
            # 1. Domain: Tax & Vision
            AgentSkill(
                skill_id="skill:tax-compliance-v1",
                name="§ 14 UStG Tax Compliance Auditor",
                pillar="domain",
                version="1.4.0",
                description="Automatische Prüfung gesetzlicher Pflichtangaben, USt-IdNr und mathematischer Konsistenz nach deutschem Steuerrecht.",
                required_tools=["validate_tax_compliance"],
                tags=["tax", "compliance", "ustg", "finance", "audit"],
                visibility="organization",
                execution_gate="auto",
                versions=[
                    SkillVersionRecord(
                        version_id="ver-skill-tax-140",
                        skill_id="skill:tax-compliance-v1",
                        version_number="1.4.0",
                        change_summary="Anpassung an UStG-Novelle und § 14 Konsistenzprüfungen",
                        required_tools=["validate_tax_compliance"]
                    )
                ]
            ),
            AgentSkill(
                skill_id="skill:pdf-vision-extractor",
                name="Multimodal PDF & Document Grabber",
                pillar="domain",
                version="2.1.0",
                description="Pixelgenaue Extraktion tabellarischer und unstrukturierter Daten mit Gemini 3.5 Flash Vision.",
                required_tools=["extract_invoice_multimodal"],
                tags=["vision", "ocr", "multimodal", "gemini", "pdf"],
                visibility="organization",
                execution_gate="auto"
            ),
            AgentSkill(
                skill_id="skill:vendor-dispute-generator",
                name="Self-Healing Vendor Dispute Communicator",
                pillar="domain",
                version="1.0.2",
                description="Formelle Korrespondenz und automatische Mahn- und Klärungsschreiben bei Belegfehlern mit Zahlungsstopp-Hinweis.",
                required_tools=["draft_vendor_dispute_email", "send_external_email"],
                tags=["dispute", "vendor", "email", "healing", "communication"],
                visibility="restricted",
                execution_gate="ask_permission"
            ),
            # 2. Control & Security
            AgentSkill(
                skill_id="skill:model-armor-sentry",
                name="Zero-Trust Model Armor Guardrail",
                pillar="control",
                version="3.0.0",
                description="Inline Prompt Injection Scanner, Jailbreak-Blocker und PII-Maskierungsfilter (IBAN, API-Keys, Credentials).",
                required_tools=["inspect_prompt", "sanitize_pii"],
                tags=["security", "armor", "zero-trust", "guardrail", "defense"],
                visibility="organization",
                execution_gate="auto"
            ),
            # 3. Memory & UAS
            AgentSkill(
                skill_id="skill:memory-bank-connector",
                name="USMC Memory Bank & Context Injector",
                pillar="memory",
                version="1.2.0",
                description="Kuratierte Faktenpersistenz und semantischer GARDENER RAG Dokumentenabruf mit dynamischer Prompt-Injektion.",
                required_tools=["query_memory_bank", "store_memory_bank"],
                tags=["memory", "usmc", "rag", "gardener", "context"],
                visibility="organization",
                execution_gate="auto"
            ),
            AgentSkill(
                skill_id="skill:task-lifecycle-maintainer",
                name="Task Lifecycle & Health Maintainer",
                pillar="uas",
                version="1.1.0",
                description="Asynchrone Task-Koordination, State-Tracking, Triage-Routing und automatische Re-Triagierung.",
                required_tools=["create_task", "update_task_state"],
                tags=["taskmaster", "lifecycle", "state", "triage"],
                visibility="organization",
                execution_gate="auto"
            ),
            # 4. English Branded Fleet Forks (.SKILLS Package)
            AgentSkill(
                skill_id="skill:google-web-reading",
                name="Google Web Reading & Multimodal DOM Digester",
                pillar="web",
                version="1.0.0",
                fork_of="skills/web/web-reading",
                language="en",
                description="Autonomous web extraction, DOM tree sanitization, and multimodal visual document digestion powered by Gemini 3.5 Flash.",
                required_tools=["extract_invoice_multimodal", "query_memory_bank"],
                tags=["web", "dom", "multimodal", "scraping"]
            ),
            AgentSkill(
                skill_id="skill:fleet-dossier-briefing",
                name="Fleet Dossier & Executive Briefing",
                pillar="assist",
                version="1.0.0",
                fork_of="skills/assist/dossier-briefing",
                language="en",
                description="Synthesizes multi-source financial, operational, and compliance telemetry into concise, decision-ready executive briefings.",
                required_tools=["query_memory_bank", "audit_telemetry"],
                tags=["briefing", "executive", "synthesis", "assist"]
            ),
            AgentSkill(
                skill_id="skill:canva-ui-stylist",
                name="Canva UI Stylist & Enterprise Design Token Engine",
                pillar="dev",
                version="1.0.0",
                fork_of="skills/dev/figma",
                language="en",
                description="Designs ultra-crisp, Canva/Stripe-inspired enterprise user interfaces, design tokens, light/dark themes, and accessible component libraries.",
                required_tools=["execute_calculation"],
                tags=["design", "ui", "ux", "css", "canva", "styling"]
            ),
            AgentSkill(
                skill_id="skill:cloudrun-swarm-conductor",
                name="Google Cloud Run Multi-Agent Swarm Conductor",
                pillar="dev",
                version="1.0.0",
                fork_of="skills/dev/swarm-operations",
                language="en",
                description="Orchestrates serverless multi-agent swarms, parallel map-reduce pipelines, and consensus rounds across Google Cloud Run workers.",
                required_tools=["dispatch_swarm", "assign_task"],
                tags=["swarm", "orchestration", "cloudrun", "parallel"]
            ),
            AgentSkill(
                skill_id="skill:sentinel-persona-router",
                name="Sentinel Persona Router & Intent Dispatcher",
                pillar="infrastructure",
                version="1.0.0",
                fork_of="skills/infrastructure/semantic-persona-routing",
                language="en",
                description="Dynamic agent persona matching, tool scoping, and intent classification using the clutch routing algorithm.",
                required_tools=["query_memory_bank"],
                tags=["routing", "persona", "clutch", "infrastructure"]
            ),
            AgentSkill(
                skill_id="skill:ustg-law-compliance-checker",
                name="§ 14 UStG Tax Compliance Auditor & Legal Sentry",
                pillar="utilities",
                version="1.0.0",
                fork_of="skills/utilities/law-checker",
                language="en",
                description="Deterministic auditor for German § 14 UStG tax regulations, VAT ID format checks, and mathematical invoice consistency.",
                required_tools=["validate_tax_compliance"],
                tags=["tax", "ustg", "legal", "compliance", "utilities"]
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
