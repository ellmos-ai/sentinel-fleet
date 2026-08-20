"""The single R1-R7 policy-binding decision function.

The UI, API and tests all consume this verdict.  Keeping the matrix here prevents a permissive
button and a stricter endpoint (or the reverse) from becoming two competing policy systems.
"""

from enum import Enum
from typing import Any, List, Optional, Protocol

from pydantic import BaseModel

from sentinel_fleet.core.users import UserIdentity, UserRegistry, user_registry


class PolicyLike(Protocol):
    """The binding fields needed here, without importing the catalogue back into its rules."""

    owner: str
    org_mandated: bool
    type: Any


TARGET_KINDS = ("agent", "process", "template", "skill", "domain")
API_TARGET_KINDS = ("agent", "template", "skill", "domain")
SCOPE_LEVELS = ("user", "other_user", "department", "organization")


class BindingAction(str, Enum):
    ALLOW = "allow"
    FORWARD = "forward"
    DENY = "deny"


class BindingVerdict(BaseModel):
    verdict: BindingAction
    reason: str
    triggered_rule: str
    applied_rules: List[str]
    decisive_rule: str
    forward_to_role: Optional[str] = None
    forward_to_user: Optional[str] = None


_STRICTNESS = {
    BindingAction.ALLOW: 0,
    BindingAction.FORWARD: 1,
    BindingAction.DENY: 2,
}


def explain_binding(
    actor: UserIdentity,
    policy: PolicyLike,
    target_kind: str,
    target_id: str,
    scope_level: str,
    *,
    target_owner: Optional[str] = None,
    target_user_id: Optional[str] = None,
    target_department_id: Optional[str] = None,
    operation: str = "bind",
    binding_owner: Optional[str] = None,
    users: UserRegistry = user_registry,
) -> BindingVerdict:
    """Return the strictest R1-R7 verdict for one proposed binding."""
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind must be one of {list(TARGET_KINDS)}.")
    if scope_level not in SCOPE_LEVELS:
        raise ValueError(f"scope_level must be one of {list(SCOPE_LEVELS)}.")
    if not target_id.strip():
        raise ValueError("target_id must not be empty.")
    if scope_level == "other_user" and not target_user_id:
        raise ValueError("other_user scope needs target_user_id.")
    if scope_level == "department" and not target_department_id:
        raise ValueError("department scope needs target_department_id.")
    if operation not in {"bind", "remove"}:
        raise ValueError("operation must be 'bind' or 'remove'.")

    # R5: a viewer may observe but cannot fill the approval queue with requests.
    if actor.profile_id == "viewer" or actor.status.value != "active":
        return BindingVerdict(
            verdict=BindingAction.DENY,
            reason="Viewer or suspended identities cannot bind or request policy bindings.",
            triggered_rule="R5",
            applied_rules=["R5", "R7"],
            decisive_rule="R5",
        )

    administrator = actor.profile_id == "administrator"
    if operation == "remove":
        # Removal has its own rights.  Reusing policy.bind.* here would let a member who may
        # create a personal binding also remove someone else's personal binding.
        if policy.owner == actor.user_id and binding_owner == actor.user_id and not policy.org_mandated:
            return BindingVerdict(
                verdict=BindingAction.ALLOW,
                reason="The policy author may remove their own non-mandated binding.",
                triggered_rule="R6",
                applied_rules=["R6", "R7"],
                decisive_rule="R6",
            )
        edit_verdict = users.explain_capability(actor, "policy.edit.foreign")
        if edit_verdict.action.value == "allow" and (administrator or not policy.org_mandated):
            return BindingVerdict(
                verdict=BindingAction.ALLOW,
                reason="The role profile grants policy.edit.foreign for this removal.",
                triggered_rule="R6",
                applied_rules=["R6", "R7"],
                decisive_rule="R6",
            )
        if edit_verdict.source == "rule":
            return BindingVerdict(
                verdict=BindingAction.DENY,
                reason=f"An explicit user or role rule denies removal: {edit_verdict.reason}",
                triggered_rule="R6",
                applied_rules=["R6", "R7"],
                decisive_rule="R6",
            )
        return BindingVerdict(
            verdict=BindingAction.FORWARD,
            reason=(
                "An organization-mandated binding requires administrator review."
                if policy.org_mandated
                else "Only the owner or a role with policy.edit.foreign may remove this binding."
            ),
            triggered_rule="R2" if policy.org_mandated else "R6",
            applied_rules=(["R2", "R6", "R7"] if policy.org_mandated else ["R6", "R7"]),
            decisive_rule="R2" if policy.org_mandated else "R6",
            forward_to_role="administrator",
        )

    candidates = []
    capability = {
        "user": "policy.bind.user",
        "other_user": "policy.bind.user.foreign",
        "department": "policy.bind.department",
        "organization": "policy.bind.organization",
    }[scope_level]
    capability_verdict = users.explain_capability(actor, capability)
    if capability_verdict.action.value == "allow":
        candidates.append((BindingAction.ALLOW, "R1", f"Role profile grants {capability}."))
    elif capability_verdict.source == "rule":
        candidates.append((
            BindingAction.DENY,
            "R1",
            f"An explicit user or role rule denies {capability}: {capability_verdict.reason}",
        ))
    else:
        candidates.append((
            BindingAction.FORWARD,
            "R1",
            f"Role profile does not grant {capability}; the request is forwarded.",
        ))

    # R2: organization-mandated rules are administrator-governed.
    if policy.org_mandated and not administrator:
        candidates.append((
            BindingAction.FORWARD,
            "R2",
            "Only an administrator may change the reach of an organization-mandated policy.",
        ))

    # R3: a policy must not become a way around rights on the target object.
    if target_kind == "domain" and not administrator:
        candidates.append((
            BindingAction.FORWARD,
            "R3",
            "A domain covers shared fleet objects and requires administrator review.",
        ))
    elif target_kind == "template" and target_owner and target_owner != actor.user_id:
        if not users.is_capability_granted(actor, "template.edit.foreign"):
            candidates.append((
                BindingAction.FORWARD,
                "R3",
                "The target template belongs to another user; target rights must be reviewed.",
            ))
    elif target_kind in {"agent", "process", "skill"} and scope_level != "user" and not administrator:
        candidates.append((
            BindingAction.FORWARD,
            "R3",
            "A shared fleet object beyond the actor's own runs requires review.",
        ))

    # R4: organization-wide principles and plan bindings are governance acts.
    policy_type = policy.type.value if hasattr(policy.type, "value") else str(policy.type)
    if policy_type == "decision" and scope_level == "organization" and not administrator:
        candidates.append((
            BindingAction.FORWARD,
            "R4",
            "An organization-wide principle decision requires administrator review.",
        ))
    if policy_type == "plan_binding" and target_kind == "template" and target_owner != actor.user_id:
        if not administrator and not users.is_capability_granted(actor, "template.edit.foreign"):
            candidates.append((
                BindingAction.FORWARD,
                "R4",
                "A plan binding inherits the rights of the workflow it references.",
            ))

    # R7: a later rule can never loosen an earlier one.  Keep every contributing rule visible
    # and identify the rule that supplied the strictest verdict.
    verdict, rule, reason = max(candidates, key=lambda candidate: _STRICTNESS[candidate[0]])
    applied_rules = list(dict.fromkeys([candidate[1] for candidate in candidates] + ["R7"]))
    if verdict == BindingAction.FORWARD:
        if scope_level == "other_user":
            return BindingVerdict(
                verdict=verdict,
                reason=reason,
                triggered_rule=rule,
                applied_rules=applied_rules,
                decisive_rule=rule,
                forward_to_user=target_user_id,
            )
        return BindingVerdict(
            verdict=verdict,
            reason=reason,
            triggered_rule=rule,
            applied_rules=applied_rules,
            decisive_rule=rule,
            forward_to_role="administrator",
        )
    return BindingVerdict(
        verdict=verdict,
        reason=reason,
        triggered_rule=rule,
        applied_rules=applied_rules,
        decisive_rule=rule,
    )
