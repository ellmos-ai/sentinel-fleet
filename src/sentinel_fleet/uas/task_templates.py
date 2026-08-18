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
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.errors import TemplateNotFoundError, TemplatePermissionError


class Step(BaseModel):
    """One execution node of a TaskTemplate. Embedded on the template (like
    `PromptVersionRecord` on `PromptItem`, `prompts.py:8-18`), not a separate `get_store()`
    entity - there is exactly one of these in Phase 1, added here so Phase 2's "add more
    steps" chains need no schema break or data migration (concept doc, section E.1/E.4).
    Phase 1 never reads or executes this - `enqueue_template()` still runs off the
    TaskTemplate's own flat prompt_source/skill_ids/assigned_agent fields below, which
    `TaskTemplateRegistry.create_template()` mirrors into `steps[0]` at creation time so the
    field is a faithful snapshot rather than an inert stub.
    """
    step_id: str
    position: int = 0                        # ordering, once there is more than one step
    agent_id: str = "agent:task-solver"
    skill_ids: List[str] = Field(default_factory=list)
    prompt_source: str = "custom"            # "library" | "custom"
    prompt_id: Optional[str] = None
    prompt_version: Optional[str] = None
    custom_prompt_text: Optional[str] = None
    input_spec: str = "previous_output"      # "previous_output" | "template_input" | "artifact:<step_id>"
    # Required by the concept (a Phase-2 chain runner enforces every step depositing its
    # output at a fixed handoff point), but left optional here: Phase 1 has nothing that
    # reads it yet, and the single default step is never chained into anything.
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
    prompt_source: str = "custom"          # "library" | "custom"
    prompt_id: Optional[str] = None        # ref PromptItem.id, when prompt_source == "library"
    prompt_version: Optional[str] = None   # pinned version, same convention as the chat console
    custom_prompt_text: Optional[str] = None
    skill_ids: List[str] = Field(default_factory=list)
    assigned_agent: str = "agent:task-solver"
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
    # or loop in the UI - but the field exists from day one.
    steps: List[Step] = Field(default_factory=_default_steps)
    loop: Optional[LoopConfig] = None      # only set once a chain is a circle - always None here
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


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
        on_failure: Optional[str] = None
    ) -> TaskTemplate:
        template_id = f"TMPL-{uuid.uuid4().hex[:8].upper()}"
        resolved_skill_ids = skill_ids or []
        template = TaskTemplate(
            template_id=template_id,
            name=name,
            owner=owner,
            prompt_source=prompt_source,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            custom_prompt_text=custom_prompt_text,
            skill_ids=resolved_skill_ids,
            assigned_agent=assigned_agent,
            visibility=visibility,
            requires_approval=requires_approval,
            group=group,
            on_success=on_success,
            on_failure=on_failure,
            # Mirror the flat fields into the single default step, so `steps[0]` is a real
            # snapshot of this template's one step rather than an inert, disconnected stub
            # (concept doc, section E.4: "Convenience-Felder aufs erste Step-Element mappen").
            steps=[Step(
                step_id="step-1",
                position=0,
                agent_id=assigned_agent,
                skill_ids=resolved_skill_ids,
                prompt_source=prompt_source,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                custom_prompt_text=custom_prompt_text
            )]
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

    def update_template(self, template_id: str, **fields) -> TaskTemplate:
        template = self._store.get(template_id)
        if not template:
            raise TemplateNotFoundError(template_id)
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
