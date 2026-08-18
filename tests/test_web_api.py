"""Unit tests for FastAPI Endpoints & UI Rendering."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sentinel_fleet.web.server import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["app"] == "SentinelFleet"


@pytest.mark.asyncio
async def test_blueprint_renders_html():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/blueprint")
        assert response.status_code == 200
        assert "Architecture &amp; Circuit Blueprint" in response.text or "Architecture & Circuit Blueprint" in response.text

        # The old German route must keep working for existing links and recordings
        legacy = await ac.get("/schaltplan")
        assert legacy.status_code == 307
        assert legacy.headers["location"] == "/blueprint"


@pytest.mark.asyncio
async def test_omniledger_process_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/omniledger/process", data={"preset_type": "valid"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["invoice"]["status"] == "booked"
        # The demo runs without an API key, and the response must say so rather than
        # implying a live model call
        assert data["extraction_mode"] in ("gemini-3.5", "deterministic-demo")
        assert data["extraction_mode"] == data["invoice"]["extraction_mode"]


@pytest.mark.asyncio
async def test_ticket_create_and_approve(client):
    created = await client.post("/api/tickets/create", data={
        "title": "Release vendor payment",
        "description": "Operator signoff for a held payment run.",
        "agent_id": "agent:vendor-dispute",
        "priority": "critical"
    })
    assert created.status_code == 200
    ticket = created.json()["ticket"]
    assert ticket["status"] == "pending_approval"
    assert ticket["priority"] == "critical"
    assert ticket["ticket_id"].startswith("TICK-")

    approved = await client.post(f"/api/tickets/{ticket['ticket_id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["ticket"]["status"] == "approved"

    # Re-resolving a settled ticket is a conflict, not a silent second approval
    again = await client.post(f"/api/tickets/{ticket['ticket_id']}/approve")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_contact_create(client):
    response = await client.post("/api/contacts/create", data={
        "name": "Accounts Payable, Northwind Ltd",
        "email": "ap@northwind.example",
        "organization": "Northwind Ltd",
        "category": "vendor",
        "protection_level": "S2"
    })
    assert response.status_code == 200
    contact = response.json()["contact"]
    assert contact["protection_level"] == "S2"
    assert contact["opt_in_status"] == "confirmed"
    assert contact["is_tombstone"] is False


@pytest.mark.asyncio
async def test_prompt_create_and_version(client):
    created = await client.post("/api/prompts/create", data={
        "title": "Ledger Reconciliation Prompt",
        "purpose": "Match booked invoices against bank statements.",
        "category": "finance",
        "text": "Reconcile invoice {{invoice_number}} against the statement lines.",
        "visibility": "organization"
    })
    assert created.status_code == 200
    prompt = created.json()["prompt"]
    prompt_id = prompt["id"]
    assert prompt["active_version"]

    bumped = await client.post(f"/api/prompts/{prompt_id}/version", data={
        "new_version_number": "2.0.0",
        "new_text": "Reconcile invoice {{invoice_number}} and flag partial payments.",
        "change_summary": "Handle partial payments"
    })
    assert bumped.status_code == 200
    updated = bumped.json()["prompt"]
    assert updated["active_version"] == "2.0.0"
    assert len(updated["versions"]) > len(prompt["versions"])


@pytest.mark.asyncio
async def test_skills_listing(client):
    response = await client.get("/api/skills")
    assert response.status_code == 200
    skills = response.json()
    assert len(skills) >= 32
    assert all({"skill_id", "name", "pillar", "required_tools"} <= set(s) for s in skills)


@pytest.mark.asyncio
async def test_task_create_is_queued_not_executed(client):
    response = await client.post("/api/tasks/create", data={
        "name": "Reconcile August statements",
        "assigned_agent": "agent:task-solver",
        "input_payload": '{"month": "2026-08"}'
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["note"] == "queued for execution"
    task = payload["task"]
    assert task["state"] == "queued"
    assert task["output_data"] == {}
    assert task["input_data"] == {"month": "2026-08"}


@pytest.mark.asyncio
async def test_quarantine_release_after_model_armor_block(client):
    """Model Armor quarantines the extractor; the operator endpoint must free it again."""
    agent_id = "agent:invoice-extractor"
    try:
        blocked = await client.post("/api/omniledger/process", data={"preset_type": "injection_attack"})
        assert blocked.status_code == 400
        assert blocked.json()["status"] == "BLOCKED_BY_MODEL_ARMOR"
        assert blocked.json()["scenario"] == "predefined-demo-attack"

        fleet = {a["agent_id"]: a for a in (await client.get("/api/fleet")).json()}
        assert fleet[agent_id]["status"] == "quarantined"
        assert fleet[agent_id]["quarantine_reason"]
    finally:
        released = await client.post(f"/api/agents/{agent_id}/quarantine/release")
        assert released.status_code == 200
        assert released.json()["agent"]["status"] == "idle"


@pytest.mark.asyncio
async def test_telemetry_status_reports_real_exporter(client):
    await client.post("/api/omniledger/process", data={"preset_type": "valid"})
    response = await client.get("/api/telemetry/status")
    assert response.status_code == 200
    status = response.json()
    assert status["otel_enabled"] is True
    assert status["exported_span_count"] >= 1
    # Mi2: the dashboard buffer is bounded
    assert status["retained_span_records"] <= status["retention_limit"] == 500
