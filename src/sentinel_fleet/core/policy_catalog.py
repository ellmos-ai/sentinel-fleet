"""Federated policy catalogue with one writable user slot.

Permission rules and code-level policy checks are projected on every read.  Only user-authored
entries are stored here; the catalogue therefore cannot drift into a second copy of the gateway
or the PolicyEngine.
"""

import time
import uuid
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from sentinel_fleet.core.binding_rules import BindingAction, explain_binding
from sentinel_fleet.core.permissions import PermissionAction, PermissionRegistry
from sentinel_fleet.core.policies import (
    DEFAULT_MAX_CONSECUTIVE_STEPS,
    MATH_TOLERANCE_EUR,
    UST_REQUIRED_FIELDS,
)
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.users import UserIdentity, UserRegistry, user_registry


class PolicyType(str, Enum):
    RULE = "rule"
    PREFERENCE = "preference"
    DECISION = "decision"
    PLAN_BINDING = "plan_binding"


class Enforcement(str, Enum):
    MANDATORY = "mandatory"
    ENFORCING = "enforcing"
    ADVISORY = "advisory"


class Policy(BaseModel):
    policy_id: str
    title: str
    statement: str
    type: PolicyType
    enforcement: Enforcement
    enforced_by: str = "advisory-only"
    source: str = "user-slot"
    source_ref: Optional[str] = None
    owner: str
    org_mandated: bool = False
    visibility: str = "own"
    allowed_roles: List[str] = Field(default_factory=list)
    removed_by: List[str] = Field(default_factory=list)
    source_decisions: List[str] = Field(default_factory=list)
    workflow_ref: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @field_validator("title", "statement")
    @classmethod
    def _text_is_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Policy title and statement must not be empty.")
        return value

    @model_validator(mode="after")
    def _coherent_shape(self) -> "Policy":
        if (self.type == PolicyType.PLAN_BINDING) != bool(self.workflow_ref):
            raise ValueError("workflow_ref is required only for type='plan_binding'.")
        if self.org_mandated and self.enforcement == Enforcement.ADVISORY:
            raise ValueError("An organization-mandated policy cannot be advisory-only.")
        return self


class PolicyBinding(BaseModel):
    binding_id: str
    policy_id: str
    target_kind: str
    target_id: str
    scope_level: str
    target_user_id: Optional[str] = None
    target_department_id: Optional[str] = None
    bound_by: str
    state: str = "active"
    verdict_reason: str
    triggered_rule: str
    applied_rules: List[str] = Field(default_factory=list)
    decisive_rule: str = ""
    forwarded_ticket_id: Optional[str] = None
    forwarded_to_role: Optional[str] = None
    forwarded_to_user: Optional[str] = None
    removal_state: Optional[str] = None
    removal_ticket_id: Optional[str] = None
    removal_forwarded_to_role: Optional[str] = None
    removal_forwarded_to_user: Optional[str] = None
    created_at: float = Field(default_factory=time.time)


class PolicyCatalog:
    def __init__(self):
        self._user_slot = get_store("user_policies", Policy)
        self._bindings = get_store("policy_bindings", PolicyBinding)

    @staticmethod
    def _permission_entries(registry: PermissionRegistry) -> List[Policy]:
        entries = []
        for rule in registry.rules:
            entries.append(Policy(
                policy_id=f"permission:{rule.tool_pattern}",
                title=f"Tool permission: {rule.tool_pattern}",
                statement=rule.reason or f"Gateway verdict is {rule.action.value}.",
                type=PolicyType.RULE,
                enforcement=Enforcement.MANDATORY if rule.action != PermissionAction.ALLOW else Enforcement.ENFORCING,
                enforced_by="gateway.permissions",
                source="permission-registry",
                source_ref=f"core/permissions.py::{rule.tool_pattern}",
                owner="organization",
                org_mandated=True,
                visibility="organization",
            ))
        return entries

    @staticmethod
    def _engine_entries() -> List[Policy]:
        return [
            Policy(
                policy_id="engine:ustg-required-fields",
                title="§ 14 UStG mandatory fields",
                statement=f"{len(UST_REQUIRED_FIELDS)} required fields must be present.",
                type=PolicyType.RULE,
                enforcement=Enforcement.MANDATORY,
                enforced_by="policy_engine",
                source="policy-engine",
                source_ref="core/policies.py::PolicyEngine.evaluate_tax_compliance",
                owner="organization", org_mandated=True, visibility="organization",
            ),
            Policy(
                policy_id="engine:arithmetic-integrity",
                title="Arithmetic integrity",
                statement=f"net + tax must match gross within ±{MATH_TOLERANCE_EUR:.2f} EUR.",
                type=PolicyType.RULE,
                enforcement=Enforcement.MANDATORY,
                enforced_by="policy_engine",
                source="policy-engine",
                source_ref="core/policies.py::PolicyEngine.evaluate_tax_compliance",
                owner="organization", org_mandated=True, visibility="organization",
            ),
            Policy(
                policy_id="engine:step-budget",
                title="Loop prevention / step budget",
                statement=f"At most {DEFAULT_MAX_CONSECUTIVE_STEPS} consecutive gateway steps.",
                type=PolicyType.RULE,
                enforcement=Enforcement.MANDATORY,
                enforced_by="policy_engine",
                source="policy-engine",
                source_ref="core/policies.py::PolicyEngine.evaluate_step_budget",
                owner="organization", org_mandated=True, visibility="organization",
            ),
        ]

    def list_all(self, registry: PermissionRegistry) -> List[Policy]:
        entries = self._permission_entries(registry) + self._engine_entries() + self._user_slot.list_all()
        return sorted(entries, key=lambda policy: (policy.source, policy.title.lower(), policy.policy_id))

    def summary(self, registry: PermissionRegistry) -> Dict[str, object]:
        entries = self.list_all(registry)
        bindings = self.list_bindings()
        return {
            "entries": [entry.model_dump() for entry in entries],
            "bindings": [binding.model_dump() for binding in bindings],
            "summary": {
                "total": len(entries),
                "enforcing": sum(entry.enforcement != Enforcement.ADVISORY for entry in entries),
                "advisory": sum(entry.enforcement == Enforcement.ADVISORY for entry in entries),
                "user_authored": sum(entry.source == "user-slot" for entry in entries),
                "active_bindings": sum(binding.state == "active" for binding in bindings),
                "pending_bindings": sum(binding.state == "pending_forward" for binding in bindings),
                "pending_removals": sum(
                    binding.removal_state == "pending_forward" for binding in bindings
                ),
            },
        }

    def get_policy(self, policy_id: str, registry: PermissionRegistry) -> Optional[Policy]:
        return next((entry for entry in self.list_all(registry) if entry.policy_id == policy_id), None)

    def create_policy(
        self,
        actor: UserIdentity,
        *,
        title: str,
        statement: str,
        type: PolicyType,
        enforcement: Enforcement = Enforcement.ADVISORY,
        workflow_ref: Optional[str] = None,
        visibility: str = "own",
        users: UserRegistry = user_registry,
    ) -> Policy:
        if not users.is_capability_granted(actor, "policy.create"):
            raise PermissionError(f"User '{actor.user_id}' cannot create policies.")
        if enforcement != Enforcement.ADVISORY:
            raise ValueError(
                "User-authored policies are advisory until an executor enforces them."
            )
        policy = Policy(
            policy_id=f"POL-{uuid.uuid4().hex[:8].upper()}",
            title=title,
            statement=statement,
            type=type,
            enforcement=enforcement,
            enforced_by="not-enforced (user declaration)",
            source="user-slot",
            owner=actor.user_id,
            visibility=visibility,
            workflow_ref=workflow_ref,
        )
        return self._user_slot.put(policy.policy_id, policy)

    def update_policy(
        self,
        actor: UserIdentity,
        policy_id: str,
        *,
        users: UserRegistry = user_registry,
        **changes,
    ) -> Policy:
        policy = self._user_slot.get(policy_id)
        if policy is None:
            raise KeyError(f"Policy '{policy_id}' is not in the writable user slot.")
        capability = "policy.edit.own" if policy.owner == actor.user_id else "policy.edit.foreign"
        if not users.is_capability_granted(actor, capability):
            raise PermissionError(f"User '{actor.user_id}' lacks {capability}.")
        writable_fields = {
            "title", "statement", "type", "workflow_ref", "visibility",
            "allowed_roles", "removed_by", "source_decisions",
        }
        forbidden = sorted(set(changes) - writable_fields)
        if forbidden:
            raise ValueError(f"Fields are immutable in the user slot: {', '.join(forbidden)}")
        updated = policy.model_copy(update={**changes, "updated_at": time.time()})
        updated = Policy.model_validate(updated.model_dump())
        return self._user_slot.put(policy_id, updated)

    def list_bindings(self) -> List[PolicyBinding]:
        return sorted(self._bindings.list_all(), key=lambda binding: binding.created_at, reverse=True)

    def bind(
        self,
        actor: UserIdentity,
        policy: Policy,
        *,
        target_kind: str,
        target_id: str,
        scope_level: str,
        target_owner: Optional[str] = None,
        target_user_id: Optional[str] = None,
        target_department_id: Optional[str] = None,
        users: UserRegistry = user_registry,
    ) -> PolicyBinding:
        verdict = explain_binding(
            actor, policy, target_kind, target_id, scope_level,
            target_owner=target_owner, target_user_id=target_user_id, users=users,
            target_department_id=target_department_id,
        )
        if verdict.verdict == BindingAction.DENY:
            raise PermissionError(verdict.reason)

        binding = PolicyBinding(
            binding_id=f"PBIND-{uuid.uuid4().hex[:8].upper()}",
            policy_id=policy.policy_id,
            target_kind=target_kind,
            target_id=target_id,
            scope_level=scope_level,
            target_user_id=target_user_id,
            target_department_id=target_department_id,
            bound_by=actor.user_id,
            state="active" if verdict.verdict == BindingAction.ALLOW else "pending_forward",
            verdict_reason=verdict.reason,
            triggered_rule=verdict.triggered_rule,
            applied_rules=verdict.applied_rules,
            decisive_rule=verdict.decisive_rule,
        )
        if verdict.verdict == BindingAction.FORWARD:
            from sentinel_fleet.uas.ticket_master import TicketPriority, ticket_master

            ticket = ticket_master.create_approval_ticket(
                title=f"Policy binding request: {policy.title}",
                description=(
                    f"{actor.user_id} requests {policy.policy_id} on {target_kind}:{target_id} "
                    f"for scope {scope_level}"
                    f"{f' ({target_user_id})' if target_user_id else ''}"
                    f"{f' ({target_department_id})' if target_department_id else ''}. "
                    f"{verdict.reason}"
                ),
                agent_id="agent:orchestrator",
                tool_name="policy_binding_request",
                payload={
                    "binding_id": binding.binding_id,
                    "policy_id": policy.policy_id,
                    "target_user_id": target_user_id,
                    "target_department_id": target_department_id,
                },
                priority=TicketPriority.NORMAL,
                requested_by=actor.user_id,
                assigned_to_role=verdict.forward_to_role,
                assigned_to_user=verdict.forward_to_user,
            )
            binding.forwarded_ticket_id = ticket.ticket_id
            binding.forwarded_to_role = verdict.forward_to_role
            binding.forwarded_to_user = verdict.forward_to_user
        return self._bindings.put(binding.binding_id, binding)

    def remove_binding(
        self,
        actor: UserIdentity,
        binding_id: str,
        *,
        registry: PermissionRegistry,
        users: UserRegistry = user_registry,
    ) -> PolicyBinding:
        binding = self._bindings.get(binding_id)
        if binding is None:
            raise KeyError(f"Policy binding '{binding_id}' does not exist.")
        if binding.state == "removed":
            raise ValueError(f"Policy binding '{binding_id}' is already removed.")
        if binding.removal_state == "pending_forward":
            raise ValueError(f"Policy binding '{binding_id}' already has a pending removal request.")
        if binding.state == "rejected":
            raise ValueError(f"Rejected policy binding '{binding_id}' is not active.")
        if binding.state == "pending_forward" and actor.user_id != binding.bound_by:
            raise PermissionError("Only the requester may withdraw a pending policy binding.")
        policy = self.get_policy(binding.policy_id, registry)
        if policy is None:
            raise KeyError(
                f"Policy '{binding.policy_id}' referenced by binding '{binding_id}' does not exist."
            )
        verdict = explain_binding(
            actor,
            policy,
            binding.target_kind,
            binding.target_id,
            binding.scope_level,
            target_user_id=binding.target_user_id,
            target_department_id=binding.target_department_id,
            operation="remove",
            binding_owner=binding.bound_by,
            users=users,
        )
        if verdict.verdict == BindingAction.DENY:
            raise PermissionError(verdict.reason)
        if verdict.verdict == BindingAction.FORWARD:
            from sentinel_fleet.uas.ticket_master import TicketPriority, ticket_master

            ticket = ticket_master.create_approval_ticket(
                title=f"Policy binding removal request: {policy.title}",
                description=(
                    f"{actor.user_id} requests removal of binding {binding.binding_id}. "
                    f"{verdict.reason}"
                ),
                agent_id="agent:orchestrator",
                tool_name="policy_binding_removal_request",
                payload={"binding_id": binding.binding_id, "policy_id": policy.policy_id},
                priority=TicketPriority.NORMAL,
                requested_by=actor.user_id,
                assigned_to_role=verdict.forward_to_role or "administrator",
                assigned_to_user=verdict.forward_to_user,
            )
            binding.removal_state = "pending_forward"
            binding.removal_ticket_id = ticket.ticket_id
            binding.removal_forwarded_to_role = verdict.forward_to_role or "administrator"
            binding.removal_forwarded_to_user = verdict.forward_to_user
            binding.verdict_reason = verdict.reason
            binding.triggered_rule = verdict.triggered_rule
            binding.applied_rules = verdict.applied_rules
            binding.decisive_rule = verdict.decisive_rule
            return self._bindings.put(binding.binding_id, binding)
        if binding.state == "pending_forward" and binding.forwarded_ticket_id:
            from sentinel_fleet.uas.ticket_master import TicketStatus, ticket_master

            pending_ticket = ticket_master.get_ticket(binding.forwarded_ticket_id)
            if pending_ticket and pending_ticket.status == TicketStatus.PENDING_APPROVAL:
                ticket_master.reject_ticket(
                    binding.forwarded_ticket_id,
                    reason=f"Binding withdrawn by requester {actor.user_id}.",
                )
        binding.state = "removed"
        binding.removal_state = "approved"
        binding.verdict_reason = verdict.reason
        binding.triggered_rule = verdict.triggered_rule
        binding.applied_rules = verdict.applied_rules
        binding.decisive_rule = verdict.decisive_rule
        return self._bindings.put(binding.binding_id, binding)

    def resolve_forward(self, ticket_id: str, approved: bool) -> Optional[PolicyBinding]:
        binding = next((
            b for b in self._bindings.list_all()
            if b.forwarded_ticket_id == ticket_id or b.removal_ticket_id == ticket_id
        ), None)
        if binding is None:
            return None
        if binding.removal_ticket_id == ticket_id:
            if binding.state != "active" or binding.removal_state != "pending_forward":
                return None
            binding.removal_state = "approved" if approved else "rejected"
            if approved:
                binding.state = "removed"
        else:
            if binding.state != "pending_forward":
                return None
            binding.state = "active" if approved else "rejected"
        return self._bindings.put(binding.binding_id, binding)


policy_catalog = PolicyCatalog()
