"""Authorization, R1-R7 binding decisions and the federated policy catalogue."""

import uuid

import pytest

from sentinel_fleet.core.binding_rules import (
    BindingAction,
    SCOPE_LEVELS,
    TARGET_KINDS,
    explain_binding,
)
from sentinel_fleet.core.permissions import PermissionAction, PermissionRegistry, PermissionRule
from sentinel_fleet.core.policy_catalog import Enforcement, Policy, PolicyCatalog, PolicyType
from sentinel_fleet.core.users import (
    Deviation,
    RoleProfile,
    UserIdentity,
    UserRegistry,
)


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _policy(owner: str, type: PolicyType = PolicyType.PREFERENCE, **changes) -> Policy:
    values = {
        "policy_id": f"TEST-{_suffix()}",
        "title": "Keep review notes concise",
        "statement": "Prefer a concise review note.",
        "type": type,
        "enforcement": Enforcement.ADVISORY,
        "owner": owner,
    }
    if type == PolicyType.PLAN_BINDING:
        values["workflow_ref"] = "TPL-test"
    values.update(changes)
    return Policy(**values)


def test_permission_registry_can_be_injected_without_changing_gateway_defaults():
    custom = PermissionRegistry(
        rules=[PermissionRule(tool_pattern="policy.*", action=PermissionAction.DENY, reason="test")],
        default_action=PermissionAction.DENY,
        default_reason="fail closed",
    )

    assert custom.explain("policy.create").action == PermissionAction.DENY
    assert custom.explain("anything-else").reason == "fail closed"
    assert PermissionRegistry().explain("extract_invoice_multimodal").action == PermissionAction.ALLOW


def test_seed_profiles_and_users_form_a_reasoned_capability_matrix():
    users = UserRegistry()

    assert {"administrator", "operator", "member", "viewer"}.issubset({
        profile.profile_id for profile in users.list_profiles()
    })
    assert users.is_capability_granted("admin:lukas", "permissions.edit")
    assert users.is_capability_granted("member:demo", "policy.create")
    denied = users.explain_capability("viewer:judge", "policy.create")
    assert denied.action == PermissionAction.DENY
    assert denied.source == "default"


def test_reasoned_user_deviation_overrides_a_wildcard_profile():
    users = UserRegistry()
    suffix = _suffix()
    users.create_profile(RoleProfile(
        profile_id=f"wild-{suffix}", name="Wildcard", description="test", grants={"*"}
    ))
    identity = users.create_user(UserIdentity(
        user_id=f"wild-user-{suffix}",
        name="Wildcard user",
        profile_id=f"wild-{suffix}",
        organization_id="sentinel-demo",
        deviations={
            "permissions.edit": Deviation(
                action=PermissionAction.DENY,
                reason="Separation of duties",
                granted_by="admin:lukas",
            )
        },
    ))

    verdict = users.explain_capability(identity, "permissions.edit")
    assert verdict.action == PermissionAction.DENY
    assert verdict.reason == "Separation of duties"


def test_specific_user_deviation_wins_over_an_overlapping_wildcard_deviation():
    users = UserRegistry()
    suffix = _suffix()
    profile_id = f"specific-{suffix}"
    users.create_profile(RoleProfile(
        profile_id=profile_id,
        name="Specific deviations",
        description="Overlapping deviation test profile",
        grants=set(),
    ))
    identity = users.create_user(UserIdentity(
        user_id=f"specific-user-{suffix}",
        name="Specific deviation user",
        profile_id=profile_id,
        organization_id="sentinel-demo",
        deviations={
            "policy.*": Deviation(
                action=PermissionAction.ALLOW,
                reason="Broad temporary grant",
                granted_by="admin:lukas",
            ),
            "policy.bind.organization": Deviation(
                action=PermissionAction.DENY,
                reason="Organization binding remains separated",
                granted_by="admin:lukas",
            ),
        },
    ))

    exact = users.explain_capability(identity, "policy.bind.organization")
    sibling = users.explain_capability(identity, "policy.create")
    assert exact.action == PermissionAction.DENY
    assert exact.reason == "Organization binding remains separated"
    assert sibling.action == PermissionAction.ALLOW


def test_r1_to_r5_and_r7_produce_the_documented_binding_verdicts():
    users = UserRegistry()
    member = users.require_user("member:demo")
    operator = users.require_user("operator")
    viewer = users.require_user("viewer:judge")
    admin = users.require_user("admin:lukas")
    policy = _policy(member.user_id)

    assert explain_binding(member, policy, "agent", "a1", "user", users=users).verdict == BindingAction.ALLOW
    other = explain_binding(
        member, policy, "agent", "a1", "other_user", target_user_id="operator", users=users
    )
    assert other.verdict == BindingAction.FORWARD and other.forward_to_user == "operator"
    assert other.decisive_rule in {"R1", "R3"} and "R7" in other.applied_rules

    department = explain_binding(
        operator, policy, "template", "t1", "department",
        target_department_id="operations", users=users,
    )
    assert department.verdict == BindingAction.FORWARD
    assert department.forward_to_role == "administrator"

    domain = explain_binding(member, policy, "domain", "finance", "user", users=users)
    assert domain.verdict == BindingAction.FORWARD and domain.decisive_rule == "R3"

    org_decision = explain_binding(
        operator, _policy(operator.user_id, PolicyType.DECISION),
        "template", "t1", "organization", target_owner=operator.user_id, users=users,
    )
    assert org_decision.verdict == BindingAction.FORWARD and "R4" in org_decision.applied_rules

    org_mandated = _policy(
        "organization", enforcement=Enforcement.MANDATORY, org_mandated=True
    )
    mandated = explain_binding(member, org_mandated, "agent", "a1", "user", users=users)
    assert mandated.verdict == BindingAction.FORWARD and "R2" in mandated.applied_rules

    assert explain_binding(viewer, policy, "agent", "a1", "user", users=users).triggered_rule == "R5"
    assert explain_binding(admin, policy, "domain", "finance", "organization", users=users).verdict == BindingAction.ALLOW


def test_r1_to_r7_generate_all_320_documented_matrix_cells():
    users = UserRegistry()
    profiles = {
        user.profile_id: user
        for user in users.list_users()
        if user.profile_id in {"administrator", "operator", "member", "viewer"}
    }
    cells = []
    for profile_id, actor in profiles.items():
        for policy_type in PolicyType:
            policy = _policy(actor.user_id, policy_type)
            for target_kind in TARGET_KINDS:
                for scope in SCOPE_LEVELS:
                    verdict = explain_binding(
                        actor,
                        policy,
                        target_kind,
                        f"{target_kind}-1",
                        scope,
                        target_owner="different-owner",
                        target_user_id="operator" if scope == "other_user" else None,
                        target_department_id="finance" if scope == "department" else None,
                        users=users,
                    )
                    cells.append((profile_id, policy_type, target_kind, scope, verdict))

    assert len(cells) == 320
    assert all("R7" in cell[-1].applied_rules for cell in cells)
    for profile_id, policy_type, target_kind, scope, verdict in cells:
        if profile_id == "viewer":
            expected = BindingAction.DENY
        elif profile_id == "administrator":
            expected = BindingAction.ALLOW
        else:
            expected = BindingAction.ALLOW
            if scope in {"department", "organization"}:
                expected = BindingAction.FORWARD
            if scope == "other_user" and profile_id == "member":
                expected = BindingAction.FORWARD
            if target_kind == "domain":
                expected = BindingAction.FORWARD
            if target_kind in {"agent", "process", "skill"} and scope != "user":
                expected = BindingAction.FORWARD
            if target_kind == "template" and profile_id == "member":
                expected = BindingAction.FORWARD  # matrix target has a different owner
            if policy_type == PolicyType.DECISION and scope == "organization":
                expected = BindingAction.FORWARD
        assert verdict.verdict == expected, (profile_id, policy_type, target_kind, scope, verdict)


def test_explicit_deny_beats_forward_under_r7():
    users = UserRegistry()
    suffix = _suffix()
    actor = users.create_user(UserIdentity(
        user_id=f"denied-{suffix}",
        name="Denied member",
        profile_id="member",
        organization_id="sentinel-demo",
        deviations={
            "policy.bind.user.foreign": Deviation(
                action=PermissionAction.DENY,
                reason="Explicit restriction",
                granted_by="admin:lukas",
            )
        },
    ))
    verdict = explain_binding(
        actor, _policy(actor.user_id), "agent", "a1", "other_user",
        target_user_id="operator", users=users,
    )

    assert verdict.verdict == BindingAction.DENY
    assert verdict.decisive_rule == "R1"
    assert "R7" in verdict.applied_rules


def test_user_policy_slot_is_advisory_only_and_immutable_metadata_stays_honest():
    users = UserRegistry()
    catalog = PolicyCatalog()
    member = users.require_user("member:demo")

    with pytest.raises(ValueError, match="advisory"):
        catalog.create_policy(
            member, title="Claim", statement="Pretend enforcement", type=PolicyType.RULE,
            enforcement=Enforcement.ENFORCING, users=users,
        )

    created = catalog.create_policy(
        member, title=f"Preference {_suffix()}", statement="Stay concise",
        type=PolicyType.PREFERENCE, users=users,
    )
    assert created.source == "user-slot"
    assert created.enforcement == Enforcement.ADVISORY
    assert created.enforced_by == "not-enforced (user declaration)"

    with pytest.raises(ValueError, match="immutable"):
        catalog.update_policy(member, created.policy_id, source="policy-engine", users=users)
    with pytest.raises(ValueError, match="immutable"):
        catalog.update_policy(member, created.policy_id, enforcement="mandatory", users=users)


def test_catalog_federates_existing_sources_and_only_updates_the_user_slot():
    users = UserRegistry()
    catalog = PolicyCatalog()
    registry = PermissionRegistry()
    member = users.require_user("member:demo")
    created = catalog.create_policy(
        member, title=f"Federated {_suffix()}", statement="Visible from user slot",
        type=PolicyType.PREFERENCE, users=users,
    )

    entries = catalog.list_all(registry)
    assert created.policy_id in {entry.policy_id for entry in entries}
    assert {"permission-registry", "policy-engine", "user-slot"} <= {entry.source for entry in entries}
    with pytest.raises(KeyError, match="writable user slot"):
        catalog.update_policy(member, "engine:step-budget", title="No", users=users)


def test_forwarding_routes_to_target_user_or_admin_and_r6_removes_own_binding():
    users = UserRegistry()
    catalog = PolicyCatalog()
    member = users.require_user("member:demo")
    created = catalog.create_policy(
        member, title=f"Binding {_suffix()}", statement="A user preference",
        type=PolicyType.PREFERENCE, users=users,
    )

    own = catalog.bind(
        member, created, target_kind="agent", target_id="agent:test",
        scope_level="user", users=users,
    )
    assert own.state == "active"
    removed = catalog.remove_binding(
        member, own.binding_id, registry=PermissionRegistry(), users=users
    )
    assert removed.state == "removed" and removed.triggered_rule == "R6"

    foreign = catalog.bind(
        member, created, target_kind="agent", target_id="agent:test",
        scope_level="other_user", target_user_id="operator", users=users,
    )
    assert foreign.state == "pending_forward" and foreign.forwarded_ticket_id

    organization = catalog.bind(
        member, created, target_kind="template", target_id="template:test",
        target_owner=member.user_id, scope_level="organization", users=users,
    )
    assert organization.state == "pending_forward" and organization.forwarded_ticket_id


def test_r6_never_reuses_bind_rights_to_remove_someone_elses_binding():
    users = UserRegistry()
    member = users.require_user("member:demo")
    policy = _policy("operator")

    verdict = explain_binding(
        member,
        policy,
        "agent",
        "agent:test",
        "user",
        operation="remove",
        binding_owner="operator",
        users=users,
    )

    assert users.is_capability_granted(member, "policy.bind.user")
    assert verdict.verdict == BindingAction.FORWARD
    assert verdict.triggered_rule == "R6"


def test_foreign_removal_forward_creates_a_real_admin_ticket():
    users = UserRegistry()
    catalog = PolicyCatalog()
    member = users.require_user("member:demo")
    operator = users.require_user("operator")
    policy = catalog.create_policy(
        operator,
        title=f"Foreign removal {_suffix()}",
        statement="Keep until reviewed.",
        type=PolicyType.PREFERENCE,
        users=users,
    )
    binding = catalog.bind(
        operator, policy, target_kind="agent", target_id="agent:test",
        scope_level="user", users=users,
    )

    requested = catalog.remove_binding(
        member, binding.binding_id, registry=PermissionRegistry(), users=users
    )
    assert requested.state == "active"
    assert requested.removal_state == "pending_forward"
    assert requested.removal_ticket_id
    assert requested.decisive_rule == "R6"


def test_pending_removal_is_single_flight_and_pending_binding_can_be_withdrawn():
    from sentinel_fleet.uas.ticket_master import TicketStatus, ticket_master

    users = UserRegistry()
    catalog = PolicyCatalog()
    member = users.require_user("member:demo")
    operator = users.require_user("operator")
    foreign_policy = catalog.create_policy(
        operator,
        title=f"Single flight {_suffix()}",
        statement="Keep removal requests coherent.",
        type=PolicyType.PREFERENCE,
        users=users,
    )
    active = catalog.bind(
        operator, foreign_policy, target_kind="agent", target_id="agent:test",
        scope_level="user", users=users,
    )
    first = catalog.remove_binding(
        member, active.binding_id, registry=PermissionRegistry(), users=users
    )
    with pytest.raises(ValueError, match="pending removal request"):
        catalog.remove_binding(
            member, active.binding_id, registry=PermissionRegistry(), users=users
        )
    assert first.removal_ticket_id

    own_policy = catalog.create_policy(
        member,
        title=f"Withdraw {_suffix()}",
        statement="Allow the requester to withdraw this request.",
        type=PolicyType.PREFERENCE,
        users=users,
    )
    forwarded = catalog.bind(
        member, own_policy, target_kind="agent", target_id="agent:test",
        scope_level="organization", users=users,
    )
    withdrawn = catalog.remove_binding(
        member, forwarded.binding_id, registry=PermissionRegistry(), users=users
    )
    assert withdrawn.state == "removed"
    assert catalog.resolve_forward(forwarded.forwarded_ticket_id, approved=True) is None
    assert ticket_master.get_ticket(forwarded.forwarded_ticket_id).status == TicketStatus.REJECTED


def test_explicit_administrator_deviation_still_denies_binding():
    users = UserRegistry()
    suffix = _suffix()
    admin = users.create_user(UserIdentity(
        user_id=f"limited-admin-{suffix}",
        name="Limited admin",
        profile_id="administrator",
        organization_id="sentinel-demo",
        deviations={
            "policy.bind.organization": Deviation(
                action=PermissionAction.DENY,
                reason="Four-eyes restriction",
                granted_by="admin:lukas",
            )
        },
    ))
    verdict = explain_binding(
        admin, _policy(admin.user_id), "agent", "agent:test", "organization", users=users
    )

    assert verdict.verdict == BindingAction.DENY
    assert "Four-eyes restriction" in verdict.reason
