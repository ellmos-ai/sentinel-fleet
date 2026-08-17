"""Prompt Registry & Versioning Engine based on profiprompt-library-v1 and PromptBoard."""

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

    def create_prompt(self, title: str, purpose: str, category: str, text: str, variables: List[str], tags: List[str]) -> PromptItem:
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
            versions=[version_rec]
        )
        self._prompts[prompt_id] = prompt
        return prompt


prompt_registry = PromptRegistry()
