"""Prompt Registry & Template Management based on ProfiPrompt."""

import time
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PromptTemplate(BaseModel):
    prompt_id: str
    name: str
    category: str
    version: str = "1.0.0"
    template_text: str
    variables: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)


class PromptRegistry:
    def __init__(self):
        self._prompts: Dict[str, PromptTemplate] = {}
        self._seed_default_prompts()

    def _seed_default_prompts(self):
        seeds = [
            PromptTemplate(
                prompt_id="prompt:invoice-vision",
                name="Multimodal Invoice Extraction Prompt",
                category="finance",
                version="1.2.0",
                template_text="Extrahiere alle steuerlichen Pflichtangaben gemäß § 14 UStG aus dem Dokument: {{filename}}. Achte auf Steuernummer, Leistungsdatum und Aufschlüsselung der Steuersätze.",
                variables=["filename"]
            ),
            PromptTemplate(
                prompt_id="prompt:vendor-dispute",
                name="Vendor Dispute Formal Notice",
                category="compliance",
                version="2.0.1",
                template_text="Verfasse ein formelles, höfliches Korrekturschreiben an {{vendor_name}} bezüglich Rechnung {{invoice_number}}. Begründe die Ablehnung mit folgenden Mängeln: {{violations}}.",
                variables=["vendor_name", "invoice_number", "violations"]
            ),
            PromptTemplate(
                prompt_id="prompt:task-solver-deep",
                name="Deep Task Solver & Evidence Synthesizer",
                category="orchestration",
                version="1.0.0",
                template_text="Analysiere die Aufgabenstellung '{{task_title}}' unter Berücksichtigung von Gedächtniskontext {{memory_context}}. Führe die Lösung schrittweise mit Belegen aus.",
                variables=["task_title", "memory_context"]
            )
        ]
        for p in seeds:
            self._prompts[p.prompt_id] = p

    def list_all(self) -> List[PromptTemplate]:
        return list(self._prompts.values())

    def get_prompt(self, prompt_id: str) -> Optional[PromptTemplate]:
        return self._prompts.get(prompt_id)

    def create_prompt(self, name: str, category: str, template_text: str, variables: List[str]) -> PromptTemplate:
        prompt_id = f"prompt:{name.lower().replace(' ', '-')}"
        prompt = PromptTemplate(
            prompt_id=prompt_id,
            name=name,
            category=category,
            template_text=template_text,
            variables=variables
        )
        self._prompts[prompt_id] = prompt
        return prompt


prompt_registry = PromptRegistry()
