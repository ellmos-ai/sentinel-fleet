"""TaskTemplate registry: the "everything is a task" foundation.

A TaskTemplate describes *what* should happen, never *when*. Attaching a RoutineBinding or a
ScheduleBinding (see `routines.py`) makes it recurring or dated; removing both leaves a bare
template again. A template never migrates between object types for this - see the "Tasks &
Routines" concept doc, section A.1/A.3, and the Routinika precedent it is built on (an
`item_type` derived from two independent flags, never stored).

Same storage pattern as `core/prompts.py` / `core/skills.py` / `uas/task_master.py`: a Pydantic
model plus a thin registry over `get_store()`.
"""

import time
import uuid
from typing import Any, List, Optional
from pydantic import BaseModel, Field, computed_field, field_validator
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.errors import TemplateNotFoundError, TemplatePermissionError

# MVP capacity for `TaskTemplate.steps` - a single-step task is the special case of a chain,
# not a different shape (concept doc, section E.1/E.4). Multi-step chains are Phase 2; this is
# the schema-level guard that keeps Phase 1 from silently accepting a shape it cannot execute.
MAX_STEPS_IN_MVP = 1


class Step(BaseModel):
    """One execution node of a TaskTemplate. Embedded on the template (like
    `PromptVersionRecord` on `PromptItem`, `prompts.py:8-18`), not a separate `get_store()`
    entity. Field names deliberately match TaskTemplate's own former flat fields
    (`assigned_agent`, `custom_prompt_text`, ...), because those flat fields are now computed
    properties reading through to `steps[0]` below - same name on both sides keeps the mapping
    a straight passthrough instead of a translation table.
    """
    step_id: str
    position: int = 0                        # ordering, once there is more than one step
    assigned_agent: str = "agent:task-solver"
    skill_ids: List[str] = Field(default_factory=list)
    prompt_source: str = "custom"            # "library" | "custom"
    prompt_id: Optional[str] = None
    prompt_version: Optional[str] = None
    custom_prompt_text: Optional[str] = None
    # "previous_output" | "template_input" | "artifact:<step_id>" once Phase 2 chains exist;
    # None here because a single step has no predecessor to read from.
    input_spec: Optional[str] = None
    # Required by the concept for a real chain (a Phase-2 runner enforces every step
    # depositing its output at a fixed handoff point) but left optional here: Phase 1 has
    # nothing that reads it yet, and the single default step is never chained into anything.
    output_artifact_id: Optional[str] = None
    parallel_group: Optional[str] = None
    execution_pattern: str = "single"        # "single" | "swarm:<id>" | "operator" | "race"
    swarm_pattern: Optional[str] = None
    race_models: List[str] = Field(default_factory=list)


class LoopConfig(BaseModel):
    """Only set when a chain is a circle (concept doc, section E.1). Always None in Phase 1."""
    max_rounds: Optional[int] = None
    max_hours: Optional[float] = None


def _default_steps() -> List[Step]:
    return [Step(step_id="step-1", position=0)]


class TaskTemplate(BaseModel):
    template_id: str
    name: str
    owner: str = "operator"
    visibility: str = "own"                # own | organization | restricted
    requires_approval: bool = False        # routes the run through ticket_master (see routines.py)
    allowed_roles: List[str] = Field(default_factory=list)
    removed_by: List[str] = Field(default_factory=list)   # per-viewer hide list for shared templates
    on_success: Optional[str] = None       # "notify" | "create_ticket" | another template_id
    on_failure: Optional[str] = None
    group: Optional[str] = None            # at most one group/tag per template
    fork_of: Optional[str] = None
    # Chain foundation (concept doc, section E.1/E.4): a single-step task is the special case
    # of Steps, not a different shape that would need migrating later. Phase 1 builds and
    # shows only this single-step case - no step editor, no chain runner, no parallel_group
    # or loop in the UI - but the field exists from day one, and IS the storage: what used to
    # be this model's own prompt_source/skill_ids/assigned_agent fields are now computed
    # properties reading through to steps[0] below, not a second, independently stored copy.
    steps: List[Step] = Field(default_factory=_default_steps)
    loop: Optional[LoopConfig] = None      # only set once a chain is a circle - always None here
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @field_validator("steps")
    @classmethod
    def _mvp_supports_exactly_one_step(cls, value: List[Step]) -> List[Step]:
        if len(value) != MAX_STEPS_IN_MVP:
            raise ValueError(
                f"This deployment (Phase 1 MVP) supports exactly {MAX_STEPS_IN_MVP} step per "
                f"task template - multi-step chains are not implemented yet (concept doc, "
                f"Phase 2 / section E.4). Got {len(value)} steps."
            )
        return value

    # -- Backward-compatible convenience: the template's one step, exposed under its old flat
    # names (concept doc, section E.4: "Convenience-Felder aufs erste Step-Element mappen").
    # `steps[0]` is the single source of truth; these read and write through to it, so every
    # existing call site, API response shape and Jinja template that expects
    # `template.assigned_agent` etc. keeps working unchanged, whether it is Phase 1's
    # single-step template or (later) the first step of a real chain. Plain `@property`
    # setters keep this Python-side mutable; `@computed_field` makes each one appear in
    # `model_dump()`/`model_dump_json()` exactly like the real fields it replaces.

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assigned_agent(self) -> str:
        return self.steps[0].assigned_agent

    @assigned_agent.setter
    def assigned_agent(self, value: str) -> None:
        self.steps[0].assigned_agent = value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def prompt_source(self) -> str:
        return self.steps[0].prompt_source

    @prompt_source.setter
    def prompt_source(self, value: str) -> None:
        self.steps[0].prompt_source = value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def prompt_id(self) -> Optional[str]:
        return self.steps[0].prompt_id

    @prompt_id.setter
    def prompt_id(self, value: Optional[str]) -> None:
        self.steps[0].prompt_id = value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def prompt_version(self) -> Optional[str]:
        return self.steps[0].prompt_version

    @prompt_version.setter
    def prompt_version(self, value: Optional[str]) -> None:
        self.steps[0].prompt_version = value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def custom_prompt_text(self) -> Optional[str]:
        return self.steps[0].custom_prompt_text

    @custom_prompt_text.setter
    def custom_prompt_text(self, value: Optional[str]) -> None:
        self.steps[0].custom_prompt_text = value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def skill_ids(self) -> List[str]:
        return self.steps[0].skill_ids

    @skill_ids.setter
    def skill_ids(self, value: List[str]) -> None:
        self.steps[0].skill_ids = value


# The flat, step-mirrored fields above - detected so `update_template()` can route an update
# through `steps[0]` instead of silently dropping it (see there for why that matters).
_LEGACY_STEP_FIELDS = {
    "assigned_agent", "prompt_source", "prompt_id", "prompt_version",
    "custom_prompt_text", "skill_ids"
}


class TaskTemplateRegistry:
    def __init__(self):
        self._store = get_store("task_templates", TaskTemplate)

    def create_template(
        self,
        name: str,
        owner: str = "operator",
        prompt_source: str = "custom",
        prompt_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        custom_prompt_text: Optional[str] = None,
        skill_ids: Optional[List[str]] = None,
        assigned_agent: str = "agent:task-solver",
        visibility: str = "own",
        requires_approval: bool = False,
        group: Optional[str] = None,
        on_success: Optional[str] = None,
        on_failure: Optional[str] = None,
        steps: Optional[List[Step]] = None
    ) -> TaskTemplate:
        """Build a new TaskTemplate.

        Either pass the flat convenience fields (the common case - the create-template form
        uses this path, and they are folded into a single default `Step`), or pass `steps`
        directly with exactly one element - the concept doc's Phase 2 chain shape, already
        valid in Phase 1's schema. `TaskTemplate`'s own field validator rejects anything other
        than exactly one step either way, so this method does not need to duplicate that rule.
        """
        template_id = f"TMPL-{uuid.uuid4().hex[:8].upper()}"
        resolved_steps = steps if steps is not None else [Step(
            step_id="step-1",
            position=0,
            assigned_agent=assigned_agent,
            skill_ids=skill_ids or [],
            prompt_source=prompt_source,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            custom_prompt_text=custom_prompt_text
        )]
        template = TaskTemplate(
            template_id=template_id,
            name=name,
            owner=owner,
            visibility=visibility,
            requires_approval=requires_approval,
            group=group,
            on_success=on_success,
            on_failure=on_failure,
            steps=resolved_steps
        )
        self._store.put(template.template_id, template)
        return template

    def get_template(self, template_id: str) -> Optional[TaskTemplate]:
        return self._store.get(template_id)

    def list_all(self, viewer: Optional[str] = None) -> List[TaskTemplate]:
        """All templates, or - with `viewer` set - only the ones that viewer has not hidden.

        A shared template a viewer removed from their own view stays intact for its owner and
        everyone else; only that one viewer's listing skips it (concept doc, section A.4).
        """
        templates = self._store.list_all()
        if viewer:
            templates = [t for t in templates if viewer not in t.removed_by]
        templates.sort(key=lambda t: t.created_at)
        return templates

    def update_template(self, template_id: str, **fields: Any) -> TaskTemplate:
        template = self._store.get(template_id)
        if not template:
            raise TemplateNotFoundError(template_id)

        step_overrides = {key: fields.pop(key) for key in list(fields) if key in _LEGACY_STEP_FIELDS}
        if step_overrides:
            # These are computed properties over steps[0], not stored fields any more -
            # model_copy(update=...) silently drops unknown keys (empirically verified), so
            # route them onto the step directly instead of letting an "update" quietly no-op.
            fields["steps"] = [template.steps[0].model_copy(update=step_overrides)]

        updated = template.model_copy(update={**fields, "updated_at": time.time()})
        self._store.put(template_id, updated)
        return updated

    def delete_template(self, template_id: str, requested_by: str = "operator") -> bool:
        """Only the owner may delete outright. Bindings must be gone first (checked by the caller,
        which also knows about RoutineBinding/ScheduleBinding - see routines.py - and would
        otherwise create an import cycle back into this module).
        """
        template = self._store.get(template_id)
        if not template:
            raise TemplateNotFoundError(template_id)
        if template.owner != requested_by:
            raise TemplatePermissionError(template_id, requested_by, template.owner)
        return self._store.delete(template_id)

    def remove_for_viewer(self, template_id: str, viewer: str) -> TaskTemplate:
        """Hide a shared template from one viewer's own list. Never deletes the template itself."""
        template = self._store.get(template_id)
        if not template:
            raise TemplateNotFoundError(template_id)
        if viewer not in template.removed_by:
            template.removed_by.append(viewer)
            template.updated_at = time.time()
            self._store.put(template_id, template)
        return template


task_template_registry = TaskTemplateRegistry()
