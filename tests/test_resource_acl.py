"""Cross-principal regression tests for task, template and ticket ACLs."""

import pytest

from sentinel_fleet.core.errors import TemplatePermissionError
from sentinel_fleet.uas.task_master import TaskMaster, TaskRecord, TaskState
from sentinel_fleet.uas.task_templates import TaskTemplateRegistry
from sentinel_fleet.uas.ticket_master import TicketMaster, TicketStatus


def test_task_acl_defaults_fail_closed_for_legacy_and_unmigrated_callers():
    tasks = TaskMaster()
    task = tasks.create_task("Legacy-shaped", "agent:test", {})

    assert task.owner_id == "legacy-unassigned"
    assert task.organization_id == "legacy-unassigned"
    assert task.visibility == "private"
    assert not tasks.can_read(task, "operator", "sentinel-demo")
    assert not tasks.can_edit(
        task,
        "operator",
        "legacy-unassigned",
        can_edit_foreign=True,
    )


def test_task_record_can_persist_a_downloadable_result_artifact_reference():
    task = TaskRecord(
        task_id="TASK-ARTIFACT",
        name="Artifact-producing task",
        assigned_agent="agent:test",
        owner_id="alice",
        result_artifact_id="ART-result-123",
    )

    assert task.result_artifact_id == "ART-result-123"
    assert TaskRecord.model_validate(task.model_dump()).result_artifact_id == "ART-result-123"


def test_task_visibility_never_crosses_organization_or_department_boundaries():
    tasks = TaskMaster()
    private = tasks.create_task(
        "Private", "agent:test", {}, owner_id="alice", organization_id="org-a",
        visibility="private",
    )
    organization = tasks.create_task(
        "Org", "agent:test", {}, owner_id="alice", organization_id="org-a",
        visibility="organization",
    )
    department = tasks.create_task(
        "Department", "agent:test", {}, owner_id="alice", organization_id="org-a",
        department_id="finance", visibility="department",
    )

    assert tasks.can_read(private, "alice", "org-a", "finance")
    assert not tasks.can_read(private, "bob", "org-a", "finance")
    assert tasks.can_read(organization, "bob", "org-a", "operations")
    assert not tasks.can_read(organization, "bob", "org-b", "operations")
    assert tasks.can_read(department, "bob", "org-a", "finance")
    assert not tasks.can_read(department, "bob", "org-a", "operations")
    assert not tasks.can_read(department, "bob", "org-b", "finance")

    visible_ids = {
        task.task_id
        for task in tasks.list_visible("bob", "org-a", "finance")
    }
    assert private.task_id not in visible_ids
    assert organization.task_id in visible_ids
    assert department.task_id in visible_ids


def test_task_mutations_require_same_org_owner_or_explicit_foreign_edit_right():
    tasks = TaskMaster()
    task = tasks.create_task(
        "Owned task", "agent:test", {}, owner_id="alice", organization_id="org-a"
    )

    assert tasks.can_edit(task, "alice", "org-a")
    assert not tasks.can_edit(task, "mallory", "org-a")
    assert not tasks.can_edit(task, "alice", "org-b", can_edit_foreign=True)

    with pytest.raises(PermissionError):
        tasks.cancel_authorized(
            task.task_id,
            requested_by="mallory",
            organization_id="org-a",
            can_edit_foreign=False,
        )
    assert tasks.get_task(task.task_id).state == TaskState.QUEUED

    cancelled = tasks.cancel_authorized(
        task.task_id,
        requested_by="operator",
        organization_id="org-a",
        can_edit_foreign=True,
    )
    assert cancelled.state == TaskState.CANCELLED

    with pytest.raises(PermissionError):
        tasks.delete_authorized(
            task.task_id,
            requested_by="alice",
            organization_id="org-b",
            can_edit_foreign=True,
        )
    assert tasks.get_task(task.task_id) is not None

    assert tasks.delete_authorized(
        task.task_id,
        requested_by="alice",
        organization_id="org-a",
    )


def test_template_acl_uses_verified_principal_scope_not_a_viewer_alias():
    templates = TaskTemplateRegistry()
    own = templates.create_template(
        "Alice private", owner="alice", organization_id="org-a", visibility="own"
    )
    organization = templates.create_template(
        "Org A", owner="alice", organization_id="org-a", visibility="organization"
    )
    department = templates.create_template(
        "Finance", owner="alice", organization_id="org-a", department_id="finance",
        visibility="department",
    )
    restricted = templates.create_template(
        "Auditors", owner="alice", organization_id="org-a", visibility="restricted",
        allowed_roles=["auditor"],
    )

    assert not templates.can_read(own, "mallory", "org-a", "finance", ["auditor"])
    assert templates.can_read(organization, "mallory", "org-a", "operations", [])
    assert not templates.can_read(organization, "mallory", "org-b", "operations", [])
    assert templates.can_read(department, "mallory", "org-a", "finance", [])
    assert not templates.can_read(department, "mallory", "org-a", "operations", [])
    assert templates.can_read(restricted, "mallory", "org-a", "finance", ["auditor"])
    assert not templates.can_read(restricted, "mallory", "org-a", "finance", ["member"])

    templates.remove_for_viewer(organization.template_id, "mallory")
    visible_ids = {
        template.template_id
        for template in templates.list_visible(
            requested_by="mallory",
            organization_id="org-a",
            department_id="finance",
            actor_roles=["auditor"],
        )
    }
    assert own.template_id not in visible_ids
    assert organization.template_id not in visible_ids
    assert department.template_id in visible_ids
    assert restricted.template_id in visible_ids


def test_template_raw_list_rejects_a_caller_supplied_viewer_alias():
    templates = TaskTemplateRegistry()

    with pytest.raises(TypeError):
        templates.list_all(viewer="forged-user")


def test_template_edit_acl_blocks_foreign_owner_but_allows_explicit_manager_capability():
    templates = TaskTemplateRegistry()
    template = templates.create_template(
        "Owned", owner="alice", organization_id="org-a", visibility="organization"
    )

    with pytest.raises(TemplatePermissionError):
        templates.update_authorized(
            template.template_id,
            requested_by="mallory",
            organization_id="org-a",
            name="Forged edit",
        )
    with pytest.raises(TemplatePermissionError):
        templates.update_authorized(
            template.template_id,
            requested_by="alice",
            organization_id="org-b",
            name="Cross-org owner alias",
        )

    updated = templates.update_authorized(
        template.template_id,
        requested_by="operator",
        organization_id="org-a",
        can_edit_foreign=True,
        name="Governed edit",
    )
    assert updated.name == "Governed edit"


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_ticket_resolution_requires_assigned_user_role_and_organization(decision):
    tickets = TicketMaster()
    ticket = tickets.create_approval_ticket(
        "Sensitive", "Needs finance lead", "agent:test", "tool:test", {},
        organization_id="org-a", assigned_to_user="alice", assigned_to_role="finance-lead",
    )
    resolve = tickets.approve_ticket if decision == "approve" else tickets.reject_ticket

    with pytest.raises(PermissionError):
        resolve(
            ticket.ticket_id,
            decided_by="mallory",
            decider_roles=["finance-lead"],
            decider_organization_id="org-a",
        )
    with pytest.raises(PermissionError):
        resolve(
            ticket.ticket_id,
            decided_by="alice",
            decider_roles=["member"],
            decider_organization_id="org-a",
        )
    with pytest.raises(PermissionError):
        resolve(
            ticket.ticket_id,
            decided_by="alice",
            decider_roles=["finance-lead"],
            decider_organization_id="org-b",
        )

    resolved = resolve(
        ticket.ticket_id,
        decided_by="alice",
        decider_roles=["finance-lead"],
        decider_organization_id="org-a",
    )
    expected = TicketStatus.APPROVED if decision == "approve" else TicketStatus.REJECTED
    assert resolved.status == expected
    assert resolved.resolved_by == "alice"


def test_ticket_payloads_are_private_to_workspace_or_explicit_assignment():
    tickets = TicketMaster()
    private = tickets.create_approval_ticket(
        "Private payload",
        "Contains a private email draft",
        "agent:test",
        "tool:test",
        {"email_body": "private"},
        requested_by="workspace-a",
        owner_id="workspace-a",
        organization_id="org-a",
    )
    assigned = tickets.create_approval_ticket(
        "Operator decision",
        "Requester can inspect status; only the assignee may decide",
        "agent:test",
        "tool:test",
        {"secret": "approval-only"},
        requested_by="workspace-a",
        owner_id="workspace-a",
        assigned_to_role="operator",
        organization_id="org-a",
    )

    alice = {
        ticket.ticket_id
        for ticket in tickets.list_visible(
            "workspace-a", "member:demo", "org-a", actor_roles=["member"]
        )
    }
    bob = {
        ticket.ticket_id
        for ticket in tickets.list_visible(
            "workspace-b", "member:demo", "org-a", actor_roles=["member"]
        )
    }
    operator = {
        ticket.ticket_id
        for ticket in tickets.list_visible(
            "operator-workspace", "operator", "org-a", actor_roles=["operator"]
        )
    }

    assert private.ticket_id in alice
    assert private.ticket_id not in bob
    assert assigned.ticket_id in alice
    assert assigned.ticket_id in operator
