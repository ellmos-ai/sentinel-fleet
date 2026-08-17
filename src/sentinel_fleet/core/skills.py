"""Skill Registry & Discovery based on ellmos-ai/skills catalog."""

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
                description="Automatische Prüfung gesetzlicher Pflichtangaben, USt-IdNr und mathematischer Konsistenz.",
                required_tools=["validate_tax_compliance"],
                tags=["tax", "compliance", "ustg", "finance"]
            ),
            AgentSkill(
                skill_id="skill:pdf-vision-extractor",
                name="Multimodal PDF & Document Grabber",
                pillar="domain",
                version="2.1.0",
                description="Pixelgenaue Extraktion tabellarischer und unstrukturierter Daten mit Gemini 3.5 Flash.",
                required_tools=["extract_invoice_multimodal"],
                tags=["vision", "ocr", "multimodal", "gemini"]
            ),
            AgentSkill(
                skill_id="skill:vendor-dispute-generator",
                name="Self-Healing Vendor Dispute Communicator",
                pillar="domain",
                version="1.0.2",
                description="Formelle Korrespondenz und automatische Mahn- und Klärungsschreiben bei Belegfehlern.",
                required_tools=["draft_vendor_dispute_email", "send_external_email"],
                tags=["dispute", "vendor", "email", "healing"]
            ),
            AgentSkill(
                skill_id="skill:model-armor-sentry",
                name="Zero-Trust Model Armor Guardrail",
                pillar="control",
                version="3.0.0",
                description="Inline Prompt Injection Scanner, Jailbreak-Blocker und PII-Maskierungsfilter.",
                required_tools=["inspect_prompt", "sanitize_pii"],
                tags=["security", "armor", "zero-trust", "guardrail"]
            ),
            AgentSkill(
                skill_id="skill:memory-bank-connector",
                name="USMC Memory Bank & Context Injector",
                pillar="memory",
                version="1.2.0",
                description="Kuratierte Faktenpersistenz und semantischer GARDENER RAG Dokumentenabruf.",
                required_tools=["query_memory_bank", "store_memory_bank"],
                tags=["memory", "usmc", "rag", "gardener"]
            ),
            AgentSkill(
                skill_id="skill:task-lifecycle-maintainer",
                name="Task Lifecycle & Health Maintainer",
                pillar="uas",
                version="1.1.0",
                description="Asynchrone Task-Koordination, State-Tracking und automatische Re-Triagierung.",
                required_tools=["create_task", "update_task_state"],
                tags=["taskmaster", "lifecycle", "state"]
            )
        ]
        for s in seeds:
            self._skills[s.skill_id] = s

    def list_all(self) -> List[AgentSkill]:
        return list(self._skills.values())

    def get_skill(self, skill_id: str) -> Optional[AgentSkill]:
        return self._skills.get(skill_id)


skill_registry = SkillRegistry()
