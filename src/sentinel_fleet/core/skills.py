"""Skill Registry, Discovery & Governance Engine based on ellmos-ai/skills and ControlCenter-MCP."""

import os
import re
import time
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from sentinel_fleet.core.errors import SkillNotFoundError, SkillSchemaValidationError


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
            import yaml
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
                visibility=data.get("visibility", "organization"),
                execution_gate=data.get("execution_gate", "auto"),
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
    def __init__(self, skills_dir: Optional[str] = None):
        self._skills: Dict[str, AgentSkill] = {}
        # Locate canonical skills directory
        if skills_dir:
            self._skills_dir = skills_dir
        else:
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            self._skills_dir = os.path.join(repo_root, "skills")

        self.reload_skills()

    def reload_skills(self):
        """Loads skills dynamically from the filesystem with fallback seeds."""
        discovered = ComponentV1SkillLoader.load_from_directory(self._skills_dir)
        if discovered:
            for s in discovered:
                self._skills[s.skill_id] = s
        else:
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
                required_tools=["validate_tax_compliance"],
                tags=["tax", "compliance", "ustg", "finance", "audit"]
            ),
            AgentSkill(
                skill_id="skill:pdf-vision-extractor",
                name="Multimodal PDF & Document Grabber",
                pillar="domain",
                version="2.1.0",
                description="Pixel-accurate extraction of tabular and unstructured data with Gemini 3.5 Flash Vision.",
                required_tools=["extract_invoice_multimodal"],
                tags=["vision", "ocr", "multimodal", "gemini", "pdf"]
            ),
            AgentSkill(
                skill_id="skill:model-armor-sentry",
                name="Zero-Trust Model Armor Guardrail",
                pillar="control",
                version="3.0.0",
                description="Inline prompt injection scanner, jailbreak blocker and PII masking filter.",
                required_tools=["inspect_prompt", "sanitize_pii"],
                tags=["security", "armor", "zero-trust", "guardrail"]
            )
        ]
        for s in fallback_seeds:
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

    def create_skill(
        self,
        name: str,
        pillar: str,
        description: str,
        body: str = "",
        required_tools: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        visibility: str = "organization",
        execution_gate: str = "auto"
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
            visibility=visibility,
            execution_gate=execution_gate
        )
        self._skills[skill.skill_id] = skill
        return skill

    def add_skill_version(
        self,
        skill_id: str,
        new_version_number: str,
        change_summary: str,
        required_tools: List[str]
    ) -> AgentSkill:
        skill = self.get_skill(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)

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
    ) -> AgentSkill:
        skill = self.get_skill(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)

        skill.visibility = visibility
        skill.execution_gate = execution_gate
        skill.updated_at = time.time()
        return skill


skill_registry = SkillRegistry()
