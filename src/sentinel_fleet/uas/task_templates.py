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
        template = TaskTemplate(
            template_id=f"TMPL-{uuid.uuid4().hex[:8].upper()}",
            name=name,
            owner=owner,
            prompt_source=prompt_source,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            custom_prompt_text=custom_prompt_text,
            skill_ids=skill_ids or [],
            assigned_agent=assigned_agent,
            visibility=visibility,
            requires_approval=requires_approval,
            group=group,
            on_success=on_success,
            on_failure=on_failure
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
