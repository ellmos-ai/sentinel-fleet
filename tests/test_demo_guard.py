"""Public showcase quotas and workspace-local quarantine boundaries."""

from httpx import ASGITransport, AsyncClient
import pytest

from sentinel_fleet.core.demo_guard import DemoUsageGuard, DemoUsageLimitError
from sentinel_fleet.core.config import settings
from sentinel_fleet.core.access import demo_principal
from sentinel_fleet.core.gateway import gateway
from sentinel_fleet.core.users import DEMO_USER_ID
from sentinel_fleet.web import server
from sentinel_fleet.web.server import app


def test_usage_guard_enforces_workspace_and_global_windows_and_supports_rollback():
    guard = DemoUsageGuard(
        window_seconds=10,
        workspace_write_limit=1,
        global_write_limit=2,
        workspace_external_limit=1,
        global_external_limit=2,
    )
    alice = guard.reserve("alice", "write", now=1)
    with pytest.raises(DemoUsageLimitError):
        guard.reserve("alice", "write", now=2)

    guard.release(alice)
    guard.reserve("alice", "write", now=3)
    guard.reserve("bob", "write", now=3)
    with pytest.raises(DemoUsageLimitError):
        guard.reserve("carol", "write", now=3)

    # The rolling window reopens without growing a permanent per-request ledger.
    guard.reserve("carol", "write", now=14)


@pytest.mark.asyncio
async def test_demo_injection_quarantines_only_the_originating_workspace(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(server, "_demo_usage_guard", DemoUsageGuard())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as alice:
        await alice.get("/")
        blocked = await alice.post(
            "/api/omniledger/process", data={"preset_type": "injection_attack"}
        )
        alice_fleet = {
            row["agent_id"]: row for row in (await alice.get("/api/fleet")).json()
        }

        async with AsyncClient(transport=transport, base_url="http://test") as bob:
            await bob.get("/")
            bob_fleet = {
                row["agent_id"]: row for row in (await bob.get("/api/fleet")).json()
            }

        assert blocked.status_code == 400
        assert blocked.json()["quarantine_scope"] == "current_demo_workspace"
        assert alice_fleet["agent:invoice-extractor"]["status"] == "quarantined"
        assert bob_fleet["agent:invoice-extractor"]["status"] == "idle"

        released = await alice.post(
            "/api/agents/agent:invoice-extractor/quarantine/release"
        )
        assert released.status_code == 200
        assert released.json()["scope"] == "current_demo_workspace"


@pytest.mark.asyncio
async def test_production_demo_limits_cost_routes_before_execution(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(
        server,
        "_demo_usage_guard",
        DemoUsageGuard(
            workspace_external_limit=1,
            global_external_limit=2,
            workspace_write_limit=10,
            global_write_limit=10,
        ),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/chat/send", json={"message": "first"})
        second = await client.post("/api/chat/send", json={"message": "second"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) >= 1


@pytest.mark.asyncio
async def test_public_demo_cannot_create_or_fire_persistent_automation(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "environment", "production")
    template_id = "template:public-demo-probe"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bound = await client.put(
            f"/api/task-templates/{template_id}/routine",
            data={"kind": "interval", "interval_seconds": 60},
        )
        fired = await client.post("/api/routines/fire", json={})

    assert bound.status_code == 403
    assert "disabled in the public demo" in bound.json()["detail"]
    assert fired.status_code == 200
    assert fired.json()["status"] == "disabled_in_public_demo"
    assert fired.json()["fired"] == []


@pytest.mark.asyncio
async def test_public_demo_cannot_delete_persistent_automation_bindings(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "environment", "production")
    template_id = "template:protected-demo-binding"
    routine = server.routines.routine_binding_registry.set_binding(
        template_id, {"kind": "interval", "seconds": 60}
    )
    schedule = server.routines.schedule_binding_registry.set_binding(
        template_id, due_at="2099-01-01T00:00:00+00:00"
    )
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            routine_delete = await client.delete(
                f"/api/task-templates/{template_id}/routine"
            )
            schedule_delete = await client.delete(
                f"/api/task-templates/{template_id}/schedule"
            )

        assert routine_delete.status_code == 403
        assert schedule_delete.status_code == 403
        assert server.routines.routine_binding_registry.get_for_template(template_id) == routine
        assert (
            server.routines.schedule_binding_registry.get_pending_for_template(template_id)
            == schedule
        )
    finally:
        server.routines.routine_binding_registry.remove_for_template(template_id)
        server.routines.schedule_binding_registry.remove_pending_for_template(template_id)


@pytest.mark.asyncio
async def test_demo_template_cannot_quarantine_a_shared_unscoped_agent(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(server, "_demo_usage_guard", DemoUsageGuard())
    server.lifecycle_manager.update_agent_status(
        "agent:web-reader", server.AgentStatus.IDLE
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as alice:
        rejected = await alice.post(
            "/api/task-templates",
            data={
                "name": "Unscoped agent probe",
                "assigned_agent": "agent:web-reader",
                "custom_prompt_text": "Run a normal template step.",
            },
        )
    async with AsyncClient(transport=transport, base_url="http://test") as bob:
        fleet = {row["agent_id"]: row for row in (await bob.get("/api/fleet")).json()}

    assert rejected.status_code == 422
    assert "cannot execute templates" in rejected.json()["detail"]
    assert fleet["agent:web-reader"]["status"] == "idle"


@pytest.mark.asyncio
async def test_ask_gate_does_not_set_shared_agent_waiting_status():
    agent = server.lifecycle_manager.get_agent("agent:vendor-dispute")
    assert agent is not None
    server.lifecycle_manager.update_agent_status(agent.agent_id, server.AgentStatus.IDLE)

    async def must_not_run(**_kwargs):
        raise AssertionError("ASK-gated tool body ran")

    result = await gateway.execute_tool_call(
        agent,
        "send_external_email",
        {"to": "synthetic@example.test", "body": "Synthetic demo"},
        must_not_run,
        principal=demo_principal(DEMO_USER_ID, "b" * 32),
    )

    assert result.requires_approval is True
    assert agent.status is server.AgentStatus.IDLE
