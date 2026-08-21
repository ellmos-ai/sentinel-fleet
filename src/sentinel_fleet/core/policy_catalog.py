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
    MATH_TOLERANCE_EUR,
    UST_REQUIRED_FIELDS,
)
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.users import UserIdentity, UserRegistry, user_registry
from sentinel_fleet.uas.task_templates import MAX_STEPS


LEGACY_UNASSIGNED_ORGANIZATION = "legacy-unassigned"


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
    organization_id: str = LEGACY_UNASSIGNED_ORGANIZATION
    org_mandated: bool = False
    visibility: str = "own"
    allowed_roles: List[str] = Field(default_factory=list)
    removed_by: List[str] = Field(default_factory=list)
    source_decisions: List[str] = Field(default_factory=list)
    workflow_ref: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @field_validator("title", "statement", "organization_id")
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
    organization_id: str = LEGACY_UNASSIGNED_ORGANIZATION
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
    def _permission_entries(
        registry: PermissionRegistry,
        organization_id: str = LEGACY_UNASSIGNED_ORGANIZATION,
    ) -> List[Policy]:
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
                organization_id=organization_id,
                org_mandated=True,
                visibility="organization",
            ))
        return entries

    @staticmethod
    def _engine_entries(
        organization_id: str = LEGACY_UNASSIGNED_ORGANIZATION,
    ) -> List[Policy]:
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
                owner="organization", organization_id=organization_id,
                org_mandated=True, visibility="organization",
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
                owner="organization", organization_id=organization_id,
                org_mandated=True, visibility="organization",
            ),
            Policy(
                policy_id="engine:step-budget",
                title="Bounded template chain",
                statement=f"A task template contains at most {MAX_STEPS} steps.",
                type=PolicyType.RULE,
                enforcement=Enforcement.MANDATORY,
                enforced_by="task_template_validator",
                source="schema-validator",
                source_ref="uas/task_templates.py::TaskTemplate._steps_form_a_valid_chain",
                owner="organization", organization_id=organization_id,
                org_mandated=True, visibility="organization",
            ),
        ]

    def list_all(self, registry: PermissionRegistry) -> List[Policy]:
        """Return the raw internal catalogue without principal filtering.

        User-facing and HTTP paths must use :meth:`list_visible`.  Projected engine and
        permission entries in this raw view deliberately retain the legacy-unassigned tenant;
        a principal-scoped view projects those same rules into the principal's organization.
        """
        entries = self._permission_entries(registry) + self._engine_entries() + self._user_slot.list_all()
        return sorted(entries, key=lambda policy: (policy.source, policy.title.lower(), policy.policy_id))

    @staticmethod
    def can_read(policy: Policy, actor: UserIdentity) -> bool:
        """Apply owner, visibility and tenant boundaries to one policy."""
        if policy.organization_id == LEGACY_UNASSIGNED_ORGANIZATION:
            return False
        if policy.organization_id != actor.organization_id:
            return False
        if policy.owner == actor.user_id:
            return True
        if policy.visibility == "organization":
            return True
        if policy.visibility == "restricted":
            return actor.profile_id in policy.allowed_roles
        return False

    def list_visible(
        self,
        registry: PermissionRegistry,
        actor: UserIdentity,
    ) -> List[Policy]:
        """Return policies visible to a verified principal in one organization."""
        projected = (
            self._permission_entries(registry, actor.organization_id)
            + self._engine_entries(actor.organization_id)
        )
        stored = [
            policy
            for policy in self._user_slot.list_all()
            if actor.user_id not in policy.removed_by and self.can_read(policy, actor)
        ]
        return sorted(
            projected + stored,
            key=lambda policy: (policy.source, policy.title.lower(), policy.policy_id),
        )

    def get_visible(
        self,
        policy_id: str,
        registry: PermissionRegistry,
        actor: UserIdentity,
    ) -> Optional[Policy]:
        return next(
            (policy for policy in self.list_visible(registry, actor) if policy.policy_id == policy_id),
            None,
        )

    def summary(
        self,
        registry: PermissionRegistry,
        actor: Optional[UserIdentity] = None,
    ) -> Dict[str, object]:
        """Summarize either the raw internal catalogue or one verified actor's view."""
        entries = self.list_all(registry) if actor is None else self.list_visible(registry, actor)
        bindings = self.list_bindings() if actor is None else self.list_visible_bindings(actor)
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
        """Raw internal lookup; user-facing callers must use :meth:`get_visible`."""
        return next((entry for entry in self.list_all(registry) if entry.policy_id == policy_id), None)

    def _get_policy_for_organization(
        self,
        policy_id: str,
        registry: PermissionRegistry,
        organization_id: str,
    ) -> Optional[Policy]:
        entries = (
            self._permission_entries(registry, organization_id)
            + self._engine_entries(organization_id)
            + self._user_slot.list_all()
        )
        return next(
            (
                policy
                for policy in entries
                if policy.policy_id == policy_id
                and policy.organization_id == organization_id
                and policy.organization_id != LEGACY_UNASSIGNED_ORGANIZATION
            ),
            None,
        )

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
            organization_id=actor.organization_id,
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
        if (
            policy.organization_id == LEGACY_UNASSIGNED_ORGANIZATION
            or policy.organization_id != actor.organization_id
        ):
            raise PermissionError(
                f"Policy '{policy_id}' belongs to another or unassigned organization."
            )
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
        """Return raw internal bindings without principal filtering."""
        return sorted(self._bindings.list_all(), key=lambda binding: binding.created_at, reverse=True)

    @staticmethod
    def can_read_binding(binding: PolicyBinding, actor: UserIdentity) -> bool:
        """Apply the binding's target scope inside its organization."""
        if binding.organization_id == LEGACY_UNASSIGNED_ORGANIZATION:
            return False
        if binding.organization_id != actor.organization_id:
            return False
        if actor.profile_id == "administrator" or binding.bound_by == actor.user_id:
            return True
        if binding.scope_level == "organization":
            return True
        if binding.scope_level == "department":
            return bool(
                actor.department
                and binding.target_department_id == actor.department
            )
        if binding.scope_level == "other_user":
            return binding.target_user_id == actor.user_id
        return False

    def list_visible_bindings(self, actor: UserIdentity) -> List[PolicyBinding]:
        return [binding for binding in self.list_bindings() if self.can_read_binding(binding, actor)]

    def get_visible_binding(
        self,
        binding_id: str,
        actor: UserIdentity,
    ) -> Optional[PolicyBinding]:
        binding = self._bindings.get(binding_id)
        if binding is None or not self.can_read_binding(binding, actor):
            return None
        return binding

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
        if (
            policy.organization_id == LEGACY_UNASSIGNED_ORGANIZATION
            or policy.organization_id != actor.organization_id
        ):
            raise PermissionError(
                f"Policy '{policy.policy_id}' belongs to another or unassigned organization."
            )
        if target_user_id:
            target_user = users.get_user(target_user_id)
            if target_user is not None and target_user.organization_id != actor.organization_id:
                raise PermissionError(
                    f"Target user '{target_user_id}' belongs to another organization."
                )
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
            organization_id=actor.organization_id,
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
                owner_id=actor.user_id,
                department_id=actor.department,
                visibility="private",
                assigned_to_role=verdict.forward_to_role,
                assigned_to_user=verdict.forward_to_user,
                organization_id=actor.organization_id,
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
        if (
            binding.organization_id == LEGACY_UNASSIGNED_ORGANIZATION
            or binding.organization_id != actor.organization_id
        ):
            raise PermissionError(
                f"Policy binding '{binding_id}' belongs to another or unassigned organization."
            )
        if binding.state == "removed":
            raise ValueError(f"Policy binding '{binding_id}' is already removed.")
        if binding.removal_state == "pending_forward":
            raise ValueError(f"Policy binding '{binding_id}' already has a pending removal request.")
        if binding.state == "rejected":
            raise ValueError(f"Rejected policy binding '{binding_id}' is not active.")
        if binding.state == "pending_forward" and actor.user_id != binding.bound_by:
            raise PermissionError("Only the requester may withdraw a pending policy binding.")
        policy = self._get_policy_for_organization(
            binding.policy_id,
            registry,
            binding.organization_id,
        )
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
                owner_id=actor.user_id,
                department_id=actor.department,
                visibility="private",
                assigned_to_role=verdict.forward_to_role or "administrator",
                assigned_to_user=verdict.forward_to_user,
                organization_id=actor.organization_id,
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
                ticket_master.withdraw_ticket(
                    binding.forwarded_ticket_id,
                    requested_by=actor.user_id,
                    requester_organization_id=actor.organization_id,
                    reason=f"Binding withdrawn by requester {actor.user_id}.",
                )
        binding.state = "removed"
        binding.removal_state = "approved"
        binding.verdict_reason = verdict.reason
        binding.triggered_rule = verdict.triggered_rule
        binding.applied_rules = verdict.applied_rules
        binding.decisive_rule = verdict.decisive_rule
        return self._bindings.put(binding.binding_id, binding)

    def resolve_forward(
        self,
        ticket_id: str,
        approved: bool,
        *,
        actor: Optional[UserIdentity] = None,
    ) -> Optional[PolicyBinding]:
        binding = next((
            b for b in self._bindings.list_all()
            if b.forwarded_ticket_id == ticket_id or b.removal_ticket_id == ticket_id
        ), None)
        if binding is None:
            return None
        if binding.removal_ticket_id == ticket_id:
            if binding.state != "active" or binding.removal_state != "pending_forward":
                return None
            if actor is None:
                raise PermissionError("A verified actor is required to resolve a policy binding.")
            if (
                binding.organization_id == LEGACY_UNASSIGNED_ORGANIZATION
                or binding.organization_id != actor.organization_id
            ):
                raise PermissionError(
                    f"Policy binding '{binding.binding_id}' belongs to another organization."
                )
            binding.removal_state = "approved" if approved else "rejected"
            if approved:
                binding.state = "removed"
        else:
            if binding.state != "pending_forward":
                return None
            if actor is None:
                raise PermissionError("A verified actor is required to resolve a policy binding.")
            if (
                binding.organization_id == LEGACY_UNASSIGNED_ORGANIZATION
                or binding.organization_id != actor.organization_id
            ):
                raise PermissionError(
                    f"Policy binding '{binding.binding_id}' belongs to another organization."
                )
            binding.state = "active" if approved else "rejected"
        return self._bindings.put(binding.binding_id, binding)


policy_catalog = PolicyCatalog()
