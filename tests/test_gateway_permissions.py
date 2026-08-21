"""Unit tests for Gateway Permissions & Zero-Trust Interceptor."""

import pytest
from sentinel_fleet.core.identity import AgentIdentity, AgentRole, AgentStatus
from sentinel_fleet.core.gateway import SovereignGateway
from sentinel_fleet.core.permissions import PermissionAction, PermissionRegistry, PermissionRule
from sentinel_fleet.core.errors import SecurityViolationError, QuarantineLockError
from sentinel_fleet.conductor.lifecycle import LifecycleManager


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
async def test_gateway_triggers_scoped_hitl_without_mutating_shared_agent_status():
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
    assert agent.status == AgentStatus.IDLE


@pytest.mark.asyncio
async def test_gateway_uses_an_injected_permission_registry_and_unknown_tools_fail_closed():
    registry = PermissionRegistry(rules=[
        PermissionRule(
            tool_pattern="custom_tool",
            action=PermissionAction.ALLOW,
            reason="Explicit test grant",
        )
    ])
    service = SovereignGateway(permission_registry=registry)
    agent = AgentIdentity(
        agent_id="test:injected-registry",
        name="Injected registry",
        role=AgentRole.ORCHESTRATOR,
        description="Tests real gateway dependency injection",
        allowed_tools={"custom_tool", "unknown_tool"},
    )

    async def tool(**kwargs):
        return "ran"

    assert (await service.execute_tool_call(agent, "custom_tool", {}, tool)).output == "ran"
    with pytest.raises(SecurityViolationError):
        await service.execute_tool_call(agent, "unknown_tool", {}, tool)


def test_every_seed_identity_tool_has_an_explicit_permission_rule():
    registry = PermissionRegistry()
    scoped_tools = {
        tool
        for identity in LifecycleManager().list_fleet()
        for tool in identity.allowed_tools
        if tool != "*"
    }

    missing = sorted(tool for tool in scoped_tools if registry.explain(tool).source != "rule")
    assert not missing, f"seeded tools without explicit permission rules: {missing}"
