"""Unit tests for the pre-model privacy screen and the active-span binding it reports through."""

import pytest

from sentinel_fleet.core.gateway import SovereignGateway
from sentinel_fleet.core.identity import AgentIdentity, AgentRole
from sentinel_fleet.core.privacy_screen import ScreenLevel, screen_text
from sentinel_fleet.core.telemetry import telemetry


def test_red_patterns_dominate_the_verdict():
    verdict = screen_text("Please wire it to DE89 3704 0044 0532 0130 00, contact a@b.example")

    assert verdict.level is ScreenLevel.RED
    patterns = {finding.pattern for finding in verdict.findings}
    assert "iban" in patterns
    # An amber hit alongside a red one is still reported, it just does not set the verdict
    assert "email address" in patterns


def test_amber_alone_stays_amber():
    verdict = screen_text("Questions to billing@vendor.example, Tel: +49 30 12345678")

    assert verdict.level is ScreenLevel.AMBER
    assert {f.pattern for f in verdict.findings} == {"email address", "phone number"}


def test_clean_text_is_green_and_reports_what_it_read():
    verdict = screen_text("Development server cluster node A, quantity 1, 2500.00")

    assert verdict.level is ScreenLevel.GREEN
    assert verdict.findings == []
    assert verdict.screened_chars > 0


def test_empty_input_is_unscreened_not_green():
    """"Found nothing" and "could not look" must not collapse into the same verdict."""
    verdict = screen_text("", unscreened_reason="scanned PDF without a text layer")

    assert verdict.level is ScreenLevel.UNSCREENED
    assert "scanned PDF" in verdict.reason
    assert "unscreened" in verdict.summary()


def test_findings_are_masked_so_the_report_does_not_leak():
    secret = "sk-abcdefghijklmnopqrstuvwxyz012345"
    verdict = screen_text(f"api key: {secret}")

    assert verdict.level is ScreenLevel.RED
    rendered = verdict.summary() + str(verdict.as_span_payload()) + str(verdict.findings)
    assert secret not in rendered
    assert all(secret not in sample for f in verdict.findings for sample in f.samples)


def test_span_payload_is_primitive_for_the_exporter():
    payload = screen_text("billing@vendor.example").as_span_payload()

    assert payload["verdict"] == "amber"
    assert all(isinstance(value, (str, int, float, bool)) for value in payload.values())


@pytest.mark.asyncio
async def test_gateway_binds_the_active_span_for_the_tool_body():
    """A tool body must be able to write evidence onto the row of the call it runs under."""
    gateway = SovereignGateway()
    agent = AgentIdentity(
        agent_id="agent:span-probe",
        name="Span Probe",
        role=AgentRole.ORCHESTRATOR,
        description="Records an event from inside a tool body.",
        allowed_tools={"query_memory_bank"},
    )

    async def tool(**_kwargs):
        return telemetry.record_on_active_span("privacy_screen", {"verdict": "green"})

    result = await gateway.execute_tool_call(agent, "query_memory_bank", {}, tool)

    assert result.success is True
    assert result.output is True, "the tool body saw no active span"
    span = next(s for s in telemetry.get_recent_spans(20) if s.name == "tool_call:query_memory_bank")
    assert any(event["name"] == "privacy_screen" for event in span.events)


@pytest.mark.asyncio
async def test_active_span_is_released_after_the_call():
    """A leaked binding would file the next call's evidence under the previous call's row."""
    gateway = SovereignGateway()
    agent = AgentIdentity(
        agent_id="agent:span-probe-2",
        name="Span Probe 2",
        role=AgentRole.ORCHESTRATOR,
        description="Checks that the binding does not outlive the call.",
        allowed_tools={"query_memory_bank"},
    )

    async def tool(**_kwargs):
        return "done"

    await gateway.execute_tool_call(agent, "query_memory_bank", {}, tool)

    assert telemetry.record_on_active_span("stray_event") is False


@pytest.mark.asyncio
async def test_active_span_is_released_even_when_the_tool_raises():
    gateway = SovereignGateway()
    agent = AgentIdentity(
        agent_id="agent:span-probe-3",
        name="Span Probe 3",
        role=AgentRole.ORCHESTRATOR,
        description="Checks the finally path of the binding.",
        allowed_tools={"query_memory_bank"},
    )

    async def failing_tool(**_kwargs):
        raise RuntimeError("tool exploded")

    result = await gateway.execute_tool_call(agent, "query_memory_bank", {}, failing_tool)

    assert result.success is False
    assert telemetry.record_on_active_span("stray_event") is False
