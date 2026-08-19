"""Governance board: one read-only federation over the registers this fleet already keeps.

The board owns no data. Every number on it is recomputed from a live register on each read -
the permission registry the gateway itself consults, the policy engine's own constants, the
telemetry ring buffer, the lifecycle manager, the template registry and the ticket store. There
is deliberately no `governance` store, no cached snapshot and no "board state" written anywhere:
a second copy of a verdict is a copy that can disagree with the gate that issued it, and a
governance view that disagrees with the gate is worse than no view at all. Same principle the
task catalogue already follows for its derived symbols and colours (`uas/routines.py`) - derive,
never store.

Every function here takes its input as a parameter and returns plain data; `build_board()` is
the only place that reaches for the module singletons. That keeps the aggregations testable
against synthetic registers, and it is why the tests below never depend on what a previous test
happened to leave in the shared fleet or span buffer.
"""

import time
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sentinel_fleet.chat.backends import MODEL_USAGE_EVENT
from sentinel_fleet.conductor.lifecycle import lifecycle_manager
from sentinel_fleet.core.gateway import gateway
from sentinel_fleet.core.identity import AgentIdentity, AgentStatus
from sentinel_fleet.core.permissions import PermissionAction, PermissionRegistry
from sentinel_fleet.core.policies import (
    DEFAULT_MAX_CONSECUTIVE_STEPS,
    MATH_TOLERANCE_EUR,
    UST_REQUIRED_FIELDS,
)
from sentinel_fleet.core.telemetry import SpanRecord, telemetry
from sentinel_fleet.uas import routines
from sentinel_fleet.uas.task_templates import TaskTemplate, task_template_registry
from sentinel_fleet.uas.ticket_master import Ticket, TicketStatus, ticket_master

# Span statuses the gateway writes when a call did not go through. Kept as one set so the board,
# the ledger colour and the "refused" count all mean exactly the same thing.
REFUSING_STATUSES = frozenset({"BLOCKED", "DENIED", "SECURITY_VIOLATION", "ERROR"})
HOLDING_STATUS = "WAITING_FOR_USER_APPROVAL"

# Span events that carry evidence of a check having run, as opposed to the verdict itself.
# `model_usage` is deliberately not here - it is metering, and has its own section.
EVIDENCE_EVENTS = ("privacy_screen", "model_armor_sanitized", "web_page_inspected")

# The order `SovereignGateway.execute_tool_call` applies its checks in. Descriptive, and pointed
# at the source so a reader can verify it rather than take the board's word for it.
GATE_SEQUENCE = [
    {"stage": "Quarantine", "detail": "A quarantined identity is refused before anything else runs."},
    {"stage": "Least privilege", "detail": "The tool must be inside the calling identity's own scope."},
    {"stage": "Model Armor", "detail": "Arguments are scanned for injection and PII before the tool sees them."},
    {"stage": "Permission registry", "detail": "The tool's own verdict: allow, ask (human signoff) or deny."},
    {"stage": "Execute", "detail": "Only now does the tool body run, under the span the ledger shows."},
]
GATE_SEQUENCE_SOURCE = "core/gateway.py :: SovereignGateway.execute_tool_call"

_RACE_LANE_PREFIX = "agent:race-lane-"


# ---------------------------------------------------------------------------
# Policies & scopes
# ---------------------------------------------------------------------------

def policy_catalogue() -> List[Dict[str, Any]]:
    """What the policy engine checks, with the real thresholds imported from it.

    The field list and both limits come from `core/policies.py`'s own constants, so a changed
    tolerance shows up here without anyone remembering to update a board.
    """
    return [
        {
            "name": "§ 14 UStG mandatory fields",
            "source": "core/policies.py :: PolicyEngine.evaluate_tax_compliance",
            "outcome": "block",
            "summary": f"{len(UST_REQUIRED_FIELDS)} fields must be present on every invoice.",
            "checks": [{"field": field, "violation": message} for field, message in UST_REQUIRED_FIELDS],
        },
        {
            "name": "Arithmetic integrity",
            "source": "core/policies.py :: PolicyEngine.evaluate_tax_compliance",
            "outcome": "block",
            "summary": (
                f"net + tax must equal the stated gross within ±{MATH_TOLERANCE_EUR:.2f} EUR. "
                "The tolerance absorbs per-line rounding, not a wrong total."
            ),
            "checks": [],
        },
        {
            "name": "Loop prevention / step budget",
            "source": "core/policies.py :: PolicyEngine.evaluate_step_budget",
            "outcome": "block",
            "summary": (
                f"An agent may take at most {DEFAULT_MAX_CONSECUTIVE_STEPS} consecutive gateway "
                "steps without the run state advancing."
            ),
            "checks": [],
        },
    ]


def _agent_groups(agents: Sequence[AgentIdentity]) -> List[List[AgentIdentity]]:
    """Fleet order, with the race lanes folded into one row when they are truly identical.

    Four lanes exist so concurrent races do not queue behind one agent lock (`chat/service.py`),
    not because they are governed differently - four repeated rows would cost a quarter of the
    matrix and say nothing. They only collapse while scope and status actually match; the moment
    one lane is quarantined, it gets its own row again and the difference stays visible.
    """
    lanes = [a for a in agents if a.agent_id.startswith(_RACE_LANE_PREFIX)]
    collapsible = len(lanes) > 1 and len({(frozenset(a.allowed_tools), a.status) for a in lanes}) == 1

    groups: List[List[AgentIdentity]] = []
    lanes_placed = False
    for agent in agents:
        if agent.agent_id.startswith(_RACE_LANE_PREFIX) and collapsible:
            if not lanes_placed:
                groups.append(lanes)
                lanes_placed = True
            continue
        groups.append([agent])
    return groups


def permission_matrix(agents: Sequence[AgentIdentity], registry: PermissionRegistry) -> Dict[str, Any]:
    """Agent × tool: who may call what, and what the registry says when they do.

    Two independent controls meet in every cell, and the board keeps them apart because they
    fail differently: least privilege decides whether this identity carries the tool at all
    (a violation quarantines the agent), while the permission registry decides what happens
    when a scoped call arrives (allow, hold for a human, or refuse outright).

    The verdict's `source` matters as much as the verdict: a tool with no rule of its own falls
    through to the registry default, and several tools agents really carry do exactly that. That
    is a governance fact worth seeing, not a detail to smooth over, so it is a column here.
    """
    scoped_tools = {tool for agent in agents for tool in agent.allowed_tools if tool != "*"}
    rule_tools = {rule.tool_pattern for rule in registry.rules if "*" not in rule.tool_pattern}
    tool_names = sorted(scoped_tools | rule_tools)

    # One tool per matrix row, one identity per column - the transpose of the obvious layout,
    # and the readable one: a tool's verdict and its reason are text and belong in a row, while
    # "does this identity hold it" is a single mark and belongs in a narrow column.
    groups = _agent_groups(agents)
    identities = [
        {
            "label": group[0].name if len(group) == 1 else f"{len(group)} race lanes",
            "agent_id": group[0].agent_id if len(group) == 1
                        else f"{group[0].agent_id} … {group[-1].agent_id}",
            "members": [a.agent_id for a in group],
            "collapsed": len(group) > 1,
            "role": group[0].role.value,
            "status": group[0].status.value,
            "quarantine_reason": group[0].quarantine_reason,
            "scope_size": len(group[0].allowed_tools),
        }
        for group in groups
    ]

    rows = []
    for tool in tool_names:
        verdict = registry.explain(tool)
        cells = []
        for group, identity in zip(groups, identities):
            granted = group[0].is_tool_scoped(tool)
            cells.append({
                "agent_id": identity["agent_id"],
                "granted": granted,
                "state": verdict.action.value if granted else "out_of_scope",
                "title": (
                    f"{identity['agent_id']} may call {tool} - registry verdict: "
                    f"{verdict.action.value} ({verdict.source})"
                    if granted else
                    f"{tool} is outside {identity['agent_id']}'s least-privilege scope"
                ),
            })
        holders = [cell["agent_id"] for cell in cells if cell["granted"]]
        rows.append({
            "tool": tool,
            "action": verdict.action.value,
            "source": verdict.source,
            "reason": verdict.reason,
            "matched_pattern": verdict.matched_pattern,
            "holders": holders,
            "holder_count": len(holders),
            # A tool no identity carries is defence in depth, not dead config - say so, rather
            # than letting an empty row read as an oversight.
            "unheld": not holders,
            "cells": cells,
        })

    granted_cells = [(row, cell) for row in rows for cell in row["cells"] if cell["granted"]]
    return {
        "identities": identities,
        "rows": rows,
        "summary": {
            "agents": len(agents),
            "columns": len(identities),
            "tools": len(rows),
            "grants": len(granted_cells),
            "cells": len(rows) * len(identities),
            "held_at_gate": sum(1 for _, cell in granted_cells if cell["state"] == PermissionAction.ASK.value),
            "denied": sum(1 for _, cell in granted_cells if cell["state"] == PermissionAction.DENY.value),
            # Grants resting on the registry's fall-through rather than a rule written for them.
            "on_default": sum(1 for row in rows for cell in row["cells"]
                              if cell["granted"] and row["source"] == "default"),
            "unheld_tools": sum(1 for row in rows if row["unheld"]),
        },
    }


# ---------------------------------------------------------------------------
# Decisions & evidence
# ---------------------------------------------------------------------------

def _span_tool(span: SpanRecord) -> Optional[str]:
    tool = span.attributes.get("tool")
    return tool if isinstance(tool, str) else None


def _verdict_class(status: str) -> str:
    if status in REFUSING_STATUSES:
        return "refused"
    if status == HOLDING_STATUS:
        return "held"
    if status == "OK":
        return "passed"
    return "other"


def aggregate_decisions(spans: Iterable[SpanRecord], recent_limit: int = 12) -> Dict[str, Any]:
    """Roll the gate ledger up by verdict, agent and tool.

    Counts the whole retained buffer, not the dashboard's tail - but the buffer is a ring, so
    every count here is "of the last N retained rows", never all-time. The board says as much
    next to the numbers; `telemetry.get_exported_span_total()` is the figure that does not
    forget, and it travels in the board's `window`.
    """
    rows = list(spans)

    by_status = Counter(span.status for span in rows)
    by_class = Counter(_verdict_class(span.status) for span in rows)

    agents: Dict[str, Counter] = {}
    tools: Dict[str, Counter] = {}
    for span in rows:
        agents.setdefault(span.agent_id, Counter())[_verdict_class(span.status)] += 1
        tool = _span_tool(span)
        if tool:
            tools.setdefault(tool, Counter())[_verdict_class(span.status)] += 1

    def _breakdown(source: Dict[str, Counter], key: str) -> List[Dict[str, Any]]:
        out = [
            {
                key: name,
                "total": sum(counts.values()),
                "passed": counts["passed"],
                "held": counts["held"],
                "refused": counts["refused"],
            }
            for name, counts in source.items()
        ]
        out.sort(key=lambda entry: (-entry["total"], entry[key]))
        return out

    recent = [
        {
            "span_id": span.span_id,
            "at": span.start_time,
            "operation": span.name,
            "tool": _span_tool(span),
            "agent_id": span.agent_id,
            "status": span.status,
            "verdict": _verdict_class(span.status),
            "duration_s": round((span.end_time or span.start_time) - span.start_time, 3),
            "error": span.error_message,
        }
        for span in reversed(rows[-recent_limit:])
    ]

    return {
        "total": len(rows),
        "by_verdict": {name: by_class[name] for name in ("passed", "held", "refused", "other")},
        "by_status": [{"status": s, "count": c} for s, c in by_status.most_common()],
        "by_agent": _breakdown(agents, "agent_id"),
        "by_tool": _breakdown(tools, "tool"),
        "recent": recent,
        "tool_calls": sum(1 for span in rows if _span_tool(span)),
    }


def evidence_trail(spans: Iterable[SpanRecord], limit: int = 15) -> Dict[str, Any]:
    """The checks that left a trace on a ledger row, newest first.

    A verdict says what the gate decided; these events say what it looked at - the privacy screen
    on an outbound document, the armor scan on tool arguments, the inspection of a fetched page.
    """
    entries = []
    counts: Counter = Counter()
    for span in spans:
        for event in span.events:
            name = event.get("name")
            if name not in EVIDENCE_EVENTS:
                continue
            counts[name] += 1
            payload = event.get("payload") or {}
            subject = payload.get("document") or payload.get("url") or _span_tool(span) or span.name
            details = ", ".join(
                f"{key} {value}" for key, value in payload.items()
                if key not in ("document", "url") and value not in ("", None)
            )
            entries.append({
                "at": event.get("timestamp", span.start_time),
                "event": name,
                "agent_id": span.agent_id,
                "operation": span.name,
                "subject": str(subject),
                "details": details,
                "verdict": str(payload.get("verdict") or ""),
            })

    entries.sort(key=lambda entry: entry["at"], reverse=True)
    return {
        "counts": [{"event": name, "count": count} for name, count in counts.most_common()],
        "total": sum(counts.values()),
        "recent": entries[:limit],
    }


def usage_summary(spans: Iterable[SpanRecord]) -> Dict[str, Any]:
    """Token spend of the model calls that ran under the gateway.

    Only a live provider response emits the underlying event, and only inside a gateway-bound
    span - so this section measures governed, metered calls, and stays honestly empty in demo
    mode rather than showing a plausible zero that looks like "no spend". Each column sums the
    calls that actually reported that field; a provider that omits one leaves it out of that sum.
    """
    calls = 0
    totals: Counter = Counter()
    reported: Counter = Counter()
    per_model: Dict[str, Counter] = {}

    for span in spans:
        for event in span.events:
            if event.get("name") != MODEL_USAGE_EVENT:
                continue
            payload = event.get("payload") or {}
            calls += 1
            model = str(payload.get("model") or "unknown")
            bucket = per_model.setdefault(model, Counter())
            bucket["calls"] += 1
            for field in ("prompt_tokens", "output_tokens", "total_tokens"):
                value = payload.get(field)
                if isinstance(value, int):
                    totals[field] += value
                    reported[field] += 1
                    bucket[field] += value

    models = [
        {
            "model": model,
            "calls": counts["calls"],
            "prompt_tokens": counts["prompt_tokens"],
            "output_tokens": counts["output_tokens"],
            "total_tokens": counts["total_tokens"],
        }
        for model, counts in sorted(per_model.items(), key=lambda item: -item[1]["calls"])
    ]
    return {
        "metered_calls": calls,
        "prompt_tokens": totals["prompt_tokens"],
        "output_tokens": totals["output_tokens"],
        "total_tokens": totals["total_tokens"],
        "reported": {field: reported[field] for field in ("prompt_tokens", "output_tokens", "total_tokens")},
        "by_model": models,
    }


# ---------------------------------------------------------------------------
# Locks & quarantine
# ---------------------------------------------------------------------------

def agent_states(agents: Sequence[AgentIdentity], spans: Iterable[SpanRecord]) -> Dict[str, Any]:
    """Who is running, who is held at the gate, who is locked out - and when it happened.

    The lifecycle manager keeps no timestamp on a status change, so the board does not invent
    one: it looks for the newest refusing row this agent has on the retained ledger and reports
    that, labelled as what it is. When the ring buffer has already rolled past it, the field
    stays empty instead of guessing.
    """
    last_refusal: Dict[str, SpanRecord] = {}
    for span in spans:
        if span.status in REFUSING_STATUSES:
            last_refusal[span.agent_id] = span

    rows = []
    for agent in agents:
        marker = last_refusal.get(agent.agent_id)
        rows.append({
            "agent_id": agent.agent_id,
            "name": agent.name,
            "role": agent.role.value,
            "status": agent.status.value,
            "quarantine_reason": agent.quarantine_reason,
            "consecutive_steps": agent.consecutive_steps,
            "step_budget": DEFAULT_MAX_CONSECUTIVE_STEPS,
            "last_refusal_at": marker.start_time if marker else None,
            "last_refusal_status": marker.status if marker else "",
            "last_refusal_operation": marker.name if marker else "",
        })

    by_status = Counter(row["status"] for row in rows)
    held = [row for row in rows if row["status"] != AgentStatus.IDLE.value]
    return {
        "rows": rows,
        "flagged": held,
        "by_status": [{"status": status, "count": count} for status, count in by_status.most_common()],
        "quarantined": by_status.get(AgentStatus.QUARANTINED.value, 0),
        "awaiting_approval": by_status.get(AgentStatus.WAITING_APPROVAL.value, 0),
    }


# ---------------------------------------------------------------------------
# Tasks & plans
# ---------------------------------------------------------------------------

def plan_catalogue(templates: Sequence[TaskTemplate]) -> Dict[str, Any]:
    """Standing plans: every template with its steps, its agents and its bindings.

    Unfiltered on purpose. The Fleet tab shows one viewer's list and honours what that viewer
    hid from it (`removed_by`); a governance view that inherited a personal hide list would
    under-report the fleet's real standing work.
    """
    rows = []
    for entry in routines.sorted_catalog(list(templates)):
        template = entry["template"]
        steps = sorted(template.steps, key=lambda step: step.position)
        rows.append({
            "template_id": template.template_id,
            "name": template.name,
            "owner": template.owner,
            "visibility": template.visibility,
            "group": template.group,
            "requires_approval": template.requires_approval,
            "step_count": len(steps),
            "steps": [
                {
                    "position": step.position,
                    "step_id": step.step_id,
                    "assigned_agent": step.assigned_agent,
                    "execution_pattern": step.execution_pattern,
                    "prompt_source": step.prompt_source,
                    "skill_count": len(step.skill_ids),
                    "race_models": list(step.race_models),
                }
                for step in steps
            ],
            "agents": sorted({step.assigned_agent for step in steps}),
            "bindings": [kind for kind, present in
                         (("routine", entry["routine"] is not None), ("schedule", entry["schedule"] is not None))
                         if present],
            "runtime_status": entry["runtime_status"],
            "next_due_at": entry["next_due_at"],
        })

    return {
        "rows": rows,
        "summary": {
            "total": len(rows),
            "chained": sum(1 for row in rows if row["step_count"] > 1),
            "gated": sum(1 for row in rows if row["requires_approval"]),
            "bound": sum(1 for row in rows if row["bindings"]),
            "running": sum(1 for row in rows if row["runtime_status"] == "running"),
        },
    }


# ---------------------------------------------------------------------------
# Tickets & approvals
# ---------------------------------------------------------------------------

def ticket_catalogue(tickets: Sequence[Ticket], limit: int = 20) -> Dict[str, Any]:
    """Human signoff, open and settled - the record of what a person actually decided."""

    def _row(ticket: Ticket) -> Dict[str, Any]:
        return {
            "ticket_id": ticket.ticket_id,
            "title": ticket.title,
            "agent_id": ticket.agent_id,
            "tool_name": ticket.tool_name,
            "priority": ticket.priority.value,
            "status": ticket.status.value,
            "created_at": ticket.created_at,
            "resolved_at": ticket.resolved_at,
            "resolution_comment": ticket.resolution_comment or "",
        }

    ordered = sorted(tickets, key=lambda ticket: ticket.created_at, reverse=True)
    pending = [_row(t) for t in ordered if t.status == TicketStatus.PENDING_APPROVAL]
    decided = [_row(t) for t in ordered if t.status != TicketStatus.PENDING_APPROVAL]
    by_status = Counter(t.status.value for t in ordered)

    return {
        "pending": pending[:limit],
        "decided": decided[:limit],
        "summary": {
            "total": len(ordered),
            "pending": len(pending),
            "approved": by_status.get(TicketStatus.APPROVED.value, 0),
            "rejected": by_status.get(TicketStatus.REJECTED.value, 0),
            "resolved": by_status.get(TicketStatus.RESOLVED.value, 0),
        },
    }


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------

def build_board() -> Dict[str, Any]:
    """Read every register once and hand back the whole board.

    The single place in this module that touches a singleton. `gateway.permissions` rather than
    a fresh `PermissionRegistry()`: the board must answer from the same object the gateway
    consults, not from a second instance that merely starts out identical.
    """
    agents = lifecycle_manager.list_fleet()
    spans = list(telemetry.spans)

    return {
        "generated_at": time.time(),
        "window": {
            "retained_spans": len(spans),
            "retention_limit": telemetry.spans.maxlen,
            "exported_total": telemetry.get_exported_span_total(),
            "otel_enabled": telemetry.otel_enabled,
        },
        "gate_sequence": GATE_SEQUENCE,
        "gate_sequence_source": GATE_SEQUENCE_SOURCE,
        "permissions": permission_matrix(agents, gateway.permissions),
        "policies": policy_catalogue(),
        "decisions": aggregate_decisions(spans),
        "evidence": evidence_trail(spans),
        "usage": usage_summary(spans),
        "agents": agent_states(agents, spans),
        "plans": plan_catalogue(task_template_registry.list_all()),
        "tickets": ticket_catalogue(ticket_master.list_all()),
    }
