"""Unit tests for interactive Control Center features (Tickets, Tasks, Memory, Prompts)."""

import pytest
from httpx import AsyncClient, ASGITransport
from sentinel_fleet.web.server import app


@pytest.mark.asyncio
async def test_create_custom_ticket():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/tickets/create", data={
            "title": "Vendor Bank Account Change",
            "description": "Lieferant Acme bittet um Aktualisierung der IBAN.",
            "agent_id": "agent:vendor-dispute",
            "priority": "high"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert data["ticket"]["title"] == "Vendor Bank Account Change"


@pytest.mark.asyncio
async def test_create_custom_task():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/tasks/create", data={
            "name": "Audit Corporate Policies",
            "assigned_agent": "agent:system-auditor",
            "input_payload": '{"scope": "all"}'
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert data["task"]["state"] == "completed"


@pytest.mark.asyncio
async def test_create_custom_memory():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/memory/create", data={
            "category": "lesson",
            "key": "lesson:vendor_discount",
            "content": "Lieferant gewährt 3% Skonto bei Zahlung binnen 7 Tagen."
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert "Skonto" in data["entry"]["content"]
