"""Durable prompt registry, versioning and RBAC metadata."""

import hashlib
import time
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from sentinel_fleet.core.errors import (
    LastVersionError,
    PromptNotFoundError,
    PromptVersionNotFoundError,
)
from sentinel_fleet.core.storage import BaseStore, get_store


LEGACY_SCOPE = "legacy-unassigned"
DEMO_ORGANIZATION = "sentinel-demo"
SYSTEM_COMPONENT_OWNER = "system:sentinel"
ComponentVisibility = Literal["private", "department", "organization", "restricted", "public"]


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
    # Records written before tenant ownership existed deliberately fail closed. Canonical
    # built-ins are explicitly assigned to the demo organisation while they are seeded below.
    owner_id: str = LEGACY_SCOPE
    organization_id: str = LEGACY_SCOPE
    department_id: Optional[str] = None
    visibility: ComponentVisibility = "private"
    global_public: bool = False
    requires_approval: bool = False
    allowed_roles: List[str] = Field(default_factory=lambda: ["orchestrator", "task_solver", "operator"])
    allowed_users: List[str] = Field(default_factory=list)
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
                owner_id=SYSTEM_COMPONENT_OWNER,
                organization_id=DEMO_ORGANIZATION,
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
                owner_id=SYSTEM_COMPONENT_OWNER,
                organization_id=DEMO_ORGANIZATION,
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
                owner_id=SYSTEM_COMPONENT_OWNER,
                organization_id=DEMO_ORGANIZATION,
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
            existing = self._store.get(p.id)
            if existing is None:
                self._store.put(p.id, p)
            elif (
                existing.owner_id == LEGACY_SCOPE
                and existing.organization_id == LEGACY_SCOPE
            ):
                if self._matches_canonical_seed(existing, p):
                    existing.owner_id = SYSTEM_COMPONENT_OWNER
                    existing.organization_id = DEMO_ORGANIZATION
                    self._store.put(existing.id, existing)
                else:
                    # A legacy operator could create the same slug as a built-in prompt.
                    # Preserve that ambiguous record under a private quarantine ID, then
                    # restore the trusted seed instead of adopting attacker-controlled text.
                    digest = hashlib.sha256(existing.model_dump_json().encode("utf-8")).hexdigest()
                    quarantined = existing.model_copy(deep=True)
                    quarantined.id = f"{existing.id}:legacy-collision:{digest[:16]}"
                    quarantined.owner_id = LEGACY_SCOPE
                    quarantined.organization_id = LEGACY_SCOPE
                    quarantined.department_id = None
                    quarantined.visibility = "private"
                    quarantined.global_public = False
                    quarantined.allowed_roles = []
                    quarantined.allowed_users = []
                    for version in quarantined.versions:
                        version.prompt_id = quarantined.id
                    self._store.put(quarantined.id, quarantined)
                    self._store.put(p.id, p)

    @staticmethod
    def _matches_canonical_seed(existing: PromptItem, seed: PromptItem) -> bool:
        """Recognize an old built-in by content, never by its identifier alone."""

        fields = (
            "id",
            "title",
            "purpose",
            "category",
            "active_version",
            "current_text",
            "variables",
            "tags",
            "department_id",
            "visibility",
            "global_public",
            "requires_approval",
            "allowed_roles",
            "allowed_users",
        )
        if any(getattr(existing, field) != getattr(seed, field) for field in fields):
            return False

        version_fields = (
            "version_id",
            "prompt_id",
            "version_number",
            "title",
            "text",
            "variables",
            "tags",
            "change_summary",
            "created_by",
        )
        if len(existing.versions) != len(seed.versions):
            return False
        return all(
            all(getattr(old, field) == getattr(trusted, field) for field in version_fields)
            for old, trusted in zip(existing.versions, seed.versions)
        )

    def list_all(self) -> List[PromptItem]:
        return self._store.list_all()

    def get_prompt(self, prompt_id: str) -> Optional[PromptItem]:
        return self._store.get(prompt_id)

    @staticmethod
    def can_read(
        prompt: PromptItem,
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> bool:
        """Return whether a principal may see this component without leaking other tenants."""
        if prompt.visibility == "public" and prompt.global_public:
            return True
        if prompt.organization_id != organization_id:
            return False
        if prompt.owner_id == requested_by:
            return True
        if prompt.visibility == "organization":
            return True
        if prompt.visibility == "department":
            return bool(prompt.department_id and prompt.department_id == department_id)
        if prompt.visibility == "restricted":
            if prompt.department_id and prompt.department_id != department_id:
                return False
            return requested_by in prompt.allowed_users or bool(
                set(roles or []).intersection(prompt.allowed_roles)
            )
        return False

    def list_visible(
        self,
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> List[PromptItem]:
        return [
            prompt
            for prompt in self._store.list_all()
            if self.can_read(prompt, requested_by, organization_id, department_id, roles)
        ]

    def get_visible(
        self,
        prompt_id: str,
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Optional[PromptItem]:
        prompt = self.get_prompt(prompt_id)
        if prompt is None or not self.can_read(
            prompt, requested_by, organization_id, department_id, roles
        ):
            return None
        return prompt

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

    def get_version_visible(
        self,
        prompt_id: str,
        version_number: str,
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Optional[PromptVersionRecord]:
        prompt = self.get_visible(
            prompt_id, requested_by, organization_id, department_id, roles
        )
        if prompt is None:
            return None
        return next(
            (version for version in prompt.versions if version.version_number == version_number),
            None,
        )

    def create_prompt(
        self,
        title: str,
        purpose: str,
        category: str,
        text: str,
        variables: List[str],
        tags: List[str],
        visibility: ComponentVisibility = "private",
        requires_approval: bool = False,
        owner_id: str = LEGACY_SCOPE,
        organization_id: str = LEGACY_SCOPE,
        department_id: Optional[str] = None,
        allowed_roles: Optional[List[str]] = None,
        allowed_users: Optional[List[str]] = None,
        global_public: bool = False,
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
            change_summary="Initial created via Control Center",
            created_by=owner_id,
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
            owner_id=owner_id,
            organization_id=organization_id,
            department_id=department_id,
            visibility=visibility,
            global_public=global_public,
            requires_approval=requires_approval,
            allowed_roles=allowed_roles or ["orchestrator", "task_solver", "operator"],
            allowed_users=allowed_users or [],
            versions=[version_rec]
        )
        return self._store.put(prompt_id, prompt)

    def create_prompt_authorized(
        self,
        title: str,
        purpose: str,
        category: str,
        text: str,
        variables: List[str],
        tags: List[str],
        owner_id: str,
        organization_id: str,
        visibility: ComponentVisibility = "private",
        requires_approval: bool = False,
        department_id: Optional[str] = None,
        allowed_roles: Optional[List[str]] = None,
        allowed_users: Optional[List[str]] = None,
        can_publish_global: bool = False,
    ) -> PromptItem:
        self._validate_principal_scope(owner_id, organization_id)
        self._validate_visibility(visibility, department_id, can_publish_global)
        prompt_id = f"prompt:{title.lower().replace(' ', '-')}"
        if self.get_prompt(prompt_id) is not None:
            raise ValueError("Component identifier is unavailable")
        return self.create_prompt(
            title,
            purpose,
            category,
            text,
            variables,
            tags,
            visibility,
            requires_approval,
            owner_id,
            organization_id,
            department_id,
            allowed_roles,
            allowed_users,
            visibility == "public",
        )

    def add_prompt_version(
        self,
        prompt_id: str,
        new_version_number: str,
        new_text: str,
        change_summary: str,
        title_override: Optional[str] = None,
        created_by: str = "operator",
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
            change_summary=change_summary,
            created_by=created_by,
        )
        prompt.versions.append(version_rec)
        prompt.active_version = new_version_number
        prompt.current_text = new_text
        prompt.updated_at = time.time()
        return self._store.put(prompt_id, prompt)

    def add_prompt_version_authorized(
        self,
        prompt_id: str,
        new_version_number: str,
        new_text: str,
        change_summary: str,
        requested_by: str,
        organization_id: str,
        title_override: Optional[str] = None,
        can_edit_foreign: bool = False,
    ) -> PromptItem:
        prompt = self._require_editable(
            prompt_id, requested_by, organization_id, can_edit_foreign
        )
        updated = self.add_prompt_version(
            prompt.id,
            new_version_number,
            new_text,
            change_summary,
            title_override,
            created_by=requested_by,
        )
        assert updated is not None
        return updated

    def delete_prompt(self, prompt_id: str) -> bool:
        """Remove a prompt and all of its versions.

        Whether anything still references it is decided by the caller: the task template registry
        lives a layer above this module and importing it here would close a cycle, the same
        reason `delete_template()` leaves its binding check to its own caller.
        """
        return self._store.delete(prompt_id)

    def delete_prompt_authorized(
        self,
        prompt_id: str,
        requested_by: str,
        organization_id: str,
        can_edit_foreign: bool = False,
    ) -> bool:
        self._require_editable(prompt_id, requested_by, organization_id, can_edit_foreign)
        return self.delete_prompt(prompt_id)

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

    def delete_version_authorized(
        self,
        prompt_id: str,
        version_number: str,
        requested_by: str,
        organization_id: str,
        can_edit_foreign: bool = False,
    ) -> PromptItem:
        self._require_editable(prompt_id, requested_by, organization_id, can_edit_foreign)
        return self.delete_version(prompt_id, version_number)

    def update_permissions(
        self,
        prompt_id: str,
        visibility: str,
        requires_approval: bool,
        allowed_roles: List[str],
        department_id: Optional[str] = None,
        allowed_users: Optional[List[str]] = None,
        global_public: Optional[bool] = None,
    ) -> Optional[PromptItem]:
        prompt = self.get_prompt(prompt_id)
        if not prompt:
            return None
        prompt.visibility = visibility
        prompt.requires_approval = requires_approval
        prompt.allowed_roles = allowed_roles
        prompt.department_id = department_id
        if allowed_users is not None:
            prompt.allowed_users = allowed_users
        if global_public is not None:
            prompt.global_public = global_public
        prompt.updated_at = time.time()
        return self._store.put(prompt_id, prompt)

    def update_permissions_authorized(
        self,
        prompt_id: str,
        visibility: ComponentVisibility,
        requires_approval: bool,
        allowed_roles: List[str],
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        allowed_users: Optional[List[str]] = None,
        can_edit_foreign: bool = False,
        can_publish_global: bool = False,
    ) -> PromptItem:
        self._require_editable(prompt_id, requested_by, organization_id, can_edit_foreign)
        self._validate_visibility(visibility, department_id, can_publish_global)
        updated = self.update_permissions(
            prompt_id,
            visibility,
            requires_approval,
            allowed_roles,
            department_id,
            allowed_users,
            visibility == "public",
        )
        assert updated is not None
        return updated

    @staticmethod
    def _validate_principal_scope(owner_id: str, organization_id: str) -> None:
        if owner_id in {"", LEGACY_SCOPE} or organization_id in {"", LEGACY_SCOPE}:
            raise ValueError("Verified owner and organization are required")

    @staticmethod
    def _validate_visibility(
        visibility: ComponentVisibility,
        department_id: Optional[str],
        can_publish_global: bool,
    ) -> None:
        if visibility not in {"private", "department", "organization", "restricted", "public"}:
            raise ValueError("Unsupported component visibility")
        if visibility == "department" and not department_id:
            raise ValueError("Department visibility requires a department")
        if visibility == "public" and not can_publish_global:
            raise PermissionError("Global component publication is not permitted")

    def _require_editable(
        self,
        prompt_id: str,
        requested_by: str,
        organization_id: str,
        can_edit_foreign: bool,
    ) -> PromptItem:
        prompt = self.get_prompt(prompt_id)
        if prompt is None:
            raise PromptNotFoundError(prompt_id)
        if prompt.organization_id != organization_id:
            raise PermissionError("Prompt belongs to another organization")
        if prompt.owner_id != requested_by and not can_edit_foreign:
            raise PermissionError("Prompt mutation requires its owner")
        return prompt


prompt_registry = PromptRegistry()
