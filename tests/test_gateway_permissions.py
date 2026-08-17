"""Unit tests for Gateway Permissions & Zero-Trust Interceptor."""

import pytest
from sentinel_fleet.core.identity import AgentIdentity, AgentRole, AgentStatus
from sentinel_fleet.core.gateway import SovereignGateway


@pytest.mark.asyncio
async def test_gateway_enforces_tool_scoping():
    gateway = SovereignGateway()
    agent = AgentIdentity(
        agent_id="test:restricted-agent",
        name="Restricted Worker",
        role=AgentRole.COMPLIANCE_AUDITOR,
        description="Can only validate compliance",
        allowed_tools={"validate_tax_compliance"}
    )

    async def mock_forbidden_tool(**kwargs):
        return "Executed"

    # Attempt calling an unauthorized tool
    result = await gateway.execute_tool_call(
        agent=agent,
        tool_name="unauthorized_system_shell",
        tool_args={},
        tool_func=mock_forbidden_tool
    )

    assert result.success is False
    assert agent.status == AgentStatus.QUARANTINED
    assert "Security Violation" in result.error


@pytest.mark.asyncio
async def test_gateway_triggers_hitl_approval_for_ask_permission():
    gateway = SovereignGateway()
    agent = AgentIdentity(
        agent_id="test:comm-agent",
        name="Communicator",
        role=AgentRole.VENDOR_COMMUNICATOR,
        description="Sends emails with HITL gate",
        allowed_tools={"send_external_email"}
    )

    async def mock_email_tool(**kwargs):
        return "Email Sent"

    result = await gateway.execute_tool_call(
        agent=agent,
        tool_name="send_external_email",
        tool_args={"to": "vendor@example.com", "body": "Correction needed"},
        tool_func=mock_email_tool
    )

    assert result.success is True
    assert result.requires_approval is True
    assert agent.status == AgentStatus.WAITING_APPROVAL
