"""Skill Registry & Discovery Engine based on ellmos-ai/skills and ControlCenter-MCP."""

import re
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class AgentSkill(BaseModel):
    skill_id: str
    name: str
    pillar: str  # control, memory, uas, domain
    version: str = "1.0.0"
    description: str
    required_tools: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    schema_version: str = "component-v1"
    status: str = "active"  # active, draft, deprecated
    compatibility: Dict[str, bool] = Field(default_factory=lambda: {
        "google_adk": True,
        "gemini_3_5": True,
        "mcp_stdio": True,
        "cloud_run": True
    })


class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, AgentSkill] = {}
        self._seed_default_skills()

    def _seed_default_skills(self):
        seeds = [
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
                skill_id="skill:vendor-dispute-generator",
                name="Self-Healing Vendor Dispute Communicator",
                pillar="domain",
                version="1.0.2",
                description="Formelle Korrespondenz und automatische Mahn- und Klärungsschreiben bei Belegfehlern mit Zahlungsstopp-Hinweis.",
                required_tools=["draft_vendor_dispute_email", "send_external_email"],
                tags=["dispute", "vendor", "email", "healing", "communication"]
            ),
            AgentSkill(
                skill_id="skill:model-armor-sentry",
                name="Zero-Trust Model Armor Guardrail",
                pillar="control",
                version="3.0.0",
                description="Inline Prompt Injection Scanner, Jailbreak-Blocker und PII-Maskierungsfilter (IBAN, API-Keys, Credentials).",
                required_tools=["inspect_prompt", "sanitize_pii"],
                tags=["security", "armor", "zero-trust", "guardrail", "defense"]
            ),
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
                skill_id="skill:task-lifecycle-maintainer",
                name="Task Lifecycle & Health Maintainer",
                pillar="uas",
                version="1.1.0",
                description="Asynchrone Task-Koordination, State-Tracking, Triage-Routing und automatische Re-Triagierung.",
                required_tools=["create_task", "update_task_state"],
                tags=["taskmaster", "lifecycle", "state", "triage"]
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


skill_registry = SkillRegistry()
