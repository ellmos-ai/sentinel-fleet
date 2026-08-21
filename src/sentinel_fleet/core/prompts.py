"""Durable prompt registry, versioning and RBAC metadata."""

import time
from typing import List, Optional
from pydantic import BaseModel, Field

from sentinel_fleet.core.errors import (
    LastVersionError,
    PromptNotFoundError,
    PromptVersionNotFoundError,
)
from sentinel_fleet.core.storage import BaseStore, get_store


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
    def __init__(self, store: Optional[BaseStore[PromptItem]] = None):
        self._store = store or get_store("prompts", PromptItem)
        self._seed_canonical_library()

    def _seed_canonical_library(self):
        seeds = [
            PromptItem(
                id="prompt:invoice-vision-multimodal",
                title="Multimodal § 14 UStG Extraction Prompt",
                purpose="Extracts invoice data and statutory mandatory fields from documents.",
                category="finance",
                active_version="1.2.0",
                current_text="Extract every statutory field required by § 14 UStG from the document: {{filename}}. Pay attention to the VAT ID, the delivery date and the tax rate breakdown.",
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
                        text="Extract data from invoice {{filename}}.",
                        change_summary="Baseline extraction without § 14 UStG focus"
                    ),
                    PromptVersionRecord(
                        version_id="ver-inv-120",
                        prompt_id="prompt:invoice-vision-multimodal",
                        version_number="1.2.0",
                        title="§ 14 UStG Compliance Prompt",
                        text="Extract every statutory field required by § 14 UStG from the document: {{filename}}. Pay attention to the VAT ID, the delivery date and the tax rate breakdown.",
                        change_summary="Added mandatory field validation and net/gross consistency"
                    )
                ]
            ),
            PromptItem(
                id="prompt:vendor-dispute-resolution",
                title="Vendor Dispute Legal Correction Notice",
                purpose="Formal correspondence template for documents that fail the compliance audit.",
                category="compliance",
                active_version="2.0.1",
                current_text="Draft a formal, legally sound correction request to {{vendor_name}} regarding invoice {{invoice_number}}. Justify the payment hold with the following defects: {{violations}}.",
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
                        title="Formal correction request under § 14 UStG",
                        text="Draft a formal, legally sound correction request to {{vendor_name}} regarding invoice {{invoice_number}}. Justify the payment hold with the following defects: {{violations}}.",
                        change_summary="Added payment hold notice and 14-day deadline"
                    )
                ]
            ),
            PromptItem(
                id="prompt:deep-task-solver",
                title="Deep Task Solver & Evidence Synthesizer",
                purpose="Step-by-step task solving with evidence checks and memory injection.",
                category="orchestration",
                active_version="1.0.0",
                current_text="Analyse the task '{{task_title}}' in the light of the memory context {{memory_context}}. Work through the solution step by step with verifiable evidence.",
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
                        text="Analyse the task '{{task_title}}' in the light of the memory context {{memory_context}}. Work through the solution step by step with verifiable evidence.",
                        change_summary="Initial version"
                    )
                ]
            )
        ]
        for p in seeds:
            if self._store.get(p.id) is None:
                self._store.put(p.id, p)

    def list_all(self) -> List[PromptItem]:
        return self._store.list_all()

    def get_prompt(self, prompt_id: str) -> Optional[PromptItem]:
        return self._store.get(prompt_id)

    def get_version(self, prompt_id: str, version_number: str) -> Optional[PromptVersionRecord]:
        """Resolve one specific version of a prompt.

        The chat console pins the version an operator picked, so a later version bump cannot
        silently change which instructions a recorded conversation actually ran on.
        """
        prompt = self.get_prompt(prompt_id)
        if not prompt:
            return None
        for version in prompt.versions:
            if version.version_number == version_number:
                return version
        return None

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
        return self._store.put(prompt_id, prompt)

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
        return self._store.put(prompt_id, prompt)

    def delete_prompt(self, prompt_id: str) -> bool:
        """Remove a prompt and all of its versions.

        Whether anything still references it is decided by the caller: the task template registry
        lives a layer above this module and importing it here would close a cycle, the same
        reason `delete_template()` leaves its binding check to its own caller.
        """
        return self._store.delete(prompt_id)

    def delete_version(self, prompt_id: str, version_number: str) -> PromptItem:
        """Remove one version. The last remaining one cannot go: a prompt without a version is a
        name with no text behind it."""
        prompt = self.get_prompt(prompt_id)
        if not prompt:
            raise PromptNotFoundError(prompt_id)
        if not any(v.version_number == version_number for v in prompt.versions):
            raise PromptVersionNotFoundError(prompt_id, version_number)
        if len(prompt.versions) <= 1:
            raise LastVersionError(prompt_id)

        prompt.versions = [v for v in prompt.versions if v.version_number != version_number]
        if prompt.active_version == version_number:
            # The newest surviving version takes over; leaving `active_version` pointing at a
            # deleted record would make every later read resolve to nothing.
            newest = prompt.versions[-1]
            prompt.active_version = newest.version_number
            prompt.current_text = newest.text
        prompt.updated_at = time.time()
        return self._store.put(prompt_id, prompt)

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
        return self._store.put(prompt_id, prompt)


prompt_registry = PromptRegistry()
