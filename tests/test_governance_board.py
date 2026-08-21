"""The governance board: one read federation over the registers this fleet already keeps.

Every aggregation is exercised against a register built inside the test, never against the
module singletons. That is not only isolation hygiene: the fleet, the span buffer and the ticket
store are shared and mutated by the rest of the suite (the injection test quarantines the
extractor, every gateway test appends spans), so assertions on absolute counts read from the
singletons would pass or fail depending on test order. `build_board()` is the one function that
touches them, and it is checked for shape rather than for numbers.
"""

import json
import time
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sentinel_fleet.chat.backends import MODEL_USAGE_EVENT
from sentinel_fleet.core.identity import AgentIdentity, AgentRole, AgentStatus
from sentinel_fleet.core.permissions import PermissionAction, PermissionRegistry
from sentinel_fleet.core.policies import (
    MATH_TOLERANCE_EUR,
    UST_REQUIRED_FIELDS,
    PolicyEngine,
)
from sentinel_fleet.core.telemetry import SpanRecord
from sentinel_fleet.uas.task_templates import MAX_STEPS, Step, TaskTemplate
from sentinel_fleet.uas.ticket_master import Ticket, TicketPriority, TicketStatus
from sentinel_fleet.web import governance
from sentinel_fleet.web.server import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _agent(agent_id, tools, status=AgentStatus.IDLE, reason="", name=None):
    return AgentIdentity(
        agent_id=agent_id,
        name=name or agent_id.split(":")[-1],
        role=AgentRole.ORCHESTRATOR,
        description="synthetic test identity",
        allowed_tools=set(tools),
        status=status,
        quarantine_reason=reason
    )


def _span(name, agent_id, status="OK", tool=None, at=None, events=None, error=None):
    started = at if at is not None else time.time()
    return SpanRecord(
        span_id=f"span-{name}-{agent_id}",
        trace_id="trace-test",
        name=name,
        agent_id=agent_id,
        start_time=started,
        end_time=started + 0.25,
        attributes={"tool": tool} if tool else {},
        events=events or [],
        status=status,
        error_message=error
    )


# ---------------------------------------------------------------------------
# Policies & scopes
# ---------------------------------------------------------------------------

def test_policy_catalogue_reports_the_enforced_schema_and_engine_thresholds():
    """The board must not restate a limit in its own words - it imports the constants the
    policy engine evaluates against, so a changed threshold cannot leave a stale board behind."""
    catalogue = governance.policy_catalogue()
    summaries = " ".join(entry["summary"] for entry in catalogue)

    assert f"{MATH_TOLERANCE_EUR:.2f}" in summaries
    assert str(MAX_STEPS) in summaries
    ust = next(entry for entry in catalogue if "UStG" in entry["name"])
    assert len(ust["checks"]) == len(UST_REQUIRED_FIELDS)
    assert {check["field"] for check in ust["checks"]} == {field for field, _ in UST_REQUIRED_FIELDS}


def test_the_listed_tolerance_is_the_one_the_engine_actually_applies():
    """A board number is only worth showing if the engine behaves the way it claims: a gap just
    inside the stated tolerance passes, a gap just outside it blocks."""
    within = PolicyEngine.evaluate_tax_compliance({
        "vendor_name": "Acme", "vendor_vat_id": "DE1", "invoice_number": "1", "invoice_date": "2026-01-01",
        "delivery_date": "2026-01-01", "net_amount": 100.0, "tax_rate": 19.0,
        "gross_amount": 119.0 + MATH_TOLERANCE_EUR
    })
    beyond = PolicyEngine.evaluate_tax_compliance({
        "vendor_name": "Acme", "vendor_vat_id": "DE1", "invoice_number": "1", "invoice_date": "2026-01-01",
        "delivery_date": "2026-01-01", "net_amount": 100.0, "tax_rate": 19.0,
        "gross_amount": 119.0 + MATH_TOLERANCE_EUR + 0.01
    })
    assert within.decision.value == "pass"
    assert beyond.decision.value == "block"


def test_permission_matrix_separates_scope_from_registry_verdict():
    agents = [
        _agent("agent:alpha", {"extract_invoice_multimodal", "send_external_email"}),
        _agent("agent:beta", {"extract_invoice_multimodal"}),
    ]
    matrix = governance.permission_matrix(agents, PermissionRegistry())
    rows = {row["tool"]: row for row in matrix["rows"]}

    # An ASK tool one identity carries: granted, and held at the gate when called.
    assert rows["send_external_email"]["action"] == PermissionAction.ASK.value
    assert rows["send_external_email"]["holders"] == ["agent:alpha"]
    beta_cell = next(c for c in rows["send_external_email"]["cells"] if c["agent_id"] == "agent:beta")
    assert beta_cell["granted"] is False
    assert beta_cell["state"] == "out_of_scope"

    # A DENY rule for a tool nobody carries is defence in depth, and is labelled as unheld
    # rather than silently rendering as an empty row.
    assert rows["bash_rm_rf"]["action"] == PermissionAction.DENY.value
    assert rows["bash_rm_rf"]["unheld"] is True

    assert matrix["summary"]["held_at_gate"] == 1
    assert matrix["summary"]["grants"] == 3


def test_every_seeded_tool_has_an_explicit_rule_and_registry_has_no_fail_open_cells():
    """A new tool must receive a reviewed rule instead of inheriting an ALLOW fall-through."""
    agents = [_agent("agent:alpha", {"dispatch_swarm", "extract_invoice_multimodal"})]
    matrix = governance.permission_matrix(agents, PermissionRegistry())
    rows = {row["tool"]: row for row in matrix["rows"]}

    assert rows["dispatch_swarm"]["source"] == "rule"
    assert rows["dispatch_swarm"]["action"] == PermissionAction.ALLOW.value
    assert rows["extract_invoice_multimodal"]["source"] == "rule"
    assert matrix["summary"]["on_default"] == 0


def test_matrix_verdict_never_disagrees_with_the_gateway_s_own_evaluation():
    registry = PermissionRegistry()
    agents = [_agent("agent:alpha", {"send_external_email", "execute_template", "dispatch_swarm"})]
    for row in governance.permission_matrix(agents, registry)["rows"]:
        assert row["action"] == registry.evaluate(row["tool"]).value


def test_identical_race_lanes_collapse_into_one_matrix_row():
    agents = [
        _agent("agent:orchestrator", {"query_memory_bank"}),
        _agent("agent:race-lane-1", {"chat_completion"}),
        _agent("agent:race-lane-2", {"chat_completion"}),
    ]
    matrix = governance.permission_matrix(agents, PermissionRegistry())
    assert matrix["summary"]["columns"] == 2
    lane_column = matrix["identities"][1]
    assert lane_column["collapsed"] is True
    assert lane_column["members"] == ["agent:race-lane-1", "agent:race-lane-2"]


def test_a_quarantined_race_lane_gets_its_own_row_again():
    """Collapsing is a readability device, never a way to average away a difference."""
    agents = [
        _agent("agent:race-lane-1", {"chat_completion"}),
        _agent("agent:race-lane-2", {"chat_completion"}, status=AgentStatus.QUARANTINED, reason="test"),
    ]
    matrix = governance.permission_matrix(agents, PermissionRegistry())
    assert matrix["summary"]["columns"] == 2
    assert [i["collapsed"] for i in matrix["identities"]] == [False, False]


# ---------------------------------------------------------------------------
# Decisions & evidence
# ---------------------------------------------------------------------------

def test_decisions_are_grouped_by_verdict_agent_and_tool():
    spans = [
        _span("tool_call:chat_completion", "agent:chat-operator", tool="chat_completion"),
        _span("tool_call:chat_completion", "agent:chat-operator", tool="chat_completion"),
        _span("tool_call:send_external_email", "agent:vendor-dispute", status="WAITING_FOR_USER_APPROVAL",
              tool="send_external_email"),
        _span("tool_call:bash_rm_rf", "agent:rogue", status="SECURITY_VIOLATION", tool="bash_rm_rf",
              error="outside scope"),
        _span("queue_task:manual", "agent:task-solver"),
    ]
    decisions = governance.aggregate_decisions(spans)

    assert decisions["total"] == 5
    assert decisions["by_verdict"] == {"passed": 3, "held": 1, "refused": 1, "other": 0}
    assert decisions["tool_calls"] == 4

    chat = next(row for row in decisions["by_agent"] if row["agent_id"] == "agent:chat-operator")
    assert (chat["total"], chat["passed"]) == (2, 2)
    rogue = next(row for row in decisions["by_tool"] if row["tool"] == "bash_rm_rf")
    assert rogue["refused"] == 1
    # A span that was not a gateway tool call is counted in the totals but carries no tool row.
    assert "queue_task:manual" not in {row["tool"] for row in decisions["by_tool"]}


def test_recent_decisions_are_newest_first_and_capped():
    spans = [_span(f"tool_call:t{i}", "agent:alpha", tool=f"t{i}", at=1000 + i) for i in range(10)]
    recent = governance.aggregate_decisions(spans, recent_limit=3)["recent"]
    assert [row["tool"] for row in recent] == ["t9", "t8", "t7"]


def test_evidence_trail_collects_the_checks_that_left_a_trace():
    spans = [
        _span("tool_call:extract_invoice_multimodal", "agent:invoice-extractor",
              tool="extract_invoice_multimodal", at=100, events=[
                  {"name": "privacy_screen", "timestamp": 100.1,
                   "payload": {"document": "Invoice_A.pdf", "verdict": "red", "findings": 2,
                               "patterns": "iban, email"}},
                  {"name": "model_armor_sanitized", "timestamp": 100.2, "payload": {"redactions": "completed"}},
              ]),
        _span("tool_call:read_web_page", "agent:web-reader", tool="read_web_page", at=200, events=[
            {"name": "web_page_inspected", "timestamp": 200.5,
             "payload": {"url": "https://example.org/a", "characters": 900, "armor_safe": True}},
        ]),
        # Metering is not evidence of a check - it has its own section and must not leak here.
        _span("tool_call:chat_completion", "agent:chat-operator", tool="chat_completion", at=300, events=[
            {"name": MODEL_USAGE_EVENT, "timestamp": 300.1, "payload": {"model": "gemini-3.5-flash",
                                                                        "total_tokens": 40}},
        ]),
    ]
    trail = governance.evidence_trail(spans)

    assert trail["total"] == 3
    assert dict((row["event"], row["count"]) for row in trail["counts"]) == {
        "privacy_screen": 1, "model_armor_sanitized": 1, "web_page_inspected": 1
    }
    assert [row["event"] for row in trail["recent"]][0] == "web_page_inspected"
    screen = next(row for row in trail["recent"] if row["event"] == "privacy_screen")
    assert screen["subject"] == "Invoice_A.pdf"
    assert screen["verdict"] == "red"
    assert "findings 2" in screen["details"]


def test_usage_sums_only_the_calls_that_reported_a_field():
    spans = [
        _span("tool_call:chat_completion", "agent:chat-operator", tool="chat_completion", events=[
            {"name": MODEL_USAGE_EVENT, "timestamp": 1.0,
             "payload": {"model": "gemini-3.5-flash", "prompt_tokens": 100, "output_tokens": 20,
                         "total_tokens": 120}},
        ]),
        _span("tool_call:execute_template", "agent:task-solver", tool="execute_template", events=[
            {"name": MODEL_USAGE_EVENT, "timestamp": 2.0,
             "payload": {"model": "gemini-3.7-flash", "total_tokens": 300}},
        ]),
    ]
    usage = governance.usage_summary(spans)

    assert usage["metered_calls"] == 2
    assert usage["total_tokens"] == 420
    # The second call reported no prompt count; the prompt column sums one call, and says so.
    assert usage["prompt_tokens"] == 100
    assert usage["reported"]["prompt_tokens"] == 1
    assert usage["reported"]["total_tokens"] == 2
    assert [row["model"] for row in usage["by_model"]] == ["gemini-3.5-flash", "gemini-3.7-flash"]


def test_usage_is_empty_rather_than_zero_when_nothing_was_metered():
    usage = governance.usage_summary([_span("tool_call:chat_completion", "agent:chat-operator",
                                            tool="chat_completion")])
    assert usage["metered_calls"] == 0
    assert usage["by_model"] == []


# ---------------------------------------------------------------------------
# Locks & quarantine
# ---------------------------------------------------------------------------

def test_agent_states_report_quarantine_with_its_ledger_moment():
    agents = [
        _agent("agent:alpha", {"query_memory_bank"}),
        _agent("agent:beta", {"query_memory_bank"}, status=AgentStatus.QUARANTINED,
               reason="Attempted unauthorized tool execution: bash_rm_rf"),
    ]
    spans = [
        _span("tool_call:bash_rm_rf", "agent:beta", status="SECURITY_VIOLATION", tool="bash_rm_rf", at=500),
        _span("tool_call:bash_rm_rf", "agent:beta", status="SECURITY_VIOLATION", tool="bash_rm_rf", at=900),
    ]
    states = governance.agent_states(agents, spans)

    assert states["quarantined"] == 1
    beta = next(row for row in states["rows"] if row["agent_id"] == "agent:beta")
    assert beta["quarantine_reason"].endswith("bash_rm_rf")
    # The newest refusing row, not the first one.
    assert beta["last_refusal_at"] == 900
    assert [row["agent_id"] for row in states["flagged"]] == ["agent:beta"]


def test_a_quarantine_older_than_the_ring_buffer_reports_no_moment_rather_than_a_guess():
    """The lifecycle manager keeps no timestamp; when the span has rolled out of the buffer the
    board leaves the field empty instead of inventing one."""
    agents = [_agent("agent:beta", {"query_memory_bank"}, status=AgentStatus.QUARANTINED, reason="old")]
    beta = governance.agent_states(agents, [])["rows"][0]
    assert beta["last_refusal_at"] is None
    assert beta["status"] == AgentStatus.QUARANTINED.value


# ---------------------------------------------------------------------------
# Plans & approvals
# ---------------------------------------------------------------------------

def _template(template_id, name, steps, **fields):
    return TaskTemplate(template_id=template_id, name=name, steps=steps, **fields)


def test_plan_catalogue_derives_steps_agents_and_gates():
    templates = [
        _template("TMPL-A", "Single", [Step(step_id="step-1", position=0, assigned_agent="agent:task-solver")]),
        _template(
            "TMPL-B", "Chain",
            [
                Step(step_id="step-1", position=0, assigned_agent="agent:invoice-extractor"),
                Step(step_id="step-2", position=1, assigned_agent="agent:compliance-auditor",
                     input_spec="previous_output"),
            ],
            requires_approval=True, group="omniledger"
        ),
    ]
    catalogue = governance.plan_catalogue(templates)
    rows = {row["template_id"]: row for row in catalogue["rows"]}

    assert catalogue["summary"]["total"] == 2
    assert catalogue["summary"]["chained"] == 1
    assert catalogue["summary"]["gated"] == 1
    assert rows["TMPL-B"]["agents"] == ["agent:compliance-auditor", "agent:invoice-extractor"]
    assert [step["position"] for step in rows["TMPL-B"]["steps"]] == [0, 1]
    assert rows["TMPL-A"]["step_count"] == 1


def test_plan_catalogue_ignores_a_viewer_s_hide_list():
    """The Fleet tab honours `removed_by` for the viewer looking at it. Governance is the global
    view: a template one operator hid from their own list is still standing work for the fleet."""
    hidden = _template("TMPL-H", "Hidden", [Step(step_id="step-1", position=0)], removed_by=["operator"])
    assert [row["template_id"] for row in governance.plan_catalogue([hidden])["rows"]] == ["TMPL-H"]


def _ticket(ticket_id, status, priority=TicketPriority.NORMAL, created=1000.0):
    return Ticket(
        ticket_id=ticket_id, title=f"Ticket {ticket_id}", description="synthetic",
        agent_id="agent:vendor-dispute", tool_name="send_external_email",
        priority=priority, status=status, created_at=created,
        resolved_at=created + 60 if status != TicketStatus.PENDING_APPROVAL else None
    )


def test_ticket_catalogue_splits_open_from_decided():
    tickets = [
        _ticket("TICK-1", TicketStatus.PENDING_APPROVAL, created=1000.0),
        _ticket("TICK-2", TicketStatus.APPROVED, created=2000.0),
        _ticket("TICK-3", TicketStatus.REJECTED, created=3000.0),
    ]
    catalogue = governance.ticket_catalogue(tickets)

    assert catalogue["summary"] == {"total": 3, "pending": 1, "approved": 1, "rejected": 1, "resolved": 0}
    assert [row["ticket_id"] for row in catalogue["pending"]] == ["TICK-1"]
    # Newest first, like every other register view on the console.
    assert [row["ticket_id"] for row in catalogue["decided"]] == ["TICK-3", "TICK-2"]


# ---------------------------------------------------------------------------
# The board and its API
# ---------------------------------------------------------------------------

def test_build_board_reports_every_section_and_names_its_counting_window():
    board = governance.build_board()

    assert set(board) >= {
        "window", "gate_sequence", "permissions", "policies", "decisions",
        "evidence", "usage", "agents", "plans", "tickets"
    }
    # The span buffer is a ring, so every verdict count is "of the retained rows" - the board
    # carries the limit and the never-forgetting exported total next to them.
    window = board["window"]
    assert window["retention_limit"] == 500
    assert window["retained_spans"] <= window["retention_limit"]
    assert isinstance(window["exported_total"], int)


def test_board_answers_from_the_same_registry_the_gateway_consults():
    """Not a fresh PermissionRegistry() that merely starts out identical: a board allowed to
    drift from the gate it reports on is worse than no board."""
    from sentinel_fleet.core.gateway import gateway

    gateway.permissions.rules.insert(
        0, type(gateway.permissions.rules[0])(
            tool_pattern="query_memory_bank", action=PermissionAction.ASK, reason="temporary test rule"
        )
    )
    try:
        row = next(r for r in governance.build_board()["permissions"]["rows"] if r["tool"] == "query_memory_bank")
        assert row["action"] == PermissionAction.ASK.value
    finally:
        gateway.permissions.rules.pop(0)


@pytest.mark.asyncio
async def test_board_endpoint_serves_the_whole_federation(client):
    response = await client.get("/api/governance/board")
    assert response.status_code == 200
    board = response.json()
    assert board["permissions"]["summary"]["tools"] > 0
    assert len(board["engine_checks"]) == 3
    assert board["policies"]["summary"]["total"] >= 3
    assert board["policies"]["summary"]["enforcing"] >= 3
    assert board["gate_sequence"][0]["stage"] == "Quarantine"


@pytest.mark.asyncio
async def test_permissions_endpoint_serves_the_matrix_alone(client):
    response = await client.get("/api/governance/permissions")
    assert response.status_code == 200
    matrix = response.json()
    assert {"identities", "rows", "summary"} <= set(matrix)
    # The seeded fleet really does hold an ASK-gated tool - the board is not an empty scaffold.
    assert any(row["action"] == "ask" and row["holders"] for row in matrix["rows"])


@pytest.mark.asyncio
async def test_board_is_read_only(client):
    """A read federation has no write surface. If one is ever added, this test should be the
    thing that forces the decision into the open."""
    assert (await client.post("/api/governance/board")).status_code == 405


# ---------------------------------------------------------------------------
# The Governance tab
#
# Rendering assertions only - a Jinja error in index.html turns the whole entry page into a 500,
# and the console has no other way to notice. They check that every section's loop body really
# ran, never how many rows it produced, because the registers behind them are shared.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_governance_tab_renders_with_all_its_sections(client):
    body = (await client.get("/")).text

    assert 'id="btn-tab-governance"' in body
    assert 'id="tab-governance"' in body
    for heading in ("Governance board", "How a call is gated", "Permission matrix", "Policies",
                    "Decisions", "Evidence", "Locks &amp; quarantine", "Plans", "Approvals",
                    "Model usage"):
        assert heading in body, f"governance section missing: {heading}"


@pytest.mark.asyncio
async def test_matrix_renders_identity_columns_and_a_legend(client):
    body = (await client.get("/")).text

    # Column heads carry the identity, cells carry the mark plus its explanation on hover.
    assert 'class="mx-id"' in body
    assert "mx-cell mx-out" in body
    assert "outside this identity&#39;s scope" in body or "outside this identity's scope" in body
    # The seeded fleet's ASK-gated tool and its reason both reach the page.
    assert "execute_bank_transfer" in body
    assert "Financial disbursements require human signoff" in body


@pytest.mark.asyncio
async def test_board_states_its_counting_window_on_the_page(client):
    """The ring buffer is the one thing a governance number can quietly lie about."""
    body = (await client.get("/")).text
    assert "ring buffer, limit" in body
    assert "have been exported in total" in body


@pytest.mark.asyncio
async def test_policy_thresholds_reach_the_page(client):
    body = (await client.get("/")).text
    assert f"{MATH_TOLERANCE_EUR:.2f} EUR" in body
    assert f"at most {MAX_STEPS} steps" in body


@pytest.mark.asyncio
async def test_usage_section_says_why_it_is_empty_in_demo_mode(client):
    """An empty cost panel must read as "nothing was metered", never as "spend was zero"."""
    body = (await client.get("/")).text
    assert "Nothing metered yet" in body
    assert "reports no" in body and "token usage" in body


# ---------------------------------------------------------------------------
# Step editor: the scope a step will actually run under
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_catalog_carries_the_execute_template_scope(client):
    """The step editor must not offer identities the template gateway will refuse."""
    body = (await client.get("/")).text
    catalog_json = body.split('id="agent-catalog"', 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    catalog = {entry["agent_id"]: entry for entry in json.loads(catalog_json)}

    assert catalog["agent:task-solver"]["can_execute_template"] is True
    assert "agent:invoice-extractor" not in catalog
    assert "agent:web-reader" not in catalog


@pytest.mark.asyncio
async def test_both_agent_pickers_only_offer_execute_template_scoped_agents(client):
    body = (await client.get("/")).text
    assert "Only agents with <code>execute_template</code> in scope" in body
    assert "no execute_template scope" not in body
    with open(Path(__file__).resolve().parents[1] / "src/sentinel_fleet/web/static/app.js",
              encoding="utf-8") as handle:
        script = handle.read()
    assert "can_execute_template === false" not in script
    assert "server catalog already contains only identities" in script


@pytest.mark.asyncio
async def test_a_real_run_shows_up_on_the_board(client):
    """End to end: process a document, then read its verdicts back off the board's API."""
    await client.post("/api/omniledger/process", data={"preset_type": "missing_vat"})
    board = (await client.get("/api/governance/board")).json()

    tools = {row["tool"] for row in board["decisions"]["by_tool"]}
    assert "validate_tax_compliance" in tools
    # The dispute path hits the ASK gate, which parks the call rather than completing it.
    assert board["decisions"]["by_verdict"]["held"] >= 1
    # And Model Armor left evidence that it looked at the arguments.
    assert any(row["event"] == "model_armor_sanitized" for row in board["evidence"]["counts"])


# ---------------------------------------------------------------------------
# Board legibility. Four findings from the live walkthrough: an explanation that read as a
# control, sections that gave no clue whether they could be acted on, two names already taken in
# the operator's head ("Plans", "Decisions"), and duplication of what other tabs hold in full.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_gate_sequence_folds_away():
    """The five gates are a reference. As a plain card among controls the live test took them
    for one: "confusing, you think you could do something there"."""
    from httpx import AsyncClient, ASGITransport
    from sentinel_fleet.web.server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    assert 'class="card gov-explainer"' in body
    assert "<details" in body.split("How a call is gated")[0][-400:], \
        "the gate sequence has to be a disclosure, not an open panel"
    assert "explanation only" in body
    # Content unchanged - it was good, only its framing was wrong.
    assert "gate-stage" in body


@pytest.mark.asyncio
async def test_every_board_section_says_whether_it_acts():
    from httpx import AsyncClient, ASGITransport
    from sentinel_fleet.web.server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    board = body.split('id="tab-governance"')[1].split("</section>")[0]
    assert board.count("read-only view") >= 5, "a read-only section must say so"
    # Locks and quarantine is the one place on this board with a button.
    locks = board.split("Locks &amp; quarantine")[1][:200]
    assert "actions available" in locks


@pytest.mark.asyncio
async def test_the_board_does_not_repeat_what_other_tabs_hold_in_full():
    """Reading federation is not a licence to render everything twice."""
    from httpx import AsyncClient, ASGITransport
    from sentinel_fleet.web.server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    board = body.split('id="tab-governance"')[1].split("</section>")[0]
    assert "Tasks with steps" in board, "the operator reads 'Plans' as something else entirely"
    assert ">Plans<" not in board, "the name stays free for a real plan concept"
    assert "See them with their steps in Fleet" in board
    assert "Open Approvals" in board
    assert "Tool-call decisions" in board, "'Decisions' means operator decisions to this operator"


@pytest.mark.asyncio
async def test_the_usage_counter_admits_that_it_resets():
    """Metering works - the operator simply never saw it, because every deploy zeroes an
    in-memory counter. That is a labelling problem, not a persistence one."""
    from httpx import AsyncClient, ASGITransport
    from sentinel_fleet.web.server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    assert "Counted since this" in body
    assert "normal right after a deploy" in body


@pytest.mark.asyncio
async def test_telemetry_names_itself_as_the_full_gate_ledger():
    """Two names for one thing: the overview says "Gate ledger", the tab says "Telemetry"."""
    from httpx import AsyncClient, ASGITransport
    from sentinel_fleet.web.server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/")).text

    assert "Telemetry — the full gate ledger" in body
    assert "shows the last three of these" in body
