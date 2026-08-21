"""Skill Registry, Discovery & Governance Engine based on ellmos-ai/skills and ControlCenter-MCP."""

import os
import re
import time
from typing import Dict, List, Literal, Optional
# Deliberately a top-level import, not a lazy one inside the parser: when pyyaml is
# missing, the old in-function `import yaml` raised inside the parser's broad
# `except Exception`, every SKILL.md silently became None and the registry degraded to
# its 3 seed skills without a trace. A missing dependency should fail the process at
# import time, loudly.
import yaml
from pydantic import BaseModel, Field
from sentinel_fleet.core.errors import SkillNotFoundError, SkillSchemaValidationError
from sentinel_fleet.core.storage import BaseStore, get_store


LEGACY_SCOPE = "legacy-unassigned"
DEMO_ORGANIZATION = "sentinel-demo"
SYSTEM_COMPONENT_OWNER = "system:sentinel"
ComponentVisibility = Literal["private", "department", "organization", "restricted", "public"]


class SkillVersionRecord(BaseModel):
    version_id: str
    skill_id: str
    version_number: str
    change_summary: str
    required_tools: List[str]
    created_at: float = Field(default_factory=time.time)
    created_by: str = "operator"


class AgentSkill(BaseModel):
    skill_id: str
    name: str
    pillar: str  # control, memory, uas, domain, dev, assist, infrastructure, utilities, web
    version: str = "1.0.0"
    description: str
    # Markdown body of the SKILL.md behind the frontmatter. The chat console injects this
    # verbatim into the system prompt, so a skill governs the model rather than only labelling it.
    body: str = ""
    required_tools: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    schema_version: str = "component-v1"
    status: str = "active"  # active, draft, deprecated
    fork_of: Optional[str] = None
    language: str = "en"
    # Permissions & Governance
    # Legacy records have no attributable tenant and therefore default to private.
    owner_id: str = LEGACY_SCOPE
    organization_id: str = LEGACY_SCOPE
    department_id: Optional[str] = None
    visibility: ComponentVisibility = "private"
    global_public: bool = False
    execution_gate: str = "auto"  # auto | ask_permission | locked
    allowed_agents: List[str] = Field(default_factory=lambda: ["*"])
    allowed_roles: List[str] = Field(default_factory=list)
    allowed_users: List[str] = Field(default_factory=list)
    compatibility: Dict[str, bool] = Field(default_factory=lambda: {
        "google_adk": True,
        "gemini_3_5": True,
        "mcp_stdio": True,
        "cloud_run": True
    })
    versions: List[SkillVersionRecord] = Field(default_factory=list)
    updated_at: float = Field(default_factory=time.time)
    origin: str = "bundled"  # bundled | operator


class ComponentV1SkillLoader:
    """Discovers and parses Component-v1 YAML skill definitions from disk."""

    @staticmethod
    def parse_skill_file(file_path: str) -> Optional[AgentSkill]:
        """Parses a SKILL.md or YAML file containing component-v1 frontmatter."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Extract YAML frontmatter delimited by ---
            frontmatter_match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
            if not frontmatter_match:
                return None

            yaml_text = frontmatter_match.group(1)
            data = yaml.safe_load(yaml_text)
            if not isinstance(data, dict):
                return None

            raw_name = data.get("name", "")
            skill_id = f"skill:{raw_name}" if not raw_name.startswith("skill:") else raw_name
            pillar = data.get("pillar", "domain")
            description = (data.get("description") or "").strip()
            body = content[frontmatter_match.end():].strip()

            return AgentSkill(
                skill_id=skill_id,
                name=raw_name,
                pillar=pillar,
                version=str(data.get("version", "1.0.0")),
                description=description,
                body=body,
                required_tools=data.get("required_tools", []),
                tags=data.get("tags", []),
                schema_version=data.get("schema_version", "component-v1"),
                status=data.get("status", "active"),
                fork_of=data.get("fork_of"),
                language=data.get("language", "en"),
                owner_id=SYSTEM_COMPONENT_OWNER,
                organization_id=DEMO_ORGANIZATION,
                department_id=data.get("department_id"),
                visibility=data.get("visibility", "organization"),
                execution_gate=data.get("execution_gate", "auto"),
                allowed_roles=data.get("allowed_roles", []),
                allowed_users=data.get("allowed_users", []),
                compatibility=data.get("compatibility", {
                    "google_adk": True,
                    "gemini_3_5": True,
                    "mcp_stdio": True,
                    "cloud_run": True
                })
            )
        except Exception:
            return None

    @classmethod
    def load_from_directory(cls, directory_path: str) -> List[AgentSkill]:
        """Recursively scans directory for Component-v1 skills."""
        skills = []
        if not os.path.exists(directory_path):
            return skills

        for root, _, files in os.walk(directory_path):
            for file in files:
                if file == "SKILL.md" or file.endswith(".skill.yaml") or file.endswith(".skill.yml"):
                    file_path = os.path.join(root, file)
                    skill = cls.parse_skill_file(file_path)
                    if skill:
                        skills.append(skill)
        return skills


class SkillRegistry:
    def __init__(
        self,
        skills_dir: Optional[str] = None,
        store: Optional[BaseStore[AgentSkill]] = None,
    ):
        self._store = store or get_store("skills", AgentSkill)
        self._skills: Dict[str, AgentSkill] = {
            skill.skill_id: skill for skill in self._store.list_all()
        }
        # Locate the canonical skills directory. The source-tree-relative path only works for
        # editable installs and checkouts; a container built with a plain `pip install .` runs
        # this file from site-packages, where `../../../skills` points into the interpreter
        # tree and silently misses all 32 bundled skills (found live on Cloud Run: the console
        # showed the 3 fallback seeds instead). Hence the candidate chain, first hit wins:
        # explicit arg > SENTINEL_SKILLS_DIR env > source-tree-relative > <cwd>/skills (the
        # Dockerfile copies the repo to the workdir, so the bundled skills live there even
        # when the package itself was installed into site-packages).
        if skills_dir:
            self._skills_dir = skills_dir
        else:
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            candidates = [
                os.environ.get("SENTINEL_SKILLS_DIR", ""),
                os.path.join(repo_root, "skills"),
                os.path.join(os.getcwd(), "skills"),
            ]
            self._skills_dir = next(
                (c for c in candidates if c and os.path.isdir(c)), candidates[1]
            )

        self.reload_skills()

    def reload_skills(self):
        """Loads skills dynamically from the filesystem with fallback seeds."""
        discovered = ComponentV1SkillLoader.load_from_directory(self._skills_dir)
        if discovered:
            for s in discovered:
                existing = self._store.get(s.skill_id)
                if existing is None:
                    existing = self._store.put(s.skill_id, s)
                elif (
                    existing.origin == "bundled"
                    and existing.owner_id == LEGACY_SCOPE
                    and existing.organization_id == LEGACY_SCOPE
                ):
                    existing.owner_id = SYSTEM_COMPONENT_OWNER
                    existing.organization_id = DEMO_ORGANIZATION
                    existing = self._store.put(existing.skill_id, existing)
                self._skills[s.skill_id] = existing
        else:
            # Loud, not silent: a missing bundled library is a deployment defect. Durable
            # operator-authored and previously loaded records remain usable across a restart.
            import logging
            if self._skills:
                logging.getLogger(__name__).warning(
                    "No component-v1 skills found under %s - using %d durable registry records. "
                    "Set SENTINEL_SKILLS_DIR if the bundled skills/ directory lives elsewhere.",
                    self._skills_dir, len(self._skills),
                )
            else:
                logging.getLogger(__name__).warning(
                    "No component-v1 skills found under %s - falling back to %d built-in seed "
                    "skills. Set SENTINEL_SKILLS_DIR if the bundled skills/ directory lives "
                    "elsewhere.", self._skills_dir, 3,
                )
                self._seed_default_skills()

    def _seed_default_skills(self):
        # Fallback seeds if filesystem is not mounted
        fallback_seeds = [
            AgentSkill(
                skill_id="skill:tax-compliance-v1",
                name="§ 14 UStG Tax Compliance Auditor",
                pillar="domain",
                version="1.4.0",
                description="Automated check of statutory mandatory fields, VAT ID and arithmetic consistency under German tax law.",
                owner_id=SYSTEM_COMPONENT_OWNER,
                organization_id=DEMO_ORGANIZATION,
                visibility="organization",
                required_tools=["validate_tax_compliance"],
                tags=["tax", "compliance", "ustg", "finance", "audit"]
            ),
            AgentSkill(
                skill_id="skill:pdf-vision-extractor",
                name="Multimodal PDF & Document Grabber",
                pillar="domain",
                version="2.1.0",
                description="Pixel-accurate extraction of tabular and unstructured data with Gemini 3.5 Flash Vision.",
                owner_id=SYSTEM_COMPONENT_OWNER,
                organization_id=DEMO_ORGANIZATION,
                visibility="organization",
                required_tools=["extract_invoice_multimodal"],
                tags=["vision", "ocr", "multimodal", "gemini", "pdf"]
            ),
            AgentSkill(
                skill_id="skill:model-armor-sentry",
                name="Zero-Trust Model Armor Guardrail",
                pillar="control",
                version="3.0.0",
                description="Inline prompt injection scanner, jailbreak blocker and PII masking filter.",
                owner_id=SYSTEM_COMPONENT_OWNER,
                organization_id=DEMO_ORGANIZATION,
                visibility="organization",
                required_tools=["inspect_prompt", "sanitize_pii"],
                tags=["security", "armor", "zero-trust", "guardrail"]
            )
        ]
        for s in fallback_seeds:
            existing = self._store.get(s.skill_id)
            if existing is None:
                existing = self._store.put(s.skill_id, s)
            elif (
                existing.origin == "bundled"
                and existing.owner_id == LEGACY_SCOPE
                and existing.organization_id == LEGACY_SCOPE
            ):
                existing.owner_id = SYSTEM_COMPONENT_OWNER
                existing.organization_id = DEMO_ORGANIZATION
                existing = self._store.put(existing.skill_id, existing)
            self._skills[s.skill_id] = existing

    def list_all(self) -> List[AgentSkill]:
        return list(self._skills.values())

    def get_skill(self, skill_id: str) -> Optional[AgentSkill]:
        return self._skills.get(skill_id)

    @staticmethod
    def can_read(
        skill: AgentSkill,
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> bool:
        if skill.visibility == "public" and skill.global_public:
            return True
        if skill.organization_id != organization_id:
            return False
        if skill.owner_id == requested_by:
            return True
        if skill.visibility == "organization":
            return True
        if skill.visibility == "department":
            return bool(skill.department_id and skill.department_id == department_id)
        if skill.visibility == "restricted":
            if skill.department_id and skill.department_id != department_id:
                return False
            return requested_by in skill.allowed_users or bool(
                set(roles or []).intersection(skill.allowed_roles)
            )
        return False

    def list_visible(
        self,
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> List[AgentSkill]:
        return [
            skill
            for skill in self._skills.values()
            if self.can_read(skill, requested_by, organization_id, department_id, roles)
        ]

    def get_visible(
        self,
        skill_id: str,
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Optional[AgentSkill]:
        skill = self.get_skill(skill_id)
        if skill is None or not self.can_read(
            skill, requested_by, organization_id, department_id, roles
        ):
            return None
        return skill

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

    def find_visible(
        self,
        query: str,
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> List[AgentSkill]:
        visible_ids = {
            skill.skill_id
            for skill in self.list_visible(
                requested_by, organization_id, department_id, roles
            )
        }
        return [skill for skill in self.find_skills(query) if skill.skill_id in visible_ids]

    def create_skill(
        self,
        name: str,
        pillar: str,
        description: str,
        body: str = "",
        required_tools: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        visibility: ComponentVisibility = "private",
        execution_gate: str = "auto",
        owner_id: str = LEGACY_SCOPE,
        organization_id: str = LEGACY_SCOPE,
        department_id: Optional[str] = None,
        allowed_roles: Optional[List[str]] = None,
        allowed_users: Optional[List[str]] = None,
        global_public: bool = False,
    ) -> AgentSkill:
        """Register an operator-authored skill.

        Registry-only, like prompt creation: nothing is written back to the skills directory,
        so authoring a skill in the console never mutates the repository it was loaded from.
        """
        slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        if not slug:
            raise SkillSchemaValidationError("name", "A skill name must contain letters or digits")

        skill = AgentSkill(
            skill_id=f"skill:{slug}",
            name=slug,
            pillar=pillar,
            version="1.0.0",
            description=description.strip(),
            body=body.strip(),
            required_tools=required_tools or [],
            tags=tags or [],
            owner_id=owner_id,
            organization_id=organization_id,
            department_id=department_id,
            visibility=visibility,
            global_public=global_public,
            execution_gate=execution_gate,
            allowed_roles=allowed_roles or [],
            allowed_users=allowed_users or [],
            origin="operator",
        )
        self._skills[skill.skill_id] = self._store.put(skill.skill_id, skill)
        return self._skills[skill.skill_id]

    def create_skill_authorized(
        self,
        name: str,
        pillar: str,
        description: str,
        owner_id: str,
        organization_id: str,
        body: str = "",
        required_tools: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        visibility: ComponentVisibility = "private",
        execution_gate: str = "auto",
        department_id: Optional[str] = None,
        allowed_roles: Optional[List[str]] = None,
        allowed_users: Optional[List[str]] = None,
        can_publish_global: bool = False,
    ) -> AgentSkill:
        self._validate_principal_scope(owner_id, organization_id)
        self._validate_visibility(visibility, department_id, can_publish_global)
        slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        if not slug:
            raise SkillSchemaValidationError("name", "A skill name must contain letters or digits")
        if self.get_skill(f"skill:{slug}") is not None:
            raise ValueError("Component identifier is unavailable")
        return self.create_skill(
            name,
            pillar,
            description,
            body,
            required_tools,
            tags,
            visibility,
            execution_gate,
            owner_id,
            organization_id,
            department_id,
            allowed_roles,
            allowed_users,
            visibility == "public",
        )

    def add_skill_version(
        self,
        skill_id: str,
        new_version_number: str,
        change_summary: str,
        required_tools: List[str],
        created_by: str = "operator",
    ) -> AgentSkill:
        skill = self.get_skill(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)

        ver_rec = SkillVersionRecord(
            version_id=f"ver-skill-{int(time.time()*1000)}",
            skill_id=skill_id,
            version_number=new_version_number,
            change_summary=change_summary,
            required_tools=required_tools,
            created_by=created_by,
        )
        skill.versions.append(ver_rec)
        skill.version = new_version_number
        skill.required_tools = required_tools
        skill.updated_at = time.time()
        self._skills[skill_id] = self._store.put(skill_id, skill)
        return self._skills[skill_id]

    def add_skill_version_authorized(
        self,
        skill_id: str,
        new_version_number: str,
        change_summary: str,
        required_tools: List[str],
        requested_by: str,
        organization_id: str,
        can_edit_foreign: bool = False,
    ) -> AgentSkill:
        self._require_editable(skill_id, requested_by, organization_id, can_edit_foreign)
        return self.add_skill_version(
            skill_id,
            new_version_number,
            change_summary,
            required_tools,
            created_by=requested_by,
        )

    def delete_skill(self, skill_id: str) -> bool:
        """Remove a skill from the registry.

        Whether a task template or a chat session still selects it is checked by the caller, for
        the same layering reason as `PromptRegistry.delete_prompt()`. A skill loaded from disk
        comes back on the next reload - the caller says so rather than letting it reappear
        unexplained.
        """
        if skill_id not in self._skills:
            return False
        del self._skills[skill_id]
        return self._store.delete(skill_id)

    def delete_skill_authorized(
        self,
        skill_id: str,
        requested_by: str,
        organization_id: str,
        can_edit_foreign: bool = False,
    ) -> bool:
        self._require_editable(skill_id, requested_by, organization_id, can_edit_foreign)
        return self.delete_skill(skill_id)

    def update_permissions(
        self,
        skill_id: str,
        visibility: str,
        execution_gate: str,
        department_id: Optional[str] = None,
        allowed_roles: Optional[List[str]] = None,
        allowed_users: Optional[List[str]] = None,
        global_public: Optional[bool] = None,
    ) -> AgentSkill:
        skill = self.get_skill(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)

        skill.visibility = visibility
        skill.execution_gate = execution_gate
        skill.department_id = department_id
        if allowed_roles is not None:
            skill.allowed_roles = allowed_roles
        if allowed_users is not None:
            skill.allowed_users = allowed_users
        if global_public is not None:
            skill.global_public = global_public
        skill.updated_at = time.time()
        self._skills[skill_id] = self._store.put(skill_id, skill)
        return self._skills[skill_id]

    def update_permissions_authorized(
        self,
        skill_id: str,
        visibility: ComponentVisibility,
        execution_gate: str,
        requested_by: str,
        organization_id: str,
        department_id: Optional[str] = None,
        allowed_roles: Optional[List[str]] = None,
        allowed_users: Optional[List[str]] = None,
        can_edit_foreign: bool = False,
        can_publish_global: bool = False,
    ) -> AgentSkill:
        self._require_editable(skill_id, requested_by, organization_id, can_edit_foreign)
        self._validate_visibility(visibility, department_id, can_publish_global)
        return self.update_permissions(
            skill_id,
            visibility,
            execution_gate,
            department_id,
            allowed_roles,
            allowed_users,
            visibility == "public",
        )

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
        skill_id: str,
        requested_by: str,
        organization_id: str,
        can_edit_foreign: bool,
    ) -> AgentSkill:
        skill = self.get_skill(skill_id)
        if skill is None:
            raise SkillNotFoundError(skill_id)
        if skill.organization_id != organization_id:
            raise PermissionError("Skill belongs to another organization")
        if skill.owner_id != requested_by and not can_edit_foreign:
            raise PermissionError("Skill mutation requires its owner")
        return skill


skill_registry = SkillRegistry()
