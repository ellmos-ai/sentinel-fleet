"""Unit tests for interactive Control Center features (Tickets, Tasks, Memory, Prompts, Skills, Domains, Contacts)."""

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
        # Honest state: the endpoint queues work, it does not execute it
        assert data["task"]["state"] == "queued"
        assert data["task"]["output_data"] == {}


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


@pytest.mark.asyncio
async def test_prompt_version_bump_and_permissions():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Bump version
        res_bump = await ac.post("/api/prompts/prompt:invoice-vision-multimodal/version", data={
            "new_version_number": "1.3.0",
            "new_text": "Aktualisierter Vision Prompt für 2026",
            "change_summary": "Added support for electronic e-invoice formats"
        })
        assert res_bump.status_code == 200
        data_bump = res_bump.json()
        assert data_bump["prompt"]["active_version"] == "1.3.0"

        # Update permissions
        res_perm = await ac.post("/api/prompts/prompt:invoice-vision-multimodal/permissions", data={
            "visibility": "public",
            "requires_approval": "true"
        })
        assert res_perm.status_code == 200
        data_perm = res_perm.json()
        assert data_perm["prompt"]["visibility"] == "public"
        assert data_perm["prompt"]["requires_approval"] is True


@pytest.mark.asyncio
async def test_get_domains():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/domains")
        assert res.status_code == 200
        domains = res.json()
        assert len(domains) >= 4


@pytest.mark.asyncio
async def test_privacy_contacts_crud_and_opt_out():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Create contact
        res_create = await ac.post("/api/contacts/create", data={
            "name": "Datenschutz Testkontakt",
            "email": "privacy-test@partner.eu",
            "organization": "Test Partner Org",
            "category": "vendor",
            "protection_level": "S3"
        })
        assert res_create.status_code == 200
        contact = res_create.json()["contact"]
        contact_id = contact["contact_id"]
        assert contact["protection_level"] == "S3"

        # 2. Opt-out
        res_optout = await ac.post(f"/api/contacts/{contact_id}/opt-out", data={"reason": "User revoked consent"})
        assert res_optout.status_code == 200
        assert res_optout.json()["contact"]["is_tombstone"] is True

        # 3. DSGVO Audit
        res_audit = await ac.get("/api/contacts/dsgvo-audit")
        assert res_audit.status_code == 200
        assert res_audit.json()["status"] == "COMPLIANT"
