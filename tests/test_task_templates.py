"""Unit tests for the TaskTemplate registry: CRUD, the delete guard and per-viewer rights.

TaskTemplate is the "everything is a task" foundation (concept doc, section A.1): a bare
skeleton is a template with no binding attached, and it only becomes deletable once every
routine and schedule binding is gone again.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError

from sentinel_fleet.core.errors import TemplateHasBindingsError, TemplateNotFoundError, TemplatePermissionError
from sentinel_fleet.uas import routines
from sentinel_fleet.uas.task_templates import Step, TaskTemplate, task_template_registry
from sentinel_fleet.web.server import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def test_create_and_get_template():
    template = task_template_registry.create_template(
        name="Reconcile bank statements",
        owner="alice",
        prompt_source="custom",
        custom_prompt_text="Match bank lines against booked invoices.",
        group="finance"
    )
    assert template.template_id.startswith("TMPL-")
    assert template.owner == "alice"
    assert template.group == "finance"
    assert template.removed_by == []
    assert template.created_at == template.updated_at

    fetched = task_template_registry.get_template(template.template_id)
    assert fetched is not None
    assert fetched.name == "Reconcile bank statements"


def test_get_missing_template_returns_none():
    assert task_template_registry.get_template("TMPL-DOES-NOT-EXIST") is None


def test_delete_missing_template_raises():
    with pytest.raises(TemplateNotFoundError):
        task_template_registry.delete_template("TMPL-DOES-NOT-EXIST")


def test_update_template_bumps_updated_at_and_keeps_the_rest():
    template = task_template_registry.create_template(name="Draft template", owner="ines")
    updated = task_template_registry.update_template(template.template_id, name="Renamed template", group="ops")
    assert updated.name == "Renamed template"
    assert updated.group == "ops"
    assert updated.owner == "ines"  # untouched fields survive a partial update
    assert updated.updated_at >= template.updated_at


def test_owner_can_delete_a_bare_template():
    template = task_template_registry.create_template(name="Disposable template", owner="carol")
    assert routines.delete_template(template.template_id, requested_by="carol") is True
    assert task_template_registry.get_template(template.template_id) is None


def test_non_owner_cannot_delete_a_shared_template():
    """"Freigegeben entfernen ≠ löschen" (concept doc, section A.4): only the owner deletes."""
    template = task_template_registry.create_template(name="Shared template", owner="dave", visibility="organization")

    with pytest.raises(TemplatePermissionError):
        routines.delete_template(template.template_id, requested_by="erin")

    # Untouched: still there for the owner and for anyone else who has not hidden it.
    assert task_template_registry.get_template(template.template_id) is not None


def test_non_owner_removes_from_own_view_instead_of_deleting():
    template = task_template_registry.create_template(name="Shared onboarding checklist", owner="frank")

    updated = task_template_registry.remove_for_viewer(template.template_id, "grace")
    assert "grace" in updated.removed_by

    # Gone from grace's own listing...
    assert template.template_id not in {t.template_id for t in task_template_registry.list_all(viewer="grace")}
    # ...but the template itself, and everyone else's view of it, is untouched.
    assert task_template_registry.get_template(template.template_id) is not None
    assert template.template_id in {t.template_id for t in task_template_registry.list_all(viewer="frank")}
    assert template.template_id in {t.template_id for t in task_template_registry.list_all()}

    # Hiding twice is a no-op, not two entries in the list.
    task_template_registry.remove_for_viewer(template.template_id, "grace")
    again = task_template_registry.get_template(template.template_id)
    assert again.removed_by.count("grace") == 1


def test_delete_guard_blocks_while_a_routine_binding_is_attached():
    template = task_template_registry.create_template(name="Bound by a routine", owner="henry")
    routines.routine_binding_registry.set_binding(template.template_id, {"kind": "interval", "seconds": 3600})

    assert routines.bindings_summary(template.template_id) == ["routine"]
    with pytest.raises(TemplateHasBindingsError) as excinfo:
        routines.delete_template(template.template_id, requested_by="henry")
    assert excinfo.value.details["bindings"] == ["routine"]
    assert task_template_registry.get_template(template.template_id) is not None  # not deleted

    routines.routine_binding_registry.remove_for_template(template.template_id)
    assert routines.bindings_summary(template.template_id) == []
    assert routines.delete_template(template.template_id, requested_by="henry") is True


def test_delete_guard_blocks_while_a_pending_schedule_binding_is_attached():
    template = task_template_registry.create_template(name="Bound by a schedule", owner="ivy")
    routines.schedule_binding_registry.set_binding(template.template_id, due_at="2099-01-01T00:00:00+00:00")

    assert routines.bindings_summary(template.template_id) == ["schedule"]
    with pytest.raises(TemplateHasBindingsError):
        routines.delete_template(template.template_id, requested_by="ivy")

    routines.schedule_binding_registry.remove_pending_for_template(template.template_id)
    assert routines.delete_template(template.template_id, requested_by="ivy") is True


def test_delete_guard_lists_both_binding_kinds_when_both_are_attached():
    template = task_template_registry.create_template(name="Doubly bound", owner="jack")
    routines.routine_binding_registry.set_binding(template.template_id, {"kind": "interval", "seconds": 60})
    routines.schedule_binding_registry.set_binding(template.template_id, due_at="2099-01-01T00:00:00+00:00")

    with pytest.raises(TemplateHasBindingsError) as excinfo:
        routines.delete_template(template.template_id, requested_by="jack")
    assert set(excinfo.value.details["bindings"]) == {"routine", "schedule"}


# ---------------------------------------------------------------------------
# Steps: TaskTemplate.steps is the actual storage for a single step's configuration; the
# flat prompt_source/skill_ids/assigned_agent fields are computed properties reading through
# to steps[0] (concept doc, section E.1/E.4 - "Convenience-Felder aufs erste Step-Element
# mappen"). Phase 1 executes only the single-step case; the schema already carries the shape
# Phase 2 chains will use, guarded by a validator that rejects anything but one step.
# ---------------------------------------------------------------------------

def test_step_is_derived_from_the_flat_fields_passed_to_create_template():
    template = task_template_registry.create_template(
        name="Flat-to-step derivation",
        owner="kate",
        prompt_source="custom",
        custom_prompt_text="Summarise the inbox.",
        skill_ids=["skill:tax-compliance-v1", "skill:pdf-vision-extractor"],
        assigned_agent="agent:invoice-extractor"
    )

    assert len(template.steps) == 1
    step = template.steps[0]
    assert step.assigned_agent == "agent:invoice-extractor"
    assert step.custom_prompt_text == "Summarise the inbox."
    assert step.skill_ids == ["skill:tax-compliance-v1", "skill:pdf-vision-extractor"]
    assert step.prompt_source == "custom"

    # The flat properties read straight through to that same step - not a second copy.
    assert template.assigned_agent == step.assigned_agent
    assert template.custom_prompt_text == step.custom_prompt_text
    assert template.skill_ids == step.skill_ids


def test_flat_property_assignment_writes_through_to_the_step():
    template = task_template_registry.create_template(name="Writable convenience field", owner="liam")

    template.assigned_agent = "agent:compliance-auditor"
    assert template.steps[0].assigned_agent == "agent:compliance-auditor"

    template.custom_prompt_text = "Audit this invoice."
    assert template.steps[0].custom_prompt_text == "Audit this invoice."

    template.skill_ids = ["skill:model-armor-sentry"]
    assert template.steps[0].skill_ids == ["skill:model-armor-sentry"]


def test_more_than_one_step_is_rejected_in_the_mvp():
    with pytest.raises(ValidationError, match="exactly 1 step"):
        TaskTemplate(
            template_id="TMPL-TOO-MANY",
            name="Two-step chain",
            steps=[Step(step_id="a", position=0), Step(step_id="b", position=1)]
        )

    with pytest.raises(ValidationError, match="exactly 1 step"):
        task_template_registry.create_template(
            name="Two-step chain via registry",
            owner="mia",
            steps=[Step(step_id="a", position=0), Step(step_id="b", position=1)]
        )


def test_zero_steps_is_rejected_in_the_mvp():
    """A template needs its one executable step - an empty chain is as invalid as a chain."""
    with pytest.raises(ValidationError, match="exactly 1 step"):
        TaskTemplate(template_id="TMPL-EMPTY", name="No steps", steps=[])


def test_template_roundtrips_through_model_dump_and_validate():
    """The computed convenience fields must not break persistence: LocalJsonStore dumps to
    JSON and reloads via `model_validate()` on every write and on process restart."""
    template = task_template_registry.create_template(
        name="Roundtrip probe", owner="noah", custom_prompt_text="Do the thing.",
        skill_ids=["skill:pdf-vision-extractor"], assigned_agent="agent:task-solver"
    )
    dumped = template.model_dump()
    assert dumped["assigned_agent"] == "agent:task-solver"  # computed field present in the dump

    restored = TaskTemplate.model_validate(dumped)
    assert restored.assigned_agent == template.assigned_agent
    assert restored.steps == template.steps
    assert restored.model_dump() == dumped

    # The registry's own store actually persists and reloads through get_template().
    fetched = task_template_registry.get_template(template.template_id)
    assert fetched.assigned_agent == "agent:task-solver"
    assert fetched.custom_prompt_text == "Do the thing."


def test_update_template_with_a_legacy_flat_field_routes_through_the_step():
    """A plain model_copy(update={"assigned_agent": ...}) would silently no-op, because that
    name is no longer a stored field (empirically verified). update_template() must route it
    onto steps[0] instead, so a future edit-template endpoint built against the old flat
    field names keeps working."""
    template = task_template_registry.create_template(name="Editable template", owner="olivia")

    updated = task_template_registry.update_template(
        template.template_id, assigned_agent="agent:compliance-auditor", group="finance"
    )

    assert updated.assigned_agent == "agent:compliance-auditor"
    assert updated.steps[0].assigned_agent == "agent:compliance-auditor"
    assert updated.group == "finance"  # a genuine field update still applies normally


@pytest.mark.asyncio
async def test_create_task_template_accepts_an_explicit_single_step_array(client):
    response = await client.post("/api/task-templates", data={
        "name": "Explicit steps array",
        "steps": '[{"step_id": "step-1", "assigned_agent": "agent:task-solver", '
                 '"custom_prompt_text": "Explicit step body."}]'
    })
    assert response.status_code == 200
    template = response.json()["template"]
    assert len(template["steps"]) == 1
    assert template["steps"][0]["custom_prompt_text"] == "Explicit step body."
    assert template["assigned_agent"] == "agent:task-solver"


@pytest.mark.asyncio
async def test_create_task_template_rejects_an_explicit_multi_step_array(client):
    response = await client.post("/api/task-templates", data={
        "name": "Explicit steps array, too many",
        "steps": '[{"step_id": "a"}, {"step_id": "b"}]'
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_task_template_rejects_malformed_steps_json(client):
    response = await client.post("/api/task-templates", data={
        "name": "Malformed steps",
        "steps": "not json"
    })
    assert response.status_code == 422
