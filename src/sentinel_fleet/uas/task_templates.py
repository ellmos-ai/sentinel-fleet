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
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.errors import TemplateNotFoundError, TemplatePermissionError

# A task template needs at least one step (concept doc, section E.1/E.4): a single-step task is
# the special case of a chain, not a different shape. Multi-step chains are the "Minimaler
# Ketten-Schnitt" of Phase 2, executed by `core/chain_runner.py`.
MIN_STEPS = 1

# The minimal chain cut supports exactly two execution patterns (concept doc, section E.4):
# "single" (the pre-existing one-model-call path) and "race" (chat_service.race(), bound to a
# step). Swarm/operator patterns are real, but their dispatch loops are Phase 3 - a schema that
# accepted them here would let the UI save a step the chain runner then silently cannot execute.
SUPPORTED_EXECUTION_PATTERNS = {"single", "race", "research"}

# Mirrors `chat/service.py`'s `MAX_RACE_LANES` (`RACE_LANE_AGENT_IDS` has 4 entries) - duplicated
# rather than imported so this low-level model module stays free of a dependency on the chat/
# gateway layer. If that race-lane roster ever changes size, this constant must move with it.
MAX_RACE_MODELS = 4

# How many pages one research step may read. Small and named on purpose: the cap is what keeps a
# research step a bounded, auditable act rather than a browsing loop, and an operator has to be
# able to read the number rather than discover it.
MAX_RESEARCH_FETCHES = 5

# Duplicated as a literal rather than imported from conductor/lifecycle for the same reason
# MAX_RACE_MODELS is: this model module stays free of dependencies on the layers above it.
WEB_READER_AGENT_ID = "agent:web-reader"

# Tool name a template/step run is scoped under at the Sovereign Gateway. Lives here, not in
# `routines.py` or `core/chain_runner.py`, because both of those modules need it and importing
# one from the other would be circular (routines.py calls into chain_runner.py to run a chain).
EXECUTE_TEMPLATE_TOOL = "execute_template"


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
    # "previous_output" is the only value the minimal chain cut's runner understands (concept
    # doc, section E.4: input_spec stays fixed at "previous_output" for this cut). None means
    # "no predecessor yet" - the default single step, or a chain's first step.
    input_spec: Optional[str] = None
    # Required by the concept for a real chain (a Phase-2 runner enforces every step
    # depositing its output at a fixed handoff point) but left optional here: Phase 1 has
    # nothing that reads it yet, and the single default step is never chained into anything.
    output_artifact_id: Optional[str] = None
    # Parallel branches ("Schwarm (b)", concept doc section E.1) are a later phase - the minimal
    # chain cut is strictly linear, so this must stay unset (validated below).
    parallel_group: Optional[str] = None
    execution_pattern: str = "single"        # see SUPPORTED_EXECUTION_PATTERNS
    swarm_pattern: Optional[str] = None
    race_models: List[str] = Field(default_factory=list)
    # Pages a research step reads before it answers. The operator names them; the model never
    # does. That is the whole difference between this and a browsing loop: the set of pages a
    # run may touch is fixed before it starts, visible in the step, and auditable afterwards.
    research_urls: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _minimal_chain_cut_shape(self) -> "Step":
        """Rejects step shapes the chain runner cannot execute, before they are ever persisted
        (concept doc, section E.4 "Minimaler Ketten-Schnitt"). Same spirit as the old
        `MAX_STEPS_IN_MVP` guard it replaces: a schema that quietly accepts an unexecutable
        shape just moves the failure to run time, where it is harder to trace back to the step
        that caused it.
        """
        if self.execution_pattern not in SUPPORTED_EXECUTION_PATTERNS:
            raise ValueError(
                f"step '{self.step_id}': execution_pattern must be one of "
                f"{sorted(SUPPORTED_EXECUTION_PATTERNS)} in this deployment (swarm/operator "
                f"patterns are Phase 3, concept doc section E.4) - got '{self.execution_pattern}'."
            )
        if self.execution_pattern == "race":
            if not (2 <= len(self.race_models) <= MAX_RACE_MODELS):
                raise ValueError(
                    f"step '{self.step_id}': a race step needs between 2 and {MAX_RACE_MODELS} "
                    f"models (concept doc, section E.1) - got {len(self.race_models)}."
                )
        elif self.race_models:
            raise ValueError(
                f"step '{self.step_id}': race_models is only meaningful with "
                f"execution_pattern='race', but this step's pattern is '{self.execution_pattern}'."
            )

        if self.execution_pattern == "research":
            if not (1 <= len(self.research_urls) <= MAX_RESEARCH_FETCHES):
                raise ValueError(
                    f"step '{self.step_id}': a research step reads between 1 and "
                    f"{MAX_RESEARCH_FETCHES} pages - got {len(self.research_urls)}."
                )
            if self.assigned_agent == WEB_READER_AGENT_ID:
                # The fetches already run as agent:web-reader; the synthesis runs as this agent
                # and calls execute_template, which web-reader is not scoped for. The gateway
                # would answer that by quarantining it - and a misconfigured step would take the
                # fleet's only fetching identity offline.
                raise ValueError(
                    f"step '{self.step_id}': a research step cannot run as "
                    f"'{WEB_READER_AGENT_ID}'. That identity fetches the pages; the step's own "
                    "agent writes the answer, and web-reader is not scoped to do that."
                )
        elif self.research_urls:
            raise ValueError(
                f"step '{self.step_id}': research_urls is only meaningful with "
                f"execution_pattern='research', but this step's pattern is "
                f"'{self.execution_pattern}'."
            )
        if self.parallel_group is not None:
            raise ValueError(
                f"step '{self.step_id}': parallel_group is a later phase's parallel-branch "
                "feature, not part of the minimal chain cut (concept doc, section E.4)."
            )
        if self.input_spec not in (None, "previous_output"):
            raise ValueError(
                f"step '{self.step_id}': input_spec must be unset or 'previous_output' in this "
                f"deployment (concept doc, section E.4) - got '{self.input_spec}'."
            )
        return self


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
    def _steps_form_a_valid_chain(cls, value: List[Step]) -> List[Step]:
        """A single-step template (the default) and a multi-step chain (concept doc, section
        E.4 "Minimaler Ketten-Schnitt") are the same shape, validated the same way - there is no
        separate "MVP mode" any more. Three invariants: at least one step, unique step ids, and
        positions that form a gapless 0..n-1 sequence once sorted - the
        chain runner executes `sorted(steps, key=lambda s: s.position)`, so a gap or a duplicate
        would silently skip or collide two steps at run time instead of failing here.
        """
        if len(value) < MIN_STEPS:
            raise ValueError(f"A task template needs at least {MIN_STEPS} step - got {len(value)}.")

        step_ids = [s.step_id for s in value]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError(f"Step ids must be unique within a template - got {step_ids}.")

        positions = sorted(s.position for s in value)
        if positions != list(range(len(value))):
            raise ValueError(
                "Step positions must be gapless and unique, forming a dense 0..n-1 sequence "
                f"once sorted (concept doc, section E.4) - got {positions}."
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
        # model_copy() does not re-run validators (Pydantic v2, by design) - revalidate
        # explicitly so an update that breaks a cross-field invariant (steps positions, a race
        # step's model count, ...) is caught here instead of persisting a template the chain
        # runner cannot execute. The round trip itself is already exercised and proven safe by
        # test_template_roundtrips_through_model_dump_and_validate.
        updated = TaskTemplate.model_validate(updated.model_dump())
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

    def restore_for_viewer(self, template_id: str, viewer: str) -> TaskTemplate:
        """Undo `remove_for_viewer()` - the mirror action a hidden template's own "Restore"
        row needs (concept doc, section D Phase 2 "removed_by-Liste"). A no-op, not an error,
        when the viewer never hid this template - restoring twice is as harmless as hiding
        twice already is above.
        """
        template = self._store.get(template_id)
        if not template:
            raise TemplateNotFoundError(template_id)
        if viewer in template.removed_by:
            template.removed_by.remove(viewer)
            template.updated_at = time.time()
            self._store.put(template_id, template)
        return template

    def list_hidden_for_viewer(self, viewer: str) -> List[TaskTemplate]:
        """The templates one viewer has hidden from their own list - the source for the
        "hidden for you" panel that carries the Restore action. Every entry here is still
        intact for its owner and everyone else, exactly as `remove_for_viewer()` promises.
        """
        templates = [t for t in self._store.list_all() if viewer in t.removed_by]
        templates.sort(key=lambda t: t.created_at)
        return templates


task_template_registry = TaskTemplateRegistry()
