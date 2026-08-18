"""Unit tests for routine/schedule bindings: derived badges and status, template execution,
and the `/api/routines/fire` trigger (concept doc, section A.5 / C.4 / D Phase 1).
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

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
    template = _template(name="Running beats preparing")
    task = task_master.create_task(
        name="probe", assigned_agent="agent:task-solver", input_data={}, source_template_id=template.template_id
    )
    task_master.update_task_state(task.task_id, TaskState.IN_PROGRESS)
    routines.routine_binding_registry.set_binding(template.template_id, {"kind": "interval", "seconds": 30})
    assert routines.derive_runtime_status(template.template_id) == "running"


def test_preparing_window_and_no_status_outside_it():
    template = _template(name="Preparing window")
    routine = routines.routine_binding_registry.set_binding(template.template_id, {"kind": "interval", "seconds": 60})

    routine.next_due_at = routines._iso(_now() + timedelta(minutes=5))
    routines.routine_binding_registry.save(routine)
    assert routines.derive_runtime_status(template.template_id) == "preparing"

    routine.next_due_at = routines._iso(_now() + timedelta(hours=2))
    routines.routine_binding_registry.save(routine)
    assert routines.derive_runtime_status(template.template_id) is None


def test_disabled_routine_carries_no_status():
    """A paused routine (enabled=False) gets no colour at all - not a warning colour either
    (concept doc, section A.5: red/paused was dropped, it simply falls into "no status")."""
    template = _template(name="Paused routine")
    routine = routines.routine_binding_registry.set_binding(
        template.template_id, {"kind": "interval", "seconds": 60}, enabled=False
    )
    routine.next_due_at = routines._iso(_now() + timedelta(minutes=1))
    routines.routine_binding_registry.save(routine)
    assert routines.derive_runtime_status(template.template_id) is None


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
    response = await client.post("/api/routines/fire")
    assert response.status_code == 200
