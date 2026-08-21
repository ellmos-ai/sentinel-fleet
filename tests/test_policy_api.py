"""HTTP boundaries for the public authorization demo."""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sentinel_fleet.core.config import settings
from sentinel_fleet.uas.task_templates import task_template_registry
from sentinel_fleet.web.server import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _title(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_user_alias_cannot_impersonate_another_profile(client):
    response = await client.get("/?user=viewer:judge")

    assert response.status_code == 200
    board = (await client.get("/api/governance/board?user=viewer:judge")).json()
    assert board["binding_matrix"]["actor"]["user_id"] == "member:demo"


@pytest.mark.asyncio
async def test_policy_create_is_pinned_to_demo_member_and_cannot_claim_enforcement(client):
    response = await client.post("/api/policies", data={
        "user_id": "admin:lukas",  # ignored display claim, never a mutation principal
        "title": _title("Pinned"),
        "statement": "Keep this advisory.",
        "policy_type": "preference",
        "enforcement": "advisory",
    })

    assert response.status_code == 200
    policy = response.json()["policy"]
    access = (await client.get("/api/access/me")).json()
    assert policy["owner"] == access["share_id"]
    assert policy["enforcement"] == "advisory"
    assert policy["enforced_by"] == "not-enforced (user declaration)"

    dishonest = await client.post("/api/policies", data={
        "title": _title("Dishonest"),
        "statement": "Pretend this is enforced.",
        "policy_type": "rule",
        "enforcement": "enforcing",
    })
    assert dishonest.status_code == 422


@pytest.mark.asyncio
async def test_org_binding_forwards_and_cannot_be_decided_in_public_demo(client):
    created = (await client.post("/api/policies", data={
        "title": _title("Forward"),
        "statement": "Request a wider scope.",
        "policy_type": "preference",
    })).json()["policy"]
    response = await client.post(f"/api/policies/{created['policy_id']}/bindings", data={
        "user_id": "admin:lukas",
        "target_kind": "agent",
        "target_id": "agent:orchestrator",
        "scope_level": "organization",
    })

    assert response.status_code == 200
    binding = response.json()["binding"]
    access = (await client.get("/api/access/me")).json()
    assert binding["bound_by"] == access["share_id"]
    assert binding["state"] == "pending_forward"
    assert binding["forwarded_ticket_id"]
    tickets = (await client.get("/api/tickets")).json()
    assert binding["forwarded_ticket_id"] in {row["ticket_id"] for row in tickets}
    board = (await client.get("/")).text
    assert binding["binding_id"] in board
    assert binding["forwarded_ticket_id"] in board
    assert "&rarr; administrator" in board
    assert (await client.post(f"/api/tickets/{binding['forwarded_ticket_id']}/approve")).status_code == 403
    assert (await client.post(f"/api/tickets/{binding['forwarded_ticket_id']}/reject")).status_code == 403


@pytest.mark.asyncio
async def test_template_owner_and_other_user_are_resolved_server_side(client):
    created = (await client.post("/api/policies", data={
        "title": _title("Ownership"),
        "statement": "Do not trust client ownership claims.",
        "policy_type": "preference",
    })).json()["policy"]
    foreign = task_template_registry.create_template(
        name=_title("Foreign template"),
        owner="operator",
        prompt_source="custom",
        custom_prompt_text="Run a bounded test.",
    ).model_dump()

    response = await client.post(f"/api/policies/{created['policy_id']}/bindings", data={
        "target_kind": "template",
        "target_id": foreign["template_id"],
        "target_owner": "member:demo",  # ignored; server reads the template registry
        "scope_level": "user",
    })
    assert response.status_code == 404

    access = (await client.get("/api/access/me")).json()
    owned = task_template_registry.create_template(
        name=_title("Owned template"),
        owner=access["share_id"],
        organization_id=access["organization_id"],
        prompt_source="custom",
        custom_prompt_text="Run a bounded test.",
    )
    own_response = await client.post(
        f"/api/policies/{created['policy_id']}/bindings",
        data={
            "target_kind": "template",
            "target_id": owned.template_id,
            "target_owner": "operator",
            "scope_level": "user",
        },
    )
    assert own_response.status_code == 200
    assert own_response.json()["binding"]["state"] == "active"

    unknown = await client.post(f"/api/policies/{created['policy_id']}/bindings", data={
        "target_kind": "agent",
        "target_id": "agent:orchestrator",
        "scope_level": "other_user",
        "target_user_id": "not-registered",
    })
    assert unknown.status_code == 404

    routed = await client.post(f"/api/policies/{created['policy_id']}/bindings", data={
        "target_kind": "agent",
        "target_id": "agent:orchestrator",
        "scope_level": "other_user",
        "target_user_id": "operator",
    })
    assert routed.status_code == 200
    routed_binding = routed.json()["binding"]
    assert routed_binding["forwarded_ticket_id"] in {
        row["ticket_id"] for row in (await client.get("/api/tickets")).json()
    }


@pytest.mark.asyncio
async def test_binding_targets_and_scope_metadata_are_validated_server_side(client):
    created = (await client.post("/api/policies", data={
        "title": _title("Validate targets"),
        "statement": "Only registered targets may be named.",
        "policy_type": "preference",
    })).json()["policy"]
    endpoint = f"/api/policies/{created['policy_id']}/bindings"

    assert (await client.post(endpoint, data={
        "target_kind": "process", "target_id": "process:missing", "scope_level": "user",
    })).status_code == 422
    assert (await client.post(endpoint, data={
        "target_kind": "agent", "target_id": "agent:missing", "scope_level": "user",
    })).status_code == 404
    assert (await client.post(endpoint, data={
        "target_kind": "agent", "target_id": "agent:orchestrator", "scope_level": "user",
        "target_user_id": "operator",
    })).status_code == 422
    assert (await client.post(endpoint, data={
        "target_kind": "agent", "target_id": "agent:orchestrator", "scope_level": "department",
    })).status_code == 422
    department = await client.post(endpoint, data={
        "target_kind": "agent",
        "target_id": "agent:orchestrator",
        "scope_level": "department",
        "target_department_id": "finance",
    })
    assert department.status_code == 200
    department_binding = department.json()["binding"]
    assert department_binding["target_department_id"] == "finance"
    assert department_binding["forwarded_ticket_id"] in {
        row["ticket_id"] for row in (await client.get("/api/tickets")).json()
    }


@pytest.mark.asyncio
async def test_own_binding_is_visible_and_repeated_removal_is_a_conflict(client):
    created = (await client.post("/api/policies", data={
        "title": _title("Visible binding"),
        "statement": "Show active state after reload.",
        "policy_type": "preference",
    })).json()["policy"]
    binding = (await client.post(
        f"/api/policies/{created['policy_id']}/bindings",
        data={
            "target_kind": "agent",
            "target_id": "agent:orchestrator",
            "scope_level": "user",
        },
    )).json()["binding"]
    assert binding["state"] == "active"
    assert binding["binding_id"] in (await client.get("/")).text

    removed = await client.delete(f"/api/policy-bindings/{binding['binding_id']}")
    assert removed.status_code == 200
    repeated = await client.delete(f"/api/policy-bindings/{binding['binding_id']}")
    assert repeated.status_code == 409
    assert "already removed" in repeated.json()["detail"]


@pytest.mark.asyncio
async def test_permission_root_is_locked_even_when_admin_is_claimed(client):
    response = await client.put("/api/governance/permissions/bash_rm_rf", data={
        "action": "allow",
        "user_id": "admin:lukas",
    })
    assert response.status_code == 403
    assert "locked" in response.json()["detail"]


@pytest.mark.asyncio
async def test_non_demo_mutation_fails_closed_without_authenticated_principal(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    response = await client.post(
        "/api/policies",
        headers={"Origin": "http://test"},
        data={
            "title": _title("No principal"),
            "statement": "Must not be written.",
            "policy_type": "preference",
        },
    )
    assert response.status_code == 403
    assert "Authenticated deployment access is not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_policy_forward_decision_stays_locked_outside_demo_mode(client, monkeypatch):
    created = (await client.post("/api/policies", data={
        "title": _title("Always locked"),
        "statement": "Forwarding needs a verified administrator.",
        "policy_type": "preference",
    })).json()["policy"]
    forwarded = (await client.post(
        f"/api/policies/{created['policy_id']}/bindings",
        data={
            "target_kind": "agent",
            "target_id": "agent:orchestrator",
            "scope_level": "organization",
        },
    )).json()["binding"]
    monkeypatch.setattr(settings, "demo_mode", False)

    ticket_id = forwarded["forwarded_ticket_id"]
    assert (await client.post(f"/api/tickets/{ticket_id}/approve")).status_code == 403
    assert (await client.post(f"/api/tickets/{ticket_id}/reject")).status_code == 403
