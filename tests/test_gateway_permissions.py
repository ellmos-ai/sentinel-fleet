"""Unit tests for Gateway Permissions & Zero-Trust Interceptor."""

import pytest
from sentinel_fleet.core.identity import AgentIdentity, AgentRole, AgentStatus
from sentinel_fleet.core.gateway import SovereignGateway
from sentinel_fleet.core.errors import SecurityViolationError, QuarantineLockError


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
    with pytest.raises(SecurityViolationError) as excinfo:
        await gateway.execute_tool_call(
            agent=agent,
            tool_name="unauthorized_system_shell",
            tool_args={},
            tool_func=mock_forbidden_tool
        )

    assert agent.status == AgentStatus.QUARANTINED
    assert "Security Violation" in excinfo.value.message
    assert excinfo.value.details["tool_name"] == "unauthorized_system_shell"


@pytest.mark.asyncio
async def test_gateway_denies_forbidden_tool_by_permission_registry():
    """A scoped tool can still be denied by policy; that verdict must raise, not return."""
    gateway = SovereignGateway()
    agent = AgentIdentity(
        agent_id="test:overreaching-agent",
        name="Overreaching Worker",
        role=AgentRole.ORCHESTRATOR,
        description="Scoped for a tool that policy forbids outright",
        allowed_tools={"bash_rm_rf"}
    )

    async def mock_destructive_tool(**kwargs):
        return "Deleted"

    with pytest.raises(SecurityViolationError) as excinfo:
        await gateway.execute_tool_call(
            agent=agent,
            tool_name="bash_rm_rf",
            tool_args={},
            tool_func=mock_destructive_tool
        )

    assert "denied by the permission registry" in excinfo.value.details["reason"]


@pytest.mark.asyncio
async def test_gateway_locks_quarantined_agent():
    """A quarantined agent stays locked out even for tools it is scoped for."""
    gateway = SovereignGateway()
    agent = AgentIdentity(
        agent_id="test:quarantined-agent",
        name="Quarantined Worker",
        role=AgentRole.FINANCE_TASKMASTER,
        description="Already quarantined",
        allowed_tools={"query_memory_bank"},
        status=AgentStatus.QUARANTINED,
        quarantine_reason="Model Armor Alert"
    )

    async def mock_tool(**kwargs):
        return "Executed"

    with pytest.raises(QuarantineLockError):
        await gateway.execute_tool_call(
            agent=agent,
            tool_name="query_memory_bank",
            tool_args={},
            tool_func=mock_tool
        )


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
