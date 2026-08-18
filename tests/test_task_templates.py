"""Unit tests for the TaskTemplate registry: CRUD, the delete guard and per-viewer rights.

TaskTemplate is the "everything is a task" foundation (concept doc, section A.1): a bare
skeleton is a template with no binding attached, and it only becomes deletable once every
routine and schedule binding is gone again.
"""

import pytest

from sentinel_fleet.core.errors import TemplateHasBindingsError, TemplateNotFoundError, TemplatePermissionError
from sentinel_fleet.uas import routines
from sentinel_fleet.uas.task_templates import task_template_registry


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
