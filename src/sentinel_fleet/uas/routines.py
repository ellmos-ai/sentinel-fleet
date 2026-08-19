"""RoutineBinding / ScheduleBinding: independent attachments that turn a bare TaskTemplate into
a recurring or a dated task, plus the execution engine that actually runs one.

Two bindings, never a new object type for the template itself (concept doc, section A.1/A.3):
- RoutineBinding - recurring, `enabled` on/off, `schedule_spec` in the ellmos-scheduler format
  (interval/daily/cron; see `core/schedule_math.py`).
- ScheduleBinding - a one-off `due_at`, kept around after it fires as a run-history row.

A "run" is not a third object either. Firing a binding creates a `TaskRecord` (the existing
TaskMaster queue) carrying `source_template_id`/`source_binding_id`/`triggered_by` - the task
queue table already IS the view of every run, template-triggered or not.
"""

import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from sentinel_fleet.chat.service import chat_service
from sentinel_fleet.conductor.lifecycle import lifecycle_manager
from sentinel_fleet.core import chain_runner
from sentinel_fleet.core.config import settings
from sentinel_fleet.core.errors import (
    QuarantineLockError,
    SecurityViolationError,
    TemplateHasBindingsError,
    TemplateNotFoundError,
)
from sentinel_fleet.core.gateway import gateway
from sentinel_fleet.core.run_log import run_log_bus
from sentinel_fleet.core.schedule_math import next_after
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.uas.task_master import TaskRecord, TaskState, task_master
from sentinel_fleet.uas.task_templates import EXECUTE_TEMPLATE_TOOL, TaskTemplate, task_template_registry
from sentinel_fleet.uas.ticket_master import TicketPriority, ticket_master

# How far past a one-off ScheduleBinding's due_at counts as "missed" rather than "fired a
# little late" - the grace window a responsive Cloud Scheduler tick normally lands inside.
SCHEDULE_GRACE_SECONDS = 15 * 60

STATUS_RANK = {"running": 0, "preparing": 1, None: 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    """Accepts both a full timestamp and a bare date (ScheduleBinding.has_time == False)."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        dt = datetime.combine(date.fromisoformat(value), datetime.min.time())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class RoutineBinding(BaseModel):
    binding_id: str
    template_id: str
    schedule_spec: Dict[str, Any]
    enabled: bool = True
    miss_policy: str = "skip"          # "skip" | "catch_up"
    next_due_at: Optional[str] = None  # ISO 8601 UTC, recomputed on every fire
    created_at: float = Field(default_factory=time.time)


class ScheduleBinding(BaseModel):
    binding_id: str
    template_id: str
    due_at: str                # ISO 8601 date or date+time
    has_time: bool = True
    miss_policy: str = "skip"  # "skip" | "catch_up"
    status: str = "pending"    # pending | fired | skipped
    created_at: float = Field(default_factory=time.time)


class RoutineBindingRegistry:
    """At most one RoutineBinding per template - the UI offers a single routine toggle,
    not a list, so "add a routine" replaces rather than accumulates."""

    def __init__(self):
        self._store = get_store("routine_bindings", RoutineBinding)

    def get_for_template(self, template_id: str) -> Optional[RoutineBinding]:
        for b in self._store.list_all():
            if b.template_id == template_id:
                return b
        return None

    def set_binding(
        self, template_id: str, schedule_spec: Dict[str, Any], miss_policy: str = "skip", enabled: bool = True
    ) -> RoutineBinding:
        existing = self.get_for_template(template_id)
        due = next_after(schedule_spec, _now())
        binding = RoutineBinding(
            binding_id=existing.binding_id if existing else f"RTBIND-{uuid.uuid4().hex[:8].upper()}",
            template_id=template_id,
            schedule_spec=schedule_spec,
            enabled=enabled,
            miss_policy=miss_policy,
            next_due_at=_iso(due) if due else None,
            created_at=existing.created_at if existing else time.time()
        )
        self._store.put(binding.binding_id, binding)
        return binding

    def remove_for_template(self, template_id: str) -> bool:
        existing = self.get_for_template(template_id)
        return self._store.delete(existing.binding_id) if existing else False

    def list_all(self) -> List[RoutineBinding]:
        return self._store.list_all()

    def save(self, binding: RoutineBinding) -> RoutineBinding:
        self._store.put(binding.binding_id, binding)
        return binding


class ScheduleBindingRegistry:
    """Several ScheduleBinding rows may exist per template over time (run history); at most
    one of them is ever `pending` - that is the one the clock badge and the UI form act on."""

    def __init__(self):
        self._store = get_store("schedule_bindings", ScheduleBinding)

    def get_pending_for_template(self, template_id: str) -> Optional[ScheduleBinding]:
        for b in self._store.list_all():
            if b.template_id == template_id and b.status == "pending":
                return b
        return None

    def set_binding(
        self, template_id: str, due_at: str, has_time: bool = True, miss_policy: str = "skip"
    ) -> ScheduleBinding:
        existing = self.get_pending_for_template(template_id)
        if existing:
            self._store.delete(existing.binding_id)
        binding = ScheduleBinding(
            binding_id=f"SCBIND-{uuid.uuid4().hex[:8].upper()}",
            template_id=template_id,
            due_at=due_at,
            has_time=has_time,
            miss_policy=miss_policy
        )
        self._store.put(binding.binding_id, binding)
        return binding

    def remove_pending_for_template(self, template_id: str) -> bool:
        existing = self.get_pending_for_template(template_id)
        return self._store.delete(existing.binding_id) if existing else False

    def list_all(self) -> List[ScheduleBinding]:
        return self._store.list_all()

    def list_by_template(self, template_id: str) -> List[ScheduleBinding]:
        return [b for b in self._store.list_all() if b.template_id == template_id]

    def save(self, binding: ScheduleBinding) -> ScheduleBinding:
        self._store.put(binding.binding_id, binding)
        return binding


routine_binding_registry = RoutineBindingRegistry()
schedule_binding_registry = ScheduleBindingRegistry()


# ---------------------------------------------------------------------------
# Derived display state - never stored, recomputed on every read (Routinika precedent,
# concept doc section B.4.1).
# ---------------------------------------------------------------------------

def derive_symbols(routine: Optional[RoutineBinding], schedule: Optional[ScheduleBinding], now: Optional[datetime] = None) -> Dict[str, bool]:
    now = now or _now()
    clock = bool(schedule and schedule.status == "pending" and _parse_iso(schedule.due_at) >= now)
    return {"gear": routine is not None, "clock": clock}


def derive_runtime_status(template_id: str) -> Optional[str]:
    """Green (running) beats yellow (preparing) beats no status - purely from this template's
    own TaskRecords, never from an upcoming-due-time lookahead (concept doc, section A.3/A.5,
    2026-08-18 correction). A bare "enqueue now" run goes through the exact same
    QUEUED -> IN_PROGRESS -> terminal path as a routine- or schedule-triggered one, so it is
    not a special case with its own heuristic - it is covered by this same rule automatically.
    """
    runs = task_master.list_by_template(template_id)
    if any(r.state == TaskState.IN_PROGRESS for r in runs):
        return "running"
    if any(r.state in (TaskState.QUEUED, TaskState.AWAITING_APPROVAL) for r in runs):
        return "preparing"
    return None


def next_due_summary(template_id: str) -> Optional[str]:
    routine = routine_binding_registry.get_for_template(template_id)
    schedule = schedule_binding_registry.get_pending_for_template(template_id)
    candidates = []
    if routine and routine.enabled and routine.next_due_at:
        candidates.append(routine.next_due_at)
    if schedule and schedule.status == "pending":
        candidates.append(schedule.due_at)
    return min(candidates, key=_parse_iso) if candidates else None


def bindings_summary(template_id: str) -> List[str]:
    """Which binding kinds are still attached - used by the delete guard and the UI badges."""
    labels = []
    if routine_binding_registry.get_for_template(template_id):
        labels.append("routine")
    if schedule_binding_registry.get_pending_for_template(template_id):
        labels.append("schedule")
    return labels


def delete_template(template_id: str, requested_by: str = "operator") -> bool:
    """The one place that enforces "no bindings left, then owner" before a template is
    removed - a bare skeleton with no routine or schedule attached becomes deletable, per
    concept doc section A.1. Callable directly (tests, a future CLI) without duplicating the
    guard, and used by the DELETE /api/task-templates/{id} route.
    """
    bindings = bindings_summary(template_id)
    if bindings:
        raise TemplateHasBindingsError(template_id, bindings)
    return task_template_registry.delete_template(template_id, requested_by=requested_by)


def catalog_entry(template: TaskTemplate) -> Dict[str, Any]:
    routine = routine_binding_registry.get_for_template(template.template_id)
    schedule = schedule_binding_registry.get_pending_for_template(template.template_id)
    return {
        "template": template,
        "routine": routine,
        "schedule": schedule,
        "symbols": derive_symbols(routine, schedule),
        "runtime_status": derive_runtime_status(template.template_id),
        "next_due_at": next_due_summary(template.template_id),
        "can_delete": routine is None and schedule is None,
    }


def sorted_catalog(templates: List[TaskTemplate]) -> List[Dict[str, Any]]:
    """Status first (running > preparing > none), group second - the one fixed order the
    concept doc's 2026-08-18 correction leaves in place (section A.5)."""
    entries = [catalog_entry(t) for t in templates]
    entries.sort(key=lambda e: (
        STATUS_RANK.get(e["runtime_status"], 2),
        e["template"].group or "",
        e["template"].name.lower()
    ))
    return entries


# ---------------------------------------------------------------------------
# Execution: a template run is a real TaskMaster task, driven through the Sovereign Gateway
# exactly like every other tool call in this app (concept doc, section D).
# ---------------------------------------------------------------------------

def _build_prompt(template: TaskTemplate) -> tuple:
    if template.prompt_source == "library" and template.prompt_id:
        system_prompt, digest = chat_service.build_system_prompt(
            template.skill_ids, template.prompt_id, template.prompt_version
        )
    else:
        system_prompt, digest = chat_service.build_system_prompt(template.skill_ids)
        if template.custom_prompt_text:
            system_prompt += f"\n\n# Task instructions\n{template.custom_prompt_text}"
            digest.append("prompt source         custom inline text")
        else:
            digest.append("prompt source         none (empty custom prompt)")
    user_message = f"Execute task template '{template.name}' ({template.template_id})."
    return system_prompt, user_message, digest


async def _execute_template_call(system_prompt: str, user_message: str, model: str, config_digest: str = ""):
    """The tool body the gateway invokes. Same backend seam as the chat console's
    `_chat_completion` - live Gemini when GEMINI_API_KEY is set, the labelled
    deterministic-demo backend otherwise. Never called directly from a route."""
    return await chat_service.backend.complete(
        system_prompt=system_prompt, user_message=user_message, model=model, config_digest=config_digest
    )


def _settle_refused_run(task: TaskRecord, exc: Exception) -> None:
    """Close out a run the gateway refused by raising.

    A quarantine lock or a scope violation leaves `gateway.execute_tool_call()` as an exception,
    by design - a security verdict is a refusal, not a result object. But the task was already
    moved to IN_PROGRESS before the call, and nothing settled it afterwards, so the record sat
    at IN_PROGRESS for ever: the console showed a run in flight with nothing behind it, and
    releasing the agent did not change that (measured 2026-08-19, reproducing the operator
    report "it says in progress, but nothing is happening"). The refusal still propagates to
    the HTTP layer, which answers 403 as before; only the run's own state is settled first.
    """
    message = getattr(exc, "message", str(exc))
    run_log_bus.emit(task.task_id, f"refused by the gateway - {message}")
    run_log_bus.close(task.task_id)
    task_master.update_task_state(task.task_id, TaskState.FAILED, error=message)


async def enqueue_template(
    template_id: str,
    triggered_by: str = "manual",
    source_binding_id: Optional[str] = None,
    scheduled_for: Optional[str] = None
) -> TaskRecord:
    """Runs one template once: create the TaskRecord, then execute it through the gateway.

    `triggered_by` is "manual" for the console's "Enqueue now" button, "routine"/"schedule"
    for a binding fired by `fire_due()`, and "external" reserved for a future direct caller.

    A single-step template keeps running the exact path below, unchanged since before chains
    existed. A multi-step template (concept doc, section E.4 "Minimaler Ketten-Schnitt") is
    handed to `core/chain_runner.py` instead, once past the template-level approval gate and
    IN_PROGRESS transition both paths share.

    Every terminal return below also mirrors into `run_log_bus` under the run's `task_id`
    (concept doc, section C.7, variant (b), the web console) - a content-free status line plus
    `run_log_bus.close()`, so a `/ws/run/{task_id}` subscriber learns the run ended at the same
    moment `task_master` does. The chain delegation below is the one exception: it does not
    close the bus itself, because `chain_runner.run_chain()` already does that on every one of
    its own terminal returns.
    """
    template = task_template_registry.get_template(template_id)
    if not template:
        raise TemplateNotFoundError(template_id)

    task = task_master.create_task(
        name=f"Template run: {template.name}",
        assigned_agent=template.assigned_agent,
        input_data={"template_id": template_id, "triggered_by": triggered_by},
        source_template_id=template_id,
        source_binding_id=source_binding_id,
        triggered_by=triggered_by,
        scheduled_for=scheduled_for
    )
    run_log_bus.emit(
        task.task_id, f"task {task.task_id} created for template '{template.name}' ({template_id}), "
                      f"triggered_by={triggered_by}"
    )

    if template.requires_approval:
        # Same shape as the gateway's own ASK gate for `send_external_email`: the ticket is
        # created BECAUSE approval is required, not instead of it (concept doc, section A.4).
        # `requires_approval` lives on the template instance, unlike the gateway's tool-name
        # keyed permission registry, so it is honoured here before any model call is made -
        # for a chain, that means before its first step runs, not just its first model call.
        ticket = ticket_master.create_approval_ticket(
            title=f"Approval required: template run '{template.name}'",
            description=(
                f"Task template '{template.template_id}' requires approval and was queued "
                f"by '{triggered_by}'. Approve to run it through the gateway."
            ),
            agent_id=template.assigned_agent,
            tool_name=EXECUTE_TEMPLATE_TOOL,
            payload={"template_id": template_id, "task_id": task.task_id},
            priority=TicketPriority.NORMAL
        )
        run_log_bus.emit(task.task_id, f"template requires approval before running (ticket {ticket.ticket_id})")
        run_log_bus.close(task.task_id)
        return task_master.update_task_state(
            task.task_id, TaskState.AWAITING_APPROVAL, output_data={"ticket_id": ticket.ticket_id}
        )

    task_master.update_task_state(task.task_id, TaskState.IN_PROGRESS)

    # A research step reads pages before it answers, which the flat single-step path below knows
    # nothing about. Rather than a second copy of that orchestration, a lone research step is
    # handed to the same runner the multi-step path uses - it loops over one step just as well.
    needs_runner = len(template.steps) > 1 or template.steps[0].execution_pattern == "research"

    if needs_runner:
        if len(template.steps) > 1:
            run_log_bus.emit(task.task_id, f"multi-step template ({len(template.steps)} steps) - delegating to chain runner")
        else:
            run_log_bus.emit(
                task.task_id,
                f"research step reading {len(template.steps[0].research_urls)} page(s) - delegating to chain runner"
            )
        # Not closed here - chain_runner.run_chain() closes the bus itself on every one of its
        # own terminal returns (see its docstring). A raised gateway refusal is the exception:
        # it leaves through neither of those returns, so the run is settled here instead.
        try:
            return await chain_runner.run_chain(template, task)
        except (QuarantineLockError, SecurityViolationError) as exc:
            _settle_refused_run(task, exc)
            raise

    agent = lifecycle_manager.get_agent(template.assigned_agent)
    if agent is None:
        run_log_bus.emit(task.task_id, f"failed - agent '{template.assigned_agent}' is not registered")
        run_log_bus.close(task.task_id)
        return task_master.update_task_state(
            task.task_id, TaskState.FAILED, error=f"Agent '{template.assigned_agent}' is not registered"
        )

    system_prompt, user_message, digest = _build_prompt(template)
    run_log_bus.emit(
        task.task_id, f"step 1/1 via {template.assigned_agent}, model {settings.gemini_default_model} - started"
    )
    try:
        result = await gateway.execute_tool_call(
            agent=agent,
            tool_name=EXECUTE_TEMPLATE_TOOL,
            tool_args={
                "system_prompt": system_prompt,
                "user_message": user_message,
                "model": settings.gemini_default_model,
                "config_digest": "\n".join(digest)
            },
            tool_func=_execute_template_call
        )
    except (QuarantineLockError, SecurityViolationError) as exc:
        _settle_refused_run(task, exc)
        raise

    if not result.success:
        run_log_bus.emit(task.task_id, f"step 1/1: failed - {result.error}")
        run_log_bus.close(task.task_id)
        return task_master.update_task_state(task.task_id, TaskState.FAILED, error=result.error)

    if result.requires_approval:
        # The gateway's own permission registry - not the template flag above - marked
        # `execute_template` as ASK. The agent is already parked WAITING_APPROVAL; mirror
        # that on the run instead of reporting a false completion.
        ticket = ticket_master.create_approval_ticket(
            title=f"Gateway approval: template run '{template.name}'",
            description=f"The gateway's permission registry marked '{EXECUTE_TEMPLATE_TOOL}' as ASK.",
            agent_id=template.assigned_agent,
            tool_name=EXECUTE_TEMPLATE_TOOL,
            payload={"template_id": template_id, "task_id": task.task_id},
            priority=TicketPriority.NORMAL
        )
        run_log_bus.emit(task.task_id, f"step 1/1: awaiting approval (ticket {ticket.ticket_id})")
        run_log_bus.close(task.task_id)
        return task_master.update_task_state(
            task.task_id, TaskState.AWAITING_APPROVAL, output_data={"ticket_id": ticket.ticket_id}
        )

    reply = result.output
    run_log_bus.emit(task.task_id, f"step 1/1: completed (model={reply.model})")
    run_log_bus.emit(task.task_id, "task completed")
    run_log_bus.close(task.task_id)
    return task_master.update_task_state(
        task.task_id,
        TaskState.COMPLETED,
        output_data={
            "content": reply.content,
            "model": reply.model,
            "mode": reply.mode.value,
            "latency_s": reply.latency_s,
            "latency_simulated": reply.latency_simulated
        }
    )


# ---------------------------------------------------------------------------
# The Cloud Scheduler trigger (concept doc, section C.4 / D Phase 1).
# ---------------------------------------------------------------------------

async def _fire_routine(binding: RoutineBinding, now: datetime) -> Dict[str, Any]:
    if task_template_registry.get_template(binding.template_id) is None:
        return {"binding_id": binding.binding_id, "template_id": binding.template_id, "status": "orphaned"}

    due_at = _parse_iso(binding.next_due_at)
    task = await enqueue_template(
        binding.template_id, triggered_by="routine", source_binding_id=binding.binding_id,
        scheduled_for=binding.next_due_at
    )

    if binding.miss_policy == "catch_up":
        # Step forward exactly one interval from the occurrence that was just fired. If real
        # time is still ahead of that, the backlog is not drained yet: the next `/fire` call
        # enqueues the following occurrence, working through the backlog one run per call
        # instead of all at once inside a single HTTP request.
        following = next_after(binding.schedule_spec, due_at)
    else:
        # "skip": drop whatever was missed and resume counting from real current time.
        following = next_after(binding.schedule_spec, now)

    binding.next_due_at = _iso(following) if following else None
    routine_binding_registry.save(binding)
    return {
        "binding_id": binding.binding_id, "template_id": binding.template_id,
        "task_id": task.task_id, "status": "enqueued"
    }


async def _fire_schedule(binding: ScheduleBinding, now: datetime) -> Dict[str, Any]:
    due_at = _parse_iso(binding.due_at)
    missed = (now - due_at).total_seconds() > SCHEDULE_GRACE_SECONDS

    if missed and binding.miss_policy == "skip":
        binding.status = "skipped"
        schedule_binding_registry.save(binding)
        return {"binding_id": binding.binding_id, "template_id": binding.template_id, "status": "skipped"}

    task = await enqueue_template(
        binding.template_id, triggered_by="schedule", source_binding_id=binding.binding_id,
        scheduled_for=binding.due_at
    )
    binding.status = "fired"
    schedule_binding_registry.save(binding)
    return {
        "binding_id": binding.binding_id, "template_id": binding.template_id,
        "task_id": task.task_id, "status": "enqueued"
    }


async def fire_due(now: Optional[datetime] = None) -> Dict[str, Any]:
    """The one endpoint Cloud Scheduler calls. Safe to call as often as it likes.

    Idempotent by construction, not by a dedupe check: a RoutineBinding only fires while
    `next_due_at <= now`, and firing always recomputes `next_due_at` strictly forward, so a
    second call for the same tick sees a future `next_due_at` and does nothing. A
    ScheduleBinding only fires while `status == "pending"` and is flipped to fired/skipped in
    the very same call, so it cannot fire twice either.
    """
    now = now or _now()
    fired: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    not_due = 0

    for binding in routine_binding_registry.list_all():
        if not binding.enabled or not binding.next_due_at or _parse_iso(binding.next_due_at) > now:
            not_due += 1
            continue
        result = await _fire_routine(binding, now)
        (fired if result["status"] == "enqueued" else skipped).append(result)

    for binding in schedule_binding_registry.list_all():
        if binding.status != "pending":
            continue
        if _parse_iso(binding.due_at) > now:
            not_due += 1
            continue
        result = await _fire_schedule(binding, now)
        (fired if result["status"] == "enqueued" else skipped).append(result)

    return {"fired": fired, "skipped": skipped, "not_due": not_due, "checked_at": _iso(now)}
