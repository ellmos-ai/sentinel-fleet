"""Prompt Registry, Versioning & RBAC Permissions Engine based on profiprompt-library-v1."""

import time
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PromptVersionRecord(BaseModel):
    version_id: str
    prompt_id: str
    version_number: str  # SemVer, e.g. "1.0.0", "1.1.0"
    title: str
    text: str
    variables: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    change_summary: str = "Initial release"
    created_at: float = Field(default_factory=time.time)
    created_by: str = "operator"


class PromptItem(BaseModel):
    id: str
    title: str
    purpose: str
    category: str
    active_version: str = "1.0.0"
    current_text: str
    variables: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    versions: List[PromptVersionRecord] = Field(default_factory=list)
    # Permissions & Sharing
    visibility: str = "organization"  # public | organization | restricted
    requires_approval: bool = False
    allowed_roles: List[str] = Field(default_factory=lambda: ["orchestrator", "task_solver", "operator"])
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class PromptRegistry:
    def __init__(self):
        self._prompts: Dict[str, PromptItem] = {}
        self._seed_canonical_library()

    def _seed_canonical_library(self):
        seeds = [
            PromptItem(
                id="prompt:invoice-vision-multimodal",
                title="Multimodal § 14 UStG Extraction Prompt",
                purpose="Extrahiert Rechnungsdaten und Pflichtfelder pixelgenau aus Dokumenten.",
                category="finance",
                active_version="1.2.0",
                current_text="Extrahiere alle steuerlichen Pflichtangaben gemäß § 14 UStG aus dem Dokument: {{filename}}. Achte auf Steuernummer, Leistungsdatum und Steuersatz-Aufschlüsselung.",
                variables=["filename"],
                tags=["ustg", "vision", "gemini-3.5", "invoice"],
                visibility="organization",
                requires_approval=False,
                allowed_roles=["finance_taskmaster", "compliance_auditor"],
                versions=[
                    PromptVersionRecord(
                        version_id="ver-inv-100",
                        prompt_id="prompt:invoice-vision-multimodal",
                        version_number="1.0.0",
                        title="Basic OCR Prompt",
                        text="Extrahiere Daten aus Rechnung {{filename}}.",
                        change_summary="Basis-Extraktion ohne UStG-Fokus"
                    ),
                    PromptVersionRecord(
                        version_id="ver-inv-120",
                        prompt_id="prompt:invoice-vision-multimodal",
                        version_number="1.2.0",
                        title="§ 14 UStG Compliance Prompt",
                        text="Extrahiere alle steuerlichen Pflichtangaben gemäß § 14 UStG aus dem Dokument: {{filename}}. Achte auf Steuernummer, Leistungsdatum und Steuersatz-Aufschlüsselung.",
                        change_summary="Hinzunahme von Pflichtfeld-Validierung und Netto/Brutto Konsistenz"
                    )
                ]
            ),
            PromptItem(
                id="prompt:vendor-dispute-resolution",
                title="Vendor Dispute Legal Correction Notice",
                purpose="Formelle Mahn- und Korrespondenzvorlage bei Belegabweichungen.",
                category="compliance",
                active_version="2.0.1",
                current_text="Verfasse ein formelles, rechtssicheres Korrekturschreiben an {{vendor_name}} bezüglich Rechnung {{invoice_number}}. Begründe die Zahlungsunterbrechung mit folgenden Mängeln: {{violations}}.",
                variables=["vendor_name", "invoice_number", "violations"],
                tags=["compliance", "dispute", "vendor", "healing"],
                visibility="restricted",
                requires_approval=True,
                allowed_roles=["vendor_communicator", "operator"],
                versions=[
                    PromptVersionRecord(
                        version_id="ver-disp-201",
                        prompt_id="prompt:vendor-dispute-resolution",
                        version_number="2.0.1",
                        title="Formelle UStG-Korrekturanforderung",
                        text="Verfasse ein formelles, rechtssicheres Korrekturschreiben an {{vendor_name}} bezüglich Rechnung {{invoice_number}}. Begründe die Zahlungsunterbrechung mit folgenden Mängeln: {{violations}}.",
                        change_summary="Zahlungsstopp-Hinweis und 14-Tage-Frist ergänzt"
                    )
                ]
            ),
            PromptItem(
                id="prompt:deep-task-solver",
                title="Deep Task Solver & Evidence Synthesizer",
                purpose="Schrittweise Aufgabenlösung mit Evidenzprüfung und Memory-Injektion.",
                category="orchestration",
                active_version="1.0.0",
                current_text="Analysiere die Aufgabenstellung '{{task_title}}' unter Berücksichtigung von Gedächtniskontext {{memory_context}}. Führe die Lösung schrittweise mit überprüfbaren Belegen aus.",
                variables=["task_title", "memory_context"],
                tags=["taskmaster", "evidence", "reasoning"],
                visibility="organization",
                requires_approval=False,
                allowed_roles=["orchestrator", "task_solver"],
                versions=[
                    PromptVersionRecord(
                        version_id="ver-solve-100",
                        prompt_id="prompt:deep-task-solver",
                        version_number="1.0.0",
                        title="Initial Solver Template",
                        text="Analysiere die Aufgabenstellung '{{task_title}}' unter Berücksichtigung von Gedächtniskontext {{memory_context}}. Führe die Lösung schrittweise mit überprüfbaren Belegen aus.",
                        change_summary="Initiale Version"
                    )
                ]
            )
        ]
        for p in seeds:
            self._prompts[p.id] = p

    def list_all(self) -> List[PromptItem]:
        return list(self._prompts.values())

    def get_prompt(self, prompt_id: str) -> Optional[PromptItem]:
        return self._prompts.get(prompt_id)

    def create_prompt(
        self,
        title: str,
        purpose: str,
        category: str,
        text: str,
        variables: List[str],
        tags: List[str],
        visibility: str = "organization",
        requires_approval: bool = False
    ) -> PromptItem:
        prompt_id = f"prompt:{title.lower().replace(' ', '-')}"
        version_rec = PromptVersionRecord(
            version_id=f"ver-{int(time.time()*1000)}",
            prompt_id=prompt_id,
            version_number="1.0.0",
            title=title,
            text=text,
            variables=variables,
            tags=tags,
            change_summary="Initial created via Control Center"
        )
        prompt = PromptItem(
            id=prompt_id,
            title=title,
            purpose=purpose,
            category=category,
            active_version="1.0.0",
            current_text=text,
            variables=variables,
            tags=tags,
            visibility=visibility,
            requires_approval=requires_approval,
            versions=[version_rec]
        )
        self._prompts[prompt_id] = prompt
        return prompt

    def add_prompt_version(
        self,
        prompt_id: str,
        new_version_number: str,
        new_text: str,
        change_summary: str,
        title_override: Optional[str] = None
    ) -> Optional[PromptItem]:
        prompt = self.get_prompt(prompt_id)
        if not prompt:
            return None
        
        version_rec = PromptVersionRecord(
            version_id=f"ver-{int(time.time()*1000)}",
            prompt_id=prompt_id,
            version_number=new_version_number,
            title=title_override or prompt.title,
            text=new_text,
            variables=prompt.variables,
            tags=prompt.tags,
            change_summary=change_summary
        )
        prompt.versions.append(version_rec)
        prompt.active_version = new_version_number
        prompt.current_text = new_text
        prompt.updated_at = time.time()
        return prompt

    def update_permissions(
        self,
        prompt_id: str,
        visibility: str,
        requires_approval: bool,
        allowed_roles: List[str]
    ) -> Optional[PromptItem]:
        prompt = self.get_prompt(prompt_id)
        if not prompt:
            return None
        prompt.visibility = visibility
        prompt.requires_approval = requires_approval
        prompt.allowed_roles = allowed_roles
        prompt.updated_at = time.time()
        return prompt


prompt_registry = PromptRegistry()
