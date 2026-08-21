"""Unit tests for routine/schedule bindings: derived badges and status, template execution,
and the `/api/routines/fire` trigger (concept doc, section A.5 / C.4 / D Phase 1).
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from sentinel_fleet.core.run_log import run_log_bus
from sentinel_fleet.core.telemetry import telemetry
from sentinel_fleet.uas import routines
from sentinel_fleet.uas.task_master import TaskState, task_master
from sentinel_fleet.uas.task_templates import task_template_registry
from sentinel_fleet.uas.ticket_master import TicketStatus, ticket_master
from sentinel_fleet.web.server import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _template(**overrides):
    fields = {
        "name": "Test template",
        "owner": "operator",
        "prompt_source": "custom",
        "custom_prompt_text": "Say hello.",
    }
    fields.update(overrides)
    return task_template_registry.create_template(**fields)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Derived symbols (gear/clock) and runtime status - never stored, recomputed on every read.
# ---------------------------------------------------------------------------

def test_symbols_reflect_attached_bindings():
    template = _template(name="Badge test")
    assert routines.derive_symbols(None, None) == {"gear": False, "clock": False}

    routine = routines.routine_binding_registry.set_binding(template.template_id, {"kind": "interval", "seconds": 60})
    assert routines.derive_symbols(routine, None) == {"gear": True, "clock": False}

    schedule = routines.schedule_binding_registry.set_binding(
        template.template_id, due_at=(_now() + timedelta(hours=1)).isoformat()
    )
    assert routines.derive_symbols(routine, schedule) == {"gear": True, "clock": True}


def test_clock_disappears_once_the_due_date_has_passed():
    """The clock badge is derived from status == pending AND due_at >= now on every render -
    not a stored flag - so it vanishes the instant the deadline passes, even before `/fire`
    has had a chance to process the binding (concept doc, section A.5)."""
    template = _template(name="Overdue schedule")
    schedule = routines.schedule_binding_registry.set_binding(
        template.template_id, due_at=(_now() - timedelta(hours=2)).isoformat()
    )
    assert schedule.status == "pending"  # still pending: nothing has fired it yet
    assert routines.derive_symbols(None, schedule)["clock"] is False


def test_running_status_from_an_in_progress_task_record():
    template = _template(name="Running probe")
    task = task_master.create_task(
        name="probe", assigned_agent="agent:task-solver", input_data={}, source_template_id=template.template_id
    )
    task_master.update_task_state(task.task_id, TaskState.IN_PROGRESS)
    assert routines.derive_runtime_status(template.template_id) == "running"


def test_running_dominates_preparing():
    """Two runs of the same template at once: one IN_PROGRESS, one still QUEUED. The
    aggregation rule (concept doc, section A.3) is running-beats-preparing regardless of how
    many other runs of the same template are still queued alongside it."""
    template = _template(name="Running beats preparing")
    running_task = task_master.create_task(
        name="running probe", assigned_agent="agent:task-solver", input_data={}, source_template_id=template.template_id
    )
    task_master.update_task_state(running_task.task_id, TaskState.IN_PROGRESS)
    task_master.create_task(
        name="queued probe", assigned_agent="agent:task-solver", input_data={}, source_template_id=template.template_id
    )  # left in state QUEUED
    assert routines.derive_runtime_status(template.template_id) == "running"


def test_preparing_status_from_a_queued_or_awaiting_approval_task_record():
    """Preparing is derived purely from this template's own TaskRecords - never from a
    binding's next_due_at lookahead (concept doc, section A.3/A.5, 2026-08-18 correction)."""
    template = _template(name="Preparing via queued record")
    task = task_master.create_task(
        name="probe", assigned_agent="agent:task-solver", input_data={}, source_template_id=template.template_id
    )
    assert task.state == TaskState.QUEUED
    assert routines.derive_runtime_status(template.template_id) == "preparing"

    task_master.update_task_state(task.task_id, TaskState.AWAITING_APPROVAL)
    assert routines.derive_runtime_status(template.template_id) == "preparing"

    task_master.update_task_state(task.task_id, TaskState.COMPLETED)
    assert routines.derive_runtime_status(template.template_id) is None


def test_a_bare_immediate_enqueue_is_not_a_special_case():
    """"Sofort einreihen" runs through exactly the same QUEUED->IN_PROGRESS->terminal path as
    a routine- or schedule-triggered run - no separate heuristic for the unbound case."""
    template = _template(name="Bare immediate enqueue")
    task = task_master.create_task(
        name="manual probe", assigned_agent="agent:task-solver", input_data={},
        source_template_id=template.template_id, triggered_by="manual"
    )
    assert routines.derive_runtime_status(template.template_id) == "preparing"
    task_master.update_task_state(task.task_id, TaskState.IN_PROGRESS)
    assert routines.derive_runtime_status(template.template_id) == "running"


def test_bindings_alone_never_produce_a_runtime_status():
    """A routine or schedule binding with no associated TaskRecord in a non-terminal state
    carries no colour by itself - true whether the routine is enabled or paused. A paused
    routine (enabled=False) is not a special case either: it never fires, so it never has a
    non-terminal TaskRecord, so it falls into "no status" through the same general rule (no
    dedicated red/paused colour - concept doc, section A.5)."""
    enabled_template = _template(name="Enabled routine, no runs yet")
    routines.routine_binding_registry.set_binding(enabled_template.template_id, {"kind": "interval", "seconds": 60})
    assert routines.derive_runtime_status(enabled_template.template_id) is None

    disabled_template = _template(name="Paused routine")
    routines.routine_binding_registry.set_binding(
        disabled_template.template_id, {"kind": "interval", "seconds": 60}, enabled=False
    )
    assert routines.derive_runtime_status(disabled_template.template_id) is None

    scheduled_template = _template(name="Pending schedule, no runs yet")
    routines.schedule_binding_registry.set_binding(
        scheduled_template.template_id, due_at=(_now() + timedelta(minutes=1)).isoformat()
    )
    assert routines.derive_runtime_status(scheduled_template.template_id) is None


def test_next_due_summary_picks_the_earliest_of_routine_and_schedule():
    template = _template(name="Earliest due")
    routine = routines.routine_binding_registry.set_binding(template.template_id, {"kind": "interval", "seconds": 60})
    routine.next_due_at = routines._iso(_now() + timedelta(hours=5))
    routines.routine_binding_registry.save(routine)

    routines.schedule_binding_registry.set_binding(template.template_id, due_at=(_now() + timedelta(hours=1)).isoformat())

    summary = routines.next_due_summary(template.template_id)
    assert summary == routines.schedule_binding_registry.get_pending_for_template(template.template_id).due_at


# ---------------------------------------------------------------------------
# Execution: enqueue_template() creates a real TaskMaster run and a gateway ledger span.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_creates_a_run_and_a_gateway_ledger_span():
    template = _template(name="Enqueue probe", assigned_agent="agent:task-solver")

    task = await routines.enqueue_template(template.template_id, triggered_by="manual")

    assert task.source_template_id == template.template_id
    assert task.triggered_by == "manual"
    assert task.state == TaskState.COMPLETED
    assert task.output_data["mode"] in ("deterministic-demo", "gemini-live")

    # The run really is a TaskMaster task, not a second, parallel object.
    stored = task_master.get_task(task.task_id)
    assert stored is not None and stored.task_id == task.task_id
    assert task.task_id in {t.task_id for t in task_master.list_by_template(template.template_id)}

    # execute_tool_call() opens and closes exactly one ledger span per run.
    matching = [
        s for s in telemetry.get_recent_spans()
        if s.name == "tool_call:execute_template" and s.agent_id == "agent:task-solver"
    ]
    assert matching, "no gateway ledger span was recorded for the template run"
    assert matching[0].status == "OK"


@pytest.mark.asyncio
async def test_enqueue_with_missing_agent_fails_the_run_instead_of_raising():
    template = _template(name="Unregistered agent", assigned_agent="agent:does-not-exist")
    task = await routines.enqueue_template(template.template_id, triggered_by="manual")
    assert task.state == TaskState.FAILED
    assert "not registered" in task.error_message


@pytest.mark.asyncio
async def test_enqueue_with_requires_approval_routes_to_the_ticket_gate():
    """A per-template `requires_approval` flag takes the same HITL path as
    `send_external_email` - a ticket is created and the run waits (concept doc, section A.4)."""
    template = _template(name="Gated template", requires_approval=True)
    task = await routines.enqueue_template(template.template_id, triggered_by="manual")

    assert task.state == TaskState.AWAITING_APPROVAL
    ticket_id = task.output_data["ticket_id"]
    ticket = ticket_master.get_ticket(ticket_id)
    assert ticket is not None
    assert ticket.status == TicketStatus.PENDING_APPROVAL
    assert ticket.payload["template_id"] == template.template_id


# ---------------------------------------------------------------------------
# run_log_bus emitter: the single-step path mirrors its own status lines into the run console's
# log bus and closes it on every terminal return (concept doc, section C.7 Ausprägung (b)
# "WEB-Konsole") - unchanged since before chains existed otherwise, this is the only new thing
# on this path. run_id == task_id throughout.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_completed_single_step_run_emits_a_status_narrative_and_closes_the_bus():
    template = _template(name="Single-step log probe", assigned_agent="agent:task-solver")

    task = await routines.enqueue_template(template.template_id, triggered_by="manual")

    assert task.state == TaskState.COMPLETED
    lines, _, closed = run_log_bus.snapshot(task.task_id)
    joined = "\n".join(lines)
    assert f"task {task.task_id} created for template" in joined
    assert template.template_id in joined
    assert "triggered_by=manual" in joined
    assert "step 1/1 via agent:task-solver" in joined and "started" in joined
    assert "step 1/1: completed (model=" in joined
    assert "task completed" in joined
    assert closed is True
    # Multi-step-only lines never appear on the single-step path.
    assert "delegating to chain runner" not in joined
    assert "chain run" not in joined
    # Never the model's actual reply text (concept doc: status/pattern/model/gate/error only).
    assert task.output_data["content"] not in joined


@pytest.mark.asyncio
async def test_enqueue_with_missing_agent_emits_a_failure_line_and_closes_the_bus():
    template = _template(name="Unregistered agent, log probe", assigned_agent="agent:does-not-exist")
    task = await routines.enqueue_template(template.template_id, triggered_by="manual")

    lines, _, closed = run_log_bus.snapshot(task.task_id)
    joined = "\n".join(lines)
    assert "failed - agent 'agent:does-not-exist' is not registered" in joined
    assert closed is True


@pytest.mark.asyncio
async def test_enqueue_with_requires_approval_emits_its_line_before_any_step_runs():
    template = _template(name="Gated template, log probe", requires_approval=True)
    task = await routines.enqueue_template(template.template_id, triggered_by="manual")

    lines, _, closed = run_log_bus.snapshot(task.task_id)
    joined = "\n".join(lines)
    assert "template requires approval" in joined
    assert "ticket" in joined
    assert closed is True
    # The gate stopped it before any step-level line was ever emitted.
    assert "step 1/1" not in joined


# ---------------------------------------------------------------------------
# fire_due(): the Cloud Scheduler trigger.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fire_enqueues_a_due_routine_and_leaves_a_future_one_alone():
    due_template = _template(name="Due now")
    due_binding = routines.routine_binding_registry.set_binding(due_template.template_id, {"kind": "interval", "seconds": 3600})
    due_binding.next_due_at = routines._iso(_now() - timedelta(minutes=1))
    routines.routine_binding_registry.save(due_binding)

    future_template = _template(name="Not due yet")
    future_binding = routines.routine_binding_registry.set_binding(future_template.template_id, {"kind": "interval", "seconds": 3600})
    future_binding.next_due_at = routines._iso(_now() + timedelta(hours=3))
    routines.routine_binding_registry.save(future_binding)

    result = await routines.fire_due()

    fired_ids = {row["binding_id"] for row in result["fired"]}
    assert due_binding.binding_id in fired_ids
    assert future_binding.binding_id not in fired_ids
    assert result["not_due"] >= 1

    # next_due_at moved into the future, so the routine will not fire again immediately.
    refired = routines.routine_binding_registry.get_for_template(due_template.template_id)
    assert routines._parse_iso(refired.next_due_at) > _now()


@pytest.mark.asyncio
async def test_fire_is_idempotent_for_two_calls_in_a_row():
    template = _template(name="Idempotency probe")
    binding = routines.routine_binding_registry.set_binding(template.template_id, {"kind": "interval", "seconds": 3600})
    binding.next_due_at = routines._iso(_now() - timedelta(seconds=5))
    routines.routine_binding_registry.save(binding)

    first = await routines.fire_due()
    second = await routines.fire_due()

    first_ids = {row["binding_id"] for row in first["fired"]}
    second_ids = {row["binding_id"] for row in second["fired"]}
    assert binding.binding_id in first_ids
    assert binding.binding_id not in second_ids  # the second call sees a future next_due_at

    runs = [t for t in task_master.list_by_template(template.template_id) if t.source_binding_id == binding.binding_id]
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_fire_routine_skip_policy_drops_the_backlog_and_resumes_from_now():
    template = _template(name="Skip backlog")
    binding = routines.routine_binding_registry.set_binding(
        template.template_id, {"kind": "interval", "seconds": 300}, miss_policy="skip"
    )
    # Missed several 5-minute ticks in a row (e.g. after a scale-to-zero gap).
    binding.next_due_at = routines._iso(_now() - timedelta(hours=2))
    routines.routine_binding_registry.save(binding)

    result = await routines.fire_due()
    assert binding.binding_id in {row["binding_id"] for row in result["fired"]}

    refired = routines.routine_binding_registry.get_for_template(template.template_id)
    # Resumed from "now", not from the missed occurrence: due again in ~5 minutes, not in the past.
    assert routines._parse_iso(refired.next_due_at) > _now()

    # Only one run was created for the whole backlog.
    runs = [t for t in task_master.list_by_template(template.template_id) if t.source_binding_id == binding.binding_id]
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_fire_routine_catch_up_policy_drains_the_backlog_one_run_per_call():
    template = _template(name="Catch-up backlog")
    binding = routines.routine_binding_registry.set_binding(
        template.template_id, {"kind": "interval", "seconds": 300}, miss_policy="catch_up"
    )
    # Two intervals behind: due at (now - 11 minutes) on a 5-minute cadence.
    binding.next_due_at = routines._iso(_now() - timedelta(minutes=11))
    routines.routine_binding_registry.save(binding)

    first = await routines.fire_due()
    assert binding.binding_id in {row["binding_id"] for row in first["fired"]}
    after_first = routines.routine_binding_registry.get_for_template(template.template_id)
    # Stepped forward by exactly one interval from the missed occurrence - still in the past,
    # so the backlog is not drained yet.
    assert routines._parse_iso(after_first.next_due_at) < _now()

    second = await routines.fire_due()
    assert binding.binding_id in {row["binding_id"] for row in second["fired"]}

    runs = [t for t in task_master.list_by_template(template.template_id) if t.source_binding_id == binding.binding_id]
    assert len(runs) == 2  # two catch-up runs, one per fire() call, draining the backlog


@pytest.mark.asyncio
async def test_fire_schedule_skip_vs_catch_up_for_a_missed_one_off():
    skip_template = _template(name="Missed, skip")
    skip_binding = routines.schedule_binding_registry.set_binding(
        skip_template.template_id, due_at=(_now() - timedelta(hours=3)).isoformat(), miss_policy="skip"
    )
    catch_up_template = _template(name="Missed, catch up")
    catch_up_binding = routines.schedule_binding_registry.set_binding(
        catch_up_template.template_id, due_at=(_now() - timedelta(hours=3)).isoformat(), miss_policy="catch_up"
    )

    result = await routines.fire_due()

    skipped_ids = {row["binding_id"] for row in result["skipped"]}
    fired_ids = {row["binding_id"] for row in result["fired"]}
    assert skip_binding.binding_id in skipped_ids
    assert catch_up_binding.binding_id in fired_ids

    assert routines.schedule_binding_registry.get_pending_for_template(skip_template.template_id) is None
    stored_skip = [b for b in routines.schedule_binding_registry.list_by_template(skip_template.template_id)][0]
    assert stored_skip.status == "skipped"
    assert not task_master.list_by_template(skip_template.template_id)  # no run for the skipped one

    assert task_master.list_by_template(catch_up_template.template_id)  # ran late


@pytest.mark.asyncio
async def test_fire_schedule_within_grace_window_fires_regardless_of_policy():
    template = _template(name="Just barely late", assigned_agent="agent:task-solver")
    binding = routines.schedule_binding_registry.set_binding(
        template.template_id, due_at=(_now() - timedelta(minutes=5)).isoformat(), miss_policy="skip"
    )

    result = await routines.fire_due()
    assert binding.binding_id in {row["binding_id"] for row in result["fired"]}


@pytest.mark.asyncio
async def test_fire_endpoint_requires_the_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("ROUTINES_FIRE_TOKEN", "s3cret")

    unauthenticated = await client.post("/api/routines/fire")
    assert unauthenticated.status_code == 401

    wrong_token = await client.post("/api/routines/fire", headers={"X-Fire-Token": "wrong"})
    assert wrong_token.status_code == 401

    authenticated = await client.post("/api/routines/fire", headers={"X-Fire-Token": "s3cret"})
    assert authenticated.status_code == 200
    assert "fired" in authenticated.json()


@pytest.mark.asyncio
async def test_fire_endpoint_stays_open_without_a_configured_token(client, monkeypatch):
    monkeypatch.delenv("ROUTINES_FIRE_TOKEN", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    response = await client.post("/api/routines/fire")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_fire_endpoint_fails_closed_on_cloud_run_without_token(client, monkeypatch):
    monkeypatch.delenv("ROUTINES_FIRE_TOKEN", raising=False)
    monkeypatch.setenv("K_SERVICE", "sentinel-fleet")
    response = await client.post("/api/routines/fire")
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Quarantine and the truth of a task's state. Reported from the live test: "it says In Progress
# ... it does not look to me like anything is actually happening". Measured on 2026-08-19: the
# record really did sit at IN_PROGRESS for ever, and releasing the agent did not touch it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_the_gateway_refuses_does_not_stay_in_progress():
    from sentinel_fleet.conductor.lifecycle import lifecycle_manager
    from sentinel_fleet.core.errors import QuarantineLockError
    from sentinel_fleet.core.identity import AgentStatus

    agent_id = "agent:system-auditor"
    template = _template(name="Quarantined run", assigned_agent=agent_id)
    lifecycle_manager.update_agent_status(
        agent_id, AgentStatus.QUARANTINED, reason="Model Armor: test injection"
    )
    try:
        with pytest.raises(QuarantineLockError):
            await routines.enqueue_template(template.template_id, triggered_by="manual")

        runs = [t for t in task_master.list_all() if t.source_template_id == template.template_id]
        assert len(runs) == 1
        assert runs[0].state is TaskState.FAILED, \
            "a refused run must not keep claiming to be in progress"
        assert "QUARANTINE" in (runs[0].error_message or "").upper(), \
            "the run has to say why it stopped"
    finally:
        lifecycle_manager.update_agent_status(agent_id, AgentStatus.IDLE)


@pytest.mark.asyncio
async def test_a_refused_chain_run_is_settled_too(client):
    """The chain runner reaches the gateway through its own call site, so the single-step fix
    alone would have left multi-step templates hanging exactly as before."""
    from sentinel_fleet.conductor.lifecycle import lifecycle_manager
    from sentinel_fleet.core.errors import QuarantineLockError
    from sentinel_fleet.core.identity import AgentStatus
    from sentinel_fleet.uas.task_templates import Step

    agent_id = "agent:system-auditor"
    template = _template(
        name="Quarantined chain",
        assigned_agent=agent_id,
        steps=[
            Step(step_id="step-1", position=0, assigned_agent=agent_id, custom_prompt_text="One."),
            Step(step_id="step-2", position=1, assigned_agent=agent_id, custom_prompt_text="Two."),
        ],
    )
    lifecycle_manager.update_agent_status(agent_id, AgentStatus.QUARANTINED, reason="Model Armor: test")
    try:
        with pytest.raises(QuarantineLockError):
            await routines.enqueue_template(template.template_id, triggered_by="manual")
        runs = [t for t in task_master.list_all() if t.source_template_id == template.template_id]
        assert runs and runs[0].state is TaskState.FAILED
    finally:
        lifecycle_manager.update_agent_status(agent_id, AgentStatus.IDLE)


@pytest.mark.asyncio
async def test_public_demo_member_cannot_release_a_global_quarantine(client):
    """A shared anonymous member must not unlock a fleet-wide security quarantine."""
    from sentinel_fleet.conductor.lifecycle import lifecycle_manager
    from sentinel_fleet.core.errors import QuarantineLockError
    from sentinel_fleet.core.identity import AgentStatus

    agent_id = "agent:system-auditor"
    template = _template(name="Released run", assigned_agent=agent_id)
    lifecycle_manager.update_agent_status(agent_id, AgentStatus.QUARANTINED, reason="Model Armor: test")
    with pytest.raises(QuarantineLockError):
        await routines.enqueue_template(template.template_id, triggered_by="manual")

    try:
        response = await client.post(f"/api/agents/{agent_id}/quarantine/release")
        assert response.status_code == 403

        runs = [t for t in task_master.list_all() if t.source_template_id == template.template_id]
        assert all(t.state is TaskState.FAILED for t in runs), \
            "a rejected release must not resurrect a run"
        assert lifecycle_manager.get_agent(agent_id).status is AgentStatus.QUARANTINED
    finally:
        lifecycle_manager.update_agent_status(agent_id, AgentStatus.IDLE)


# ---------------------------------------------------------------------------
# Intervening in the queue. The live test ended up with two identical tasks after the quarantine
# hang and had no way to touch either: "deactivate, delete or pause ... I cannot intervene".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_queued_task_can_be_cancelled_and_stays_in_the_queue(client):
    """Cancelling is a state, not an eraser: the record and its history remain."""
    created = await client.post("/api/tasks/create", data={
        "name": "Duplicate to call off", "assigned_agent": "agent:system-auditor"
    })
    task_id = created.json()["task"]["task_id"]

    cancelled = await client.post(f"/api/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["task"]["state"] == "cancelled"

    record = task_master.get_task(task_id)
    assert record is not None, "cancelling must not remove the record"
    assert record.state is TaskState.CANCELLED
    assert "operator" in (record.error_message or "").lower()


@pytest.mark.asyncio
async def test_cancelling_is_refused_once_a_task_has_settled(client):
    """Terminal states are final - that rule holds for the new state too."""
    created = await client.post("/api/tasks/create", data={
        "name": "Already settled", "assigned_agent": "agent:system-auditor"
    })
    task_id = created.json()["task"]["task_id"]
    task_master.update_task_state(task_id, TaskState.COMPLETED)

    refused = await client.post(f"/api/tasks/{task_id}/cancel")
    assert refused.status_code == 409
    assert task_master.get_task(task_id).state is TaskState.COMPLETED


def test_a_running_task_has_no_cancel_edge():
    """A run in flight is synchronous and over in seconds. Offering to stop it would be a button
    with nothing behind it - the same class of untruth as an "in progress" that is not running."""
    from sentinel_fleet.uas.task_master import ALLOWED_TASK_TRANSITIONS

    assert TaskState.CANCELLED not in ALLOWED_TASK_TRANSITIONS[TaskState.IN_PROGRESS]
    assert TaskState.CANCELLED in ALLOWED_TASK_TRANSITIONS[TaskState.QUEUED]
    assert TaskState.CANCELLED in ALLOWED_TASK_TRANSITIONS[TaskState.AWAITING_APPROVAL]
    assert ALLOWED_TASK_TRANSITIONS[TaskState.CANCELLED] == set(), "cancelled is terminal"


@pytest.mark.asyncio
async def test_only_a_settled_record_can_be_removed(client):
    """Removing does erase. A queued task still belongs to the fleet, so it may not go - the
    queue would stop describing what the fleet is actually doing."""
    created = await client.post("/api/tasks/create", data={
        "name": "Still queued", "assigned_agent": "agent:system-auditor"
    })
    task_id = created.json()["task"]["task_id"]

    refused = await client.delete(f"/api/tasks/{task_id}")
    assert refused.status_code == 409
    assert task_master.get_task(task_id) is not None

    await client.post(f"/api/tasks/{task_id}/cancel")
    removed = await client.delete(f"/api/tasks/{task_id}")
    assert removed.status_code == 200
    assert task_master.get_task(task_id) is None
