"""Chain runner: executes a TaskTemplate with more than one Step (concept doc, section E.4
"Minimaler Ketten-Schnitt"). A single-step template never reaches this module -
`routines.enqueue_template()` keeps running that path exactly as it did before chains existed;
`run_chain()` only handles `len(template.steps) > 1`.

Two execution patterns only, enforced by `Step`'s own validator (`uas/task_templates.py`):
- "single" runs one model call through the Sovereign Gateway under the same `execute_template`
  tool name and PoLP scope as the pre-chain single-step path.
- "race" reuses `ChatService.race()` unmodified - not a reimplementation - because the race-lane
  agent identities (`agent:race-lane-1..4`, `chat/service.py`) are scoped for `chat_completion`,
  not `execute_template`: a hand-rolled race under the template tool name would quarantine every
  lane on its first call. Per-lane identity separation (so lanes do not serialise behind one
  agent's gateway lock) is a hard-won property of that existing code, kept as-is.

`input_spec` is fixed to "previous_output" for the whole minimal cut (`Step`'s validator
rejects any other value): every step after the first receives the previous step's output
injected as extra context - a system-prompt block for a "single" step, or the user message for
a "race" step, because `ChatService.race()` builds its own system prompt from
skill_ids/prompt_id/prompt_version and has no system-prompt slot to inject into.
"""

import logging
from typing import Any, Dict, List, Optional

from sentinel_fleet.chat.models import ChatMode
from sentinel_fleet.chat.service import chat_service
from sentinel_fleet.conductor.lifecycle import lifecycle_manager
from sentinel_fleet.core.config import settings
from sentinel_fleet.core.gateway import gateway
from sentinel_fleet.core.telemetry import telemetry
from sentinel_fleet.uas.task_master import TaskRecord, TaskState, task_master
from sentinel_fleet.uas.task_templates import EXECUTE_TEMPLATE_TOOL, Step, TaskTemplate
from sentinel_fleet.uas.ticket_master import TicketPriority, ticket_master

logger = logging.getLogger(__name__)

# Synthetic identity for the bracketing "chain:run" span (concept doc, section E.4: "Jeder
# Step-Lauf landet nachvollziehbar im Gate-Ledger/Telemetrie"). Each step's own model call
# already opens its own gateway span under its own agent; this one groups them into one visible
# run in the telemetry tab. Not a registered agent - telemetry.start_span() only stores this as
# a free-text label, the same way ChatService.race() labels its own span with CHAT_AGENT_ID.
CHAIN_RUNNER_AGENT_ID = "agent:chain-runner"


async def _execute_step_call(system_prompt: str, user_message: str, model: str, config_digest: str = ""):
    """The tool body the gateway invokes for a "single" step - same backend seam as the
    pre-chain single-step path and the chat console (`chat_service.backend`). Never called
    directly outside `gateway.execute_tool_call()`.
    """
    return await chat_service.backend.complete(
        system_prompt=system_prompt, user_message=user_message, model=model, config_digest=config_digest
    )


def _build_step_prompt(step: Step, previous_output: Optional[str]) -> tuple:
    if step.prompt_source == "library" and step.prompt_id:
        system_prompt, digest = chat_service.build_system_prompt(
            step.skill_ids, step.prompt_id, step.prompt_version
        )
    else:
        system_prompt, digest = chat_service.build_system_prompt(step.skill_ids)
        if step.custom_prompt_text:
            system_prompt += f"\n\n# Task instructions\n{step.custom_prompt_text}"
            digest.append("prompt source         custom inline text")
        else:
            digest.append("prompt source         none (empty custom prompt)")
    if previous_output is not None:
        system_prompt += f"\n\n# Output of the previous step\n{previous_output}"
        digest.append("previous step output   injected as context")
    return system_prompt, digest


async def _run_single_step(step: Step, previous_output: Optional[str]) -> Dict[str, Any]:
    agent = lifecycle_manager.get_agent(step.assigned_agent)
    if agent is None:
        return {"success": False, "error": f"agent '{step.assigned_agent}' is not registered"}

    system_prompt, digest = _build_step_prompt(step, previous_output)
    user_message = f"Execute step '{step.step_id}'."
    result = await gateway.execute_tool_call(
        agent=agent,
        tool_name=EXECUTE_TEMPLATE_TOOL,
        tool_args={
            "system_prompt": system_prompt,
            "user_message": user_message,
            "model": settings.gemini_default_model,
            "config_digest": "\n".join(digest)
        },
        tool_func=_execute_step_call
    )
    if not result.success:
        return {"success": False, "error": result.error}
    if result.requires_approval:
        # The gateway's own permission registry - not evaluated per template like
        # `requires_approval` above the loop - marked `execute_template` as ASK. Unreachable
        # with this deployment's default PermissionRegistry (`execute_template` is ALLOW,
        # `core/permissions.py`), handled defensively for symmetry with the pre-chain
        # single-step path, which has the identical, equally unreached branch.
        return {"success": True, "requires_approval": True}
    reply = result.output
    return {"success": True, "content": reply.content, "model": reply.model, "mode": reply.mode.value}


async def _run_race_step(step: Step, previous_output: Optional[str], template_name: str) -> Dict[str, Any]:
    """Reuses `ChatService.race()` as-is (concept doc, section E.4: "near-unmodified reuse of
    ChatService.race(), bound to a step instead of a chat message"). `race()`
    builds its own system prompt from skill_ids/prompt_id/prompt_version, so a step's custom
    prompt text and the previous step's output both travel in the *message* instead - the same
    slot a chat operator would type into.

    A race is not automatically a success: `race()` never raises for a blocked or failed lane,
    it records `mode=BLOCKED`/`error` on that lane and returns normally (concept doc review
    finding, 2026-08-18). Forwarding refusal boilerplate to the next step as if it were real
    content would turn a blocked step into a silent pass, so only lanes that actually produced
    content are used; the step fails outright if none did.
    """
    message_parts = []
    if step.prompt_source != "library" and step.custom_prompt_text:
        message_parts.append(step.custom_prompt_text)
    if previous_output is not None:
        message_parts.append(f"# Output of the previous step\n{previous_output}")
    message = "\n\n".join(message_parts) or f"Execute step '{step.step_id}'."

    session = chat_service.create_session(title=f"Chain step race: {template_name} / {step.step_id}")
    try:
        _, record = await chat_service.race(
            message=message,
            models=step.race_models,
            judge=False,
            session_id=session.session_id,
            skill_ids=step.skill_ids,
            prompt_id=step.prompt_id if step.prompt_source == "library" else "",
            prompt_version=step.prompt_version if step.prompt_source == "library" else ""
        )
    except ValueError as exc:
        # race() itself validates lane count (2..MAX_RACE_LANES) - Step's own validator already
        # enforces the same bound, so this is a defensive backstop, not the primary guard.
        return {"success": False, "error": f"race step '{step.step_id}': {exc}"}

    usable = [lane for lane in record.lanes if lane.mode is not ChatMode.BLOCKED and not lane.error]
    if not usable:
        reason = "blocked by Model Armor" if any(l.mode is ChatMode.BLOCKED for l in record.lanes) else "every lane failed"
        return {
            "success": False,
            "error": f"race step '{step.step_id}': {reason}",
            "session_id": session.session_id,
            "race_id": record.race_id
        }

    content = "\n\n".join(f"## {lane.model}\n{lane.content}" for lane in usable)
    return {
        "success": True,
        "content": content,
        "model": ",".join(lane.model for lane in usable),
        "mode": "race",
        "session_id": session.session_id,
        "race_id": record.race_id
    }


async def run_chain(template: TaskTemplate, task: TaskRecord) -> TaskRecord:
    """Runs every step of `template` in position order against the already-created,
    already-IN_PROGRESS `task` (both handled by the caller, `routines.enqueue_template()`, the
    same way for a single-step run). Each step's output becomes the next step's
    `previous_output` context - `input_spec` is fixed to "previous_output" for the whole
    minimal cut, enforced by `Step`'s own validator, so there is nothing else to branch on here.
    """
    steps = sorted(template.steps, key=lambda s: s.position)
    step_records: List[Dict[str, Any]] = []
    previous_output: Optional[str] = None

    span = telemetry.start_span(
        "chain:run", CHAIN_RUNNER_AGENT_ID, {"template_id": template.template_id, "steps": str(len(steps))}
    )

    for index, step in enumerate(steps):
        if step.execution_pattern == "race":
            outcome = await _run_race_step(step, previous_output, template.name)
        else:
            outcome = await _run_single_step(step, previous_output)

        if outcome.get("requires_approval"):
            telemetry.end_span(span, status="WAITING_FOR_USER_APPROVAL")
            ticket = ticket_master.create_approval_ticket(
                title=f"Gateway approval: chain step '{step.step_id}' of '{template.name}'",
                description=f"The gateway's permission registry marked '{EXECUTE_TEMPLATE_TOOL}' as ASK.",
                agent_id=step.assigned_agent,
                tool_name=EXECUTE_TEMPLATE_TOOL,
                payload={"template_id": template.template_id, "task_id": task.task_id, "step_id": step.step_id},
                priority=TicketPriority.NORMAL
            )
            step_records.append({"step_id": step.step_id, "status": "awaiting_approval"})
            return task_master.update_task_state(
                task.task_id, TaskState.AWAITING_APPROVAL,
                output_data={"ticket_id": ticket.ticket_id, "steps": step_records}
            )

        if not outcome["success"]:
            telemetry.end_span(span, status="ERROR", error=outcome["error"])
            step_records.append({"step_id": step.step_id, "status": "failed", "error": outcome["error"]})
            return task_master.update_task_state(
                task.task_id, TaskState.FAILED,
                error=f"step {step.step_id} ({index + 1}/{len(steps)}): {outcome['error']}",
                output_data={"steps": step_records}
            )

        record: Dict[str, Any] = {
            "step_id": step.step_id,
            "status": "completed",
            "execution_pattern": step.execution_pattern,
            "model": outcome.get("model"),
            "content": outcome["content"]
        }
        if "race_id" in outcome:
            record["session_id"] = outcome["session_id"]
            record["race_id"] = outcome["race_id"]
        step_records.append(record)
        previous_output = outcome["content"]

    telemetry.end_span(span, status="OK")
    return task_master.update_task_state(
        task.task_id, TaskState.COMPLETED,
        output_data={"content": previous_output, "steps": step_records}
    )
