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
from sentinel_fleet.core.prompts import prompt_registry
from sentinel_fleet.core.skills import skill_registry
from sentinel_fleet.uas import routines
from sentinel_fleet.uas.task_templates import MAX_RACE_MODELS, Step, TaskTemplate, task_template_registry
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


def test_restore_for_viewer_undoes_a_hide():
    """`restore_for_viewer()` is `remove_for_viewer()`'s mirror action (concept doc, section
    D Phase 2 "removed_by-Liste") - the "hidden for you" panel's Restore button."""
    template = task_template_registry.create_template(name="Shared audit checklist", owner="henry")

    task_template_registry.remove_for_viewer(template.template_id, "ines")
    assert template.template_id in {t.template_id for t in task_template_registry.list_hidden_for_viewer("ines")}
    assert template.template_id not in {t.template_id for t in task_template_registry.list_all(viewer="ines")}

    restored = task_template_registry.restore_for_viewer(template.template_id, "ines")
    assert "ines" not in restored.removed_by
    assert template.template_id in {t.template_id for t in task_template_registry.list_all(viewer="ines")}
    assert task_template_registry.list_hidden_for_viewer("ines") == []


def test_restore_for_viewer_without_a_prior_hide_is_a_no_op():
    template = task_template_registry.create_template(name="Never hidden", owner="jack")
    before = template.updated_at

    restored = task_template_registry.restore_for_viewer(template.template_id, "kim")
    assert restored.removed_by == []
    assert restored.updated_at == before  # no spurious write when nothing changed


def test_list_hidden_for_viewer_is_per_viewer():
    template = task_template_registry.create_template(name="Shared release checklist", owner="lena")
    task_template_registry.remove_for_viewer(template.template_id, "mia")

    assert template.template_id in {t.template_id for t in task_template_registry.list_hidden_for_viewer("mia")}
    # A different viewer never hid it - it must not show up in their hidden list.
    assert template.template_id not in {t.template_id for t in task_template_registry.list_hidden_for_viewer("noah")}


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


def test_multi_step_chains_are_now_supported():
    """Migrated from the old "exactly 1 step" MVP guard (concept doc, section E.4 "Minimaler
    Ketten-Schnitt"): a template with several steps, gapless positions and unique ids is valid
    - the shape this test used to reject is now the shape Phase 2 chains use.
    """
    template = TaskTemplate(
        template_id="TMPL-TWO-STEPS",
        name="Two-step chain",
        steps=[Step(step_id="a", position=0), Step(step_id="b", position=1)]
    )
    assert len(template.steps) == 2

    via_registry = task_template_registry.create_template(
        name="Two-step chain via registry",
        owner="mia",
        steps=[Step(step_id="a", position=0), Step(step_id="b", position=1)]
    )
    assert len(via_registry.steps) == 2


def test_zero_steps_is_rejected():
    """A template needs at least one executable step - an empty chain is as invalid as before,
    just under the new "at least 1" wording (concept doc, section E.4)."""
    with pytest.raises(ValidationError, match="at least 1 step"):
        TaskTemplate(template_id="TMPL-EMPTY", name="No steps", steps=[])


def test_duplicate_step_ids_are_rejected():
    with pytest.raises(ValidationError, match="unique"):
        TaskTemplate(
            template_id="TMPL-DUP-IDS",
            name="Duplicate step ids",
            steps=[Step(step_id="a", position=0), Step(step_id="a", position=1)]
        )


def test_duplicate_positions_are_rejected():
    with pytest.raises(ValidationError, match="gapless"):
        TaskTemplate(
            template_id="TMPL-DUP-POS",
            name="Duplicate positions",
            steps=[Step(step_id="a", position=0), Step(step_id="b", position=0)]
        )


def test_gappy_positions_are_rejected():
    with pytest.raises(ValidationError, match="gapless"):
        TaskTemplate(
            template_id="TMPL-GAP-POS",
            name="Gappy positions",
            steps=[Step(step_id="a", position=0), Step(step_id="b", position=2)]
        )


def test_only_single_and_race_execution_patterns_are_supported():
    with pytest.raises(ValidationError, match="execution_pattern"):
        Step(step_id="a", execution_pattern="operator")
    with pytest.raises(ValidationError, match="execution_pattern"):
        Step(step_id="a", execution_pattern="swarm:hierarchy")


def test_race_step_needs_between_two_and_four_models():
    with pytest.raises(ValidationError, match="between 2 and"):
        Step(step_id="a", execution_pattern="race", race_models=["gemini-3.5-flash"])
    with pytest.raises(ValidationError, match="between 2 and"):
        Step(
            step_id="a", execution_pattern="race",
            race_models=[f"model-{i}" for i in range(MAX_RACE_MODELS + 1)]
        )
    # Exactly at the bounds is valid.
    Step(step_id="a", execution_pattern="race", race_models=["gemini-3.5-flash", "gemini-3.5-pro"])


def test_race_models_only_allowed_with_race_pattern():
    with pytest.raises(ValidationError, match="only meaningful with execution_pattern='race'"):
        Step(step_id="a", execution_pattern="single", race_models=["gemini-3.5-flash", "gemini-3.5-pro"])


def test_parallel_group_is_rejected_in_the_minimal_chain_cut():
    with pytest.raises(ValidationError, match="parallel_group"):
        Step(step_id="a", parallel_group="branch-1")


def test_input_spec_only_supports_previous_output():
    with pytest.raises(ValidationError, match="input_spec"):
        Step(step_id="a", input_spec="template_input")
    with pytest.raises(ValidationError, match="input_spec"):
        Step(step_id="a", input_spec="artifact:step-1")
    # Both the default (None) and the one supported value are valid.
    Step(step_id="a")
    Step(step_id="a", input_spec="previous_output")


def test_update_template_revalidates_steps_and_rejects_a_broken_chain():
    """model_copy(update=...) does not re-run validators (Pydantic v2) - update_template() must
    revalidate explicitly, or a broken chain (duplicate positions here) would silently persist.
    """
    template = task_template_registry.create_template(name="Revalidation probe", owner="nadia")
    with pytest.raises(ValidationError, match="gapless"):
        task_template_registry.update_template(
            template.template_id,
            steps=[Step(step_id="a", position=0), Step(step_id="b", position=0)]
        )
    # Untouched: the broken update never persisted.
    assert len(task_template_registry.get_template(template.template_id).steps) == 1


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
async def test_create_task_template_accepts_a_valid_multi_step_array(client):
    """A gapless, uniquely-positioned multi-step array is now a real chain (concept doc,
    section E.4), not just schema future-proofing - this used to be the rejection case."""
    response = await client.post("/api/task-templates", data={
        "name": "Two-step chain via the API",
        "steps": '[{"step_id": "step-1", "position": 0, "custom_prompt_text": "First."}, '
                 '{"step_id": "step-2", "position": 1, "custom_prompt_text": "Second."}]'
    })
    assert response.status_code == 200
    template = response.json()["template"]
    assert len(template["steps"]) == 2
    assert [s["step_id"] for s in template["steps"]] == ["step-1", "step-2"]


@pytest.mark.asyncio
async def test_create_task_template_rejects_steps_with_duplicate_positions(client):
    """Both steps default to position=0 here - rejected for a duplicate position, not for
    having "too many" steps (that rule no longer exists, see the test above)."""
    response = await client.post("/api/task-templates", data={
        "name": "Explicit steps array, duplicate positions",
        "steps": '[{"step_id": "a", "position": 0}, {"step_id": "b", "position": 0}]'
    })
    assert response.status_code == 422
    assert "gapless" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_task_template_rejects_malformed_steps_json(client):
    response = await client.post("/api/task-templates", data={
        "name": "Malformed steps",
        "steps": "not json"
    })
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/task-templates/{id}/steps: add/change/remove/reorder are all the same operation -
# submit the whole edited array, position = index order (concept doc, section E.4).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_steps_endpoint_replaces_the_whole_list(client):
    template = task_template_registry.create_template(name="Editable steps", owner="petra")

    response = await client.put(f"/api/task-templates/{template.template_id}/steps", data={
        "steps": '[{"step_id": "a", "position": 0, "custom_prompt_text": "First."}, '
                 '{"step_id": "b", "position": 1, "custom_prompt_text": "Second."}]'
    })
    assert response.status_code == 200
    updated = response.json()["template"]
    assert [s["step_id"] for s in updated["steps"]] == ["a", "b"]

    fetched = task_template_registry.get_template(template.template_id)
    assert len(fetched.steps) == 2


@pytest.mark.asyncio
async def test_update_steps_endpoint_reorders_by_resubmitting_positions(client):
    """"Umordnen" is the same call as add/change/remove: the client re-sends every step with
    its new position - here a→1, b→0 swaps the execution order."""
    template = task_template_registry.create_template(
        name="Reorder probe", owner="quinn",
        steps=[Step(step_id="a", position=0), Step(step_id="b", position=1)]
    )

    response = await client.put(f"/api/task-templates/{template.template_id}/steps", data={
        "steps": '[{"step_id": "a", "position": 1}, {"step_id": "b", "position": 0}]'
    })
    assert response.status_code == 200
    fetched = task_template_registry.get_template(template.template_id)
    assert [s.step_id for s in sorted(fetched.steps, key=lambda s: s.position)] == ["b", "a"]


@pytest.mark.asyncio
async def test_update_steps_endpoint_returns_404_for_a_missing_template(client):
    response = await client.put("/api/task-templates/TMPL-DOES-NOT-EXIST/steps", data={
        "steps": '[{"step_id": "a", "position": 0}]'
    })
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_steps_endpoint_rejects_malformed_json(client):
    template = task_template_registry.create_template(name="Bad JSON target", owner="rio")
    response = await client.put(f"/api/task-templates/{template.template_id}/steps", data={"steps": "not json"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_steps_endpoint_rejects_an_empty_array(client):
    template = task_template_registry.create_template(name="Empty array target", owner="sana")
    response = await client.put(f"/api/task-templates/{template.template_id}/steps", data={"steps": "[]"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_steps_endpoint_rejects_gappy_positions(client):
    template = task_template_registry.create_template(name="Gap target", owner="tariq")
    response = await client.put(f"/api/task-templates/{template.template_id}/steps", data={
        "steps": '[{"step_id": "a", "position": 0}, {"step_id": "b", "position": 5}]'
    })
    assert response.status_code == 422
    assert "gapless" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_endpoint_carries_steps_and_step_count_for_the_editor(client):
    template = task_template_registry.create_template(
        name="Two-step for the dashboard", owner="vik",
        steps=[Step(step_id="b", position=1), Step(step_id="a", position=0)]
    )

    response = await client.get("/api/task-templates")
    assert response.status_code == 200
    row = next(r for r in response.json() if r["template_id"] == template.template_id)

    assert row["step_count"] == 2
    # Sorted by position for the editor, regardless of storage order.
    assert [s["step_id"] for s in row["steps"]] == ["a", "b"]


@pytest.mark.asyncio
async def test_dashboard_shows_a_step_count_chip_for_a_multi_step_template():
    task_template_registry.create_template(
        name="Chip visibility probe", owner="wren",
        steps=[Step(step_id="a", position=0), Step(step_id="b", position=1)]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        body = (await ac.get("/")).text
    assert "2 steps" in body


@pytest.mark.asyncio
async def test_dashboard_shows_the_history_toggle_and_wizard_entry_points(client):
    """Markup guard for the two Phase-2 UI additions that render unconditionally once at least
    one template exists (concept doc, section D Phase 2 "Verlauf-Ansicht"/"Wizard-UI").
    """
    template = task_template_registry.create_template(name="History toggle probe", owner="oskar")

    body = (await client.get("/")).text
    assert f"toggleHistoryPanel(\"{template.template_id}\"" in body
    assert f'id="history-row-{template.template_id}"' in body
    assert 'onclick="openWizardFromChat()"' in body


@pytest.mark.asyncio
async def test_update_steps_endpoint_rejects_an_unsupported_race_model(client):
    template = task_template_registry.create_template(name="Bad race model target", owner="uma")
    response = await client.put(f"/api/task-templates/{template.template_id}/steps", data={
        "steps": '[{"step_id": "a", "position": 0, "execution_pattern": "race", '
                 '"race_models": ["gemini-3.5-flash", "made-up-model"]}]'
    })
    assert response.status_code == 422
    assert "made-up-model" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Per-viewer hide/restore endpoints (concept doc, section D Phase 2 "removed_by") and the
# `viewer` query string that threads that identity through `GET /` (server.py's index_view).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_for_me_endpoint_hides_and_restore_for_me_undoes_it(client):
    template = task_template_registry.create_template(name="Shared onboarding pack", owner="xena")

    hide = await client.post(f"/api/task-templates/{template.template_id}/remove-for-me", data={"viewer": "yara"})
    assert hide.status_code == 200
    assert "yara" in hide.json()["template"]["removed_by"]

    listing = await client.get("/api/task-templates", params={"viewer": "yara"})
    assert template.template_id not in {r["template_id"] for r in listing.json()}

    restore = await client.post(f"/api/task-templates/{template.template_id}/restore-for-me", data={"viewer": "yara"})
    assert restore.status_code == 200
    assert "yara" not in restore.json()["template"]["removed_by"]

    listing_after = await client.get("/api/task-templates", params={"viewer": "yara"})
    assert template.template_id in {r["template_id"] for r in listing_after.json()}


@pytest.mark.asyncio
async def test_index_viewer_query_param_filters_the_tasks_card_and_shows_the_hidden_panel(client):
    template = task_template_registry.create_template(name="Zeds shared checklist", owner="zed")
    await client.post(f"/api/task-templates/{template.template_id}/remove-for-me", data={"viewer": "amir"})

    # Default viewer ("operator") never hid it - still visible there.
    default_view = await client.get("/")
    assert "Zeds shared checklist" in default_view.text

    # amir hid it - gone from the Tasks card, but surfaced in the "hidden for you" panel with
    # a Restore action, not silently dropped. The panel accumulates across every test that has
    # ever hidden something for "amir" (LocalJsonStore persists to disk, concept doc, section
    # A.2's storage pattern), so this checks the specific row, not an exact count.
    amir_view = await client.get("/", params={"viewer": "amir"})
    assert "Hidden for you (" in amir_view.text
    assert f'restoreTemplateForViewer("{template.template_id}", "amir")' in amir_view.text
    assert 'value="amir"' in amir_view.text  # the "Viewing as" input reflects the query param


@pytest.mark.asyncio
async def test_index_only_offers_hide_for_shared_not_own_templates(client):
    """The hide action needs both halves of "shared, not own" (concept doc, section A.4):
    a template still on its default `visibility="own"` is not shared yet, no matter who owns
    it, so the button must stay off even when someone else is viewing.
    """
    own = task_template_registry.create_template(name="Amirs own draft", owner="amir")
    shared = task_template_registry.create_template(
        name="Amir sees this shared one", owner="brynn", visibility="organization"
    )

    body = (await client.get("/", params={"viewer": "amir"})).text.replace('"', "'")
    assert f"hideTemplateForViewer('{own.template_id}'" not in body
    assert f"hideTemplateForViewer('{shared.template_id}'" in body


# ---------------------------------------------------------------------------
# Version wiring (concept doc, section D Phase 2 "Sauberes Verdrahten von add_prompt_version()/
# add_skill_version()"): the task wizard's own call chain replayed at the API level, since this
# project's test suite is pytest-only and the wizard's staging logic lives in app.js. This
# proves the two endpoints it calls do what the wizard's forked-text/staged-fork flow needs -
# not a second copy of PromptRegistry/SkillRegistry version logic, the same endpoints the
# Prompts/Skills tabs already use.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wizard_call_chain_forks_a_prompt_then_pins_the_new_version_on_the_template(client):
    prompt = prompt_registry.get_prompt("prompt:deep-task-solver")
    assert prompt is not None
    original_version_count = len(prompt.versions)

    fork = await client.post(f"/api/prompts/{prompt.id}/version", data={
        "new_version_number": "9.9.0",
        "new_text": "Forked for a one-off wizard task: {{task_title}} / {{memory_context}}",
        "change_summary": "Adjusted from the task wizard"
    })
    assert fork.status_code == 200
    forked = fork.json()["prompt"]
    assert forked["active_version"] == "9.9.0"
    assert len(forked["versions"]) == original_version_count + 1

    create = await client.post("/api/task-templates", data={
        "name": "Wizard-forked prompt task",
        "owner": "priya",
        "steps": '[{"step_id": "step-1", "position": 0, "assigned_agent": "agent:task-solver", '
                 f'"prompt_source": "library", "prompt_id": "{prompt.id}", "prompt_version": "9.9.0"}}]'
    })
    assert create.status_code == 200
    template = create.json()["template"]
    assert template["prompt_id"] == prompt.id
    assert template["prompt_version"] == "9.9.0"

    # The registry, not a second copy on the template, still holds the version's text - pinning
    # only stores the version number (concept doc, section A.2 "gepinnte Version").
    assert prompt_registry.get_version(prompt.id, "9.9.0").text.startswith("Forked for a one-off wizard task")


@pytest.mark.asyncio
async def test_wizard_call_chain_forks_a_skill_then_attaches_it_to_a_new_template(client):
    skill = skill_registry.create_skill(
        name="wizard fork source", pillar="domain", description="Base skill for a wizard fork test"
    )

    fork = await client.post(f"/api/skills/{skill.skill_id}/version", data={
        "new_version_number": "1.1.0",
        "change_summary": "Adjusted from the task wizard",
        "required_tools": "inspect_prompt, sanitize_pii"
    })
    assert fork.status_code == 200
    forked = fork.json()["skill"]
    assert forked["version"] == "1.1.0"
    assert forked["required_tools"] == ["inspect_prompt", "sanitize_pii"]

    create = await client.post("/api/task-templates", data={
        "name": "Wizard-forked skill task",
        "owner": "priya",
        "skill_ids": skill.skill_id
    })
    assert create.status_code == 200
    assert skill.skill_id in create.json()["template"]["skill_ids"]

    # The fork is a real, independent version bump on the skill registry - visible there too,
    # not something only the template remembers.
    assert skill_registry.get_skill(skill.skill_id).version == "1.1.0"
