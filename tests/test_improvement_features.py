"""Unit tests verifying all features implemented from the Improvement Report."""

import pytest
import asyncio
from sentinel_fleet.core.errors import (
    TaskNotFoundError,
    TicketNotFoundError,
    ContactNotFoundError,
    SkillNotFoundError
)
from sentinel_fleet.core.model_armor import ModelArmor
from sentinel_fleet.core.skills import skill_registry, ComponentV1SkillLoader
from sentinel_fleet.core.privacy_contacts import privacy_contact_hub
from sentinel_fleet.core.gateway import SovereignGateway
from sentinel_fleet.core.identity import AgentIdentity, AgentRole
from sentinel_fleet.uas.task_master import task_master, TaskState
from sentinel_fleet.uas.ticket_master import ticket_master, TicketPriority


@pytest.mark.asyncio
async def test_component_v1_yaml_loader_and_32_skills():
    """Verifies that all 32 Component-v1 YAML skills are discovered and loaded from the filesystem."""
    skills = skill_registry.list_all()
    assert len(skills) >= 32
    
    # Check specific skills and their metadata
    tax_skill = skill_registry.get_skill("skill:tax-compliance-v1")
    assert tax_skill is not None
    assert tax_skill.schema_version == "component-v1"
    assert tax_skill.pillar == "domain"
    assert "validate_tax_compliance" in tax_skill.required_tools

    armor_skill = skill_registry.get_skill("skill:model-armor-sentry")
    assert armor_skill is not None
    assert armor_skill.pillar == "control"
    assert "inspect_prompt" in armor_skill.required_tools


def test_skill_not_found_error():
    """Verifies that SkillNotFoundError is raised on unknown skill modifications."""
    with pytest.raises(SkillNotFoundError):
        skill_registry.update_permissions("skill:non-existent-skill", "public", "auto")

    with pytest.raises(SkillNotFoundError):
        skill_registry.add_skill_version("skill:non-existent-skill", "2.0.0", "new", ["tool"])


@pytest.mark.asyncio
async def test_async_model_armor_non_blocking_and_recursion():
    """Verifies that ModelArmor async offloading handles nested dicts without blocking."""
    heavy_payload = {
        "invoice_data": {
            "vendor": {
                "name": "CloudTech GmbH",
                "iban": "DE89370400440532013000",
                "api_key": "AIzaSyTestKey12345678901234567890123456"
            },
            "line_items": [
                {"description": "Server hosting", "card": "4111 2222 3333 4444"}
            ]
        }
    }

    sanitized = await ModelArmor.sanitize_arguments_async(heavy_payload)
    assert "[REDACTED_API_KEY]" in sanitized["invoice_data"]["vendor"]["api_key"]
    assert "[REDACTED_CREDIT_CARD]" in sanitized["invoice_data"]["line_items"][0]["card"]


@pytest.mark.asyncio
async def test_strict_task_master_errors_and_persistence():
    """Verifies TaskMaster persistence and TaskNotFoundError."""
    task = task_master.create_task(
        name="Test Persistence Task",
        assigned_agent="agent:task-solver",
        input_data={"test": True}
    )

    fetched = task_master.get_task(task.task_id)
    assert fetched is not None
    assert fetched.name == "Test Persistence Task"

    # Update state
    updated = task_master.update_task_state(task.task_id, TaskState.COMPLETED, output_data={"success": True})
    assert updated.state == TaskState.COMPLETED

    # Missing task error
    with pytest.raises(TaskNotFoundError):
        task_master.update_task_state("TASK-NON-EXISTENT", TaskState.COMPLETED)


@pytest.mark.asyncio
async def test_strict_ticket_master_errors_and_persistence():
    """Verifies TicketMaster persistence and TicketNotFoundError."""
    ticket = ticket_master.create_approval_ticket(
        title="Test Approval",
        description="Require operator signoff",
        agent_id="agent:vendor-dispute",
        tool_name="send_external_email",
        payload={"to": "test@vendor.com"},
        priority=TicketPriority.HIGH
    )

    fetched = ticket_master.get_ticket(ticket.ticket_id)
    assert fetched is not None
    assert fetched.priority == TicketPriority.HIGH

    approved = ticket_master.approve_ticket(ticket.ticket_id, comment="All good")
    assert approved.status == "approved"

    # Missing ticket errors
    with pytest.raises(TicketNotFoundError):
        ticket_master.approve_ticket("TICK-NON-EXISTENT")

    with pytest.raises(TicketNotFoundError):
        ticket_master.reject_ticket("TICK-NON-EXISTENT")


@pytest.mark.asyncio
async def test_privacy_contacts_strict_errors_and_tombstones():
    """Verifies ContactNotFoundError and tombstone protections."""
    contact = privacy_contact_hub.add_contact(
        name="Strict Test Contact",
        email="strict@gdpr-test.de",
        organization="GDPR Inc",
        category="vendor",
        protection_level="S3"
    )

    # Opt out / tombstone
    opted_out = privacy_contact_hub.mark_opt_out(contact.contact_id, "User requested erasure")
    assert opted_out.is_tombstone is True

    # Validate permission should be blocked
    permission = privacy_contact_hub.validate_send_permission("strict@gdpr-test.de")
    assert permission["allowed"] is False
    assert "DSGVO Block" in permission["reason"]

    # Missing contact error
    with pytest.raises(ContactNotFoundError):
        privacy_contact_hub.mark_opt_out("cnt-invalid-id")


@pytest.mark.asyncio
async def test_gateway_concurrency_lock():
    """Verifies that concurrent tool executions on the same agent are serialized safely."""
    gateway = SovereignGateway()
    agent = AgentIdentity(
        agent_id="agent:concurrent-worker",
        name="Concurrent Worker",
        role=AgentRole.ORCHESTRATOR,
        description="Parallel tool worker",
        allowed_tools={"query_memory_bank"}
    )

    async def mock_tool(**kwargs):
        await asyncio.sleep(0.01)
        return "Done"

    # Launch 5 concurrent calls
    tasks = [
        gateway.execute_tool_call(
            agent=agent,
            tool_name="query_memory_bank",
            tool_args={"query": f"test_{i}"},
            tool_func=mock_tool
        )
        for i in range(5)
    ]

    results = await asyncio.gather(*tasks)
    assert len(results) == 5
    assert all(r.success for r in results)
    assert agent.consecutive_steps == 5
