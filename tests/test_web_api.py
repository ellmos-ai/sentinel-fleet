"""Unit tests for FastAPI Endpoints & UI Rendering."""

import pytest
from httpx import AsyncClient, ASGITransport
from sentinel_fleet.web.server import app


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
async def test_schaltplan_renders_html():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/schaltplan")
        assert response.status_code == 200
        assert "Architecture &amp; Circuit Blueprint" in response.text or "Architecture & Circuit Blueprint" in response.text


@pytest.mark.asyncio
async def test_omniledger_process_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/omniledger/process", data={"preset_type": "valid"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["invoice"]["status"] == "booked"
