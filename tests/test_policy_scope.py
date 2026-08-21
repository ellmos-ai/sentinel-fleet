"""Tenant boundaries for user policies and their bindings.

These tests intentionally exercise the catalogue directly.  HTTP handlers must consume the
principal-filtered methods instead of the raw internal catalogue/listing methods.
"""

import uuid

import pytest

from sentinel_fleet.core.permissions import PermissionRegistry
from sentinel_fleet.core.policy_catalog import (
    Enforcement,
    Policy,
    PolicyBinding,
    PolicyCatalog,
    PolicyType,
)
from sentinel_fleet.core.users import UserIdentity, UserRegistry


def _actor(
    user_id: str,
    organization_id: str,
    *,
    profile_id: str = "member",
    department: str | None = None,
) -> UserIdentity:
    return UserIdentity(
        user_id=user_id,
        name=user_id,
        profile_id=profile_id,
        organization_id=organization_id,
        department=department,
    )


def _create(
    catalog: PolicyCatalog,
    actor: UserIdentity,
    users: UserRegistry,
    *,
    visibility: str = "own",
    allowed_roles: list[str] | None = None,
) -> Policy:
    policy = catalog.create_policy(
        actor,
        title=f"Scoped preference {uuid.uuid4().hex}",
        statement="Keep this preference inside its organization.",
        type=PolicyType.PREFERENCE,
        visibility=visibility,
        users=users,
    )
    if allowed_roles is not None:
        policy = catalog.update_policy(
            actor,
            policy.policy_id,
            allowed_roles=allowed_roles,
            users=users,
        )
    return policy


def test_policy_reads_are_owner_visibility_and_organization_scoped():
    users = UserRegistry()
    catalog = PolicyCatalog()
    owner = _actor("policy-owner", "org-policy-a")
    colleague = _actor("policy-colleague", "org-policy-a")
    outsider = _actor("policy-owner", "org-policy-b")

    private = _create(catalog, owner, users)
    shared = _create(catalog, owner, users, visibility="organization")
    restricted = _create(
        catalog,
        owner,
        users,
        visibility="restricted",
        allowed_roles=["member"],
    )

    assert private.organization_id == "org-policy-a"
    assert catalog.can_read(private, owner)
    assert not catalog.can_read(private, colleague)
    assert not catalog.can_read(private, outsider)
    assert catalog.can_read(shared, colleague)
    assert not catalog.can_read(shared, outsider)
    assert catalog.can_read(restricted, colleague)

    visible_ids = {
        policy.policy_id
        for policy in catalog.list_visible(PermissionRegistry(), colleague)
    }
    assert shared.policy_id in visible_ids
    assert restricted.policy_id in visible_ids
    assert private.policy_id not in visible_ids
    assert catalog.get_visible(private.policy_id, PermissionRegistry(), colleague) is None
    assert catalog.get_visible(shared.policy_id, PermissionRegistry(), colleague) is not None

    restarted = PolicyCatalog()
    restored = restarted.get_visible(shared.policy_id, PermissionRegistry(), colleague)
    assert restored is not None
    assert restored.organization_id == "org-policy-a"


def test_legacy_policy_and_binding_rows_are_fail_closed():
    catalog = PolicyCatalog()
    actor = _actor("legacy-owner", "legacy-unassigned")
    legacy_policy = Policy(
        policy_id=f"LEGACY-{uuid.uuid4().hex}",
        title="Legacy policy",
        statement="A row written before tenant ownership existed.",
        type=PolicyType.PREFERENCE,
        enforcement=Enforcement.ADVISORY,
        owner=actor.user_id,
    )
    legacy_binding = PolicyBinding(
        binding_id=f"LEGACY-BIND-{uuid.uuid4().hex}",
        policy_id=legacy_policy.policy_id,
        target_kind="agent",
        target_id="agent:legacy",
        scope_level="user",
        bound_by=actor.user_id,
        verdict_reason="legacy",
        triggered_rule="legacy",
    )
    catalog._user_slot.put(legacy_policy.policy_id, legacy_policy)
    catalog._bindings.put(legacy_binding.binding_id, legacy_binding)

    assert not catalog.can_read(legacy_policy, actor)
    assert catalog.get_visible(legacy_policy.policy_id, PermissionRegistry(), actor) is None
    assert not catalog.can_read_binding(legacy_binding, actor)
    assert catalog.get_visible_binding(legacy_binding.binding_id, actor) is None


def test_policy_mutations_never_cross_the_organization_boundary():
    users = UserRegistry()
    catalog = PolicyCatalog()
    owner = _actor("policy-owner-a", "org-mutation-a")
    foreign_admin = _actor(
        "policy-admin-b",
        "org-mutation-b",
        profile_id="administrator",
    )
    policy = _create(catalog, owner, users)
    binding = catalog.bind(
        owner,
        policy,
        target_kind="agent",
        target_id="agent:owned",
        scope_level="user",
        users=users,
    )

    with pytest.raises(PermissionError, match="organization"):
        catalog.update_policy(
            foreign_admin,
            policy.policy_id,
            statement="Cross-tenant rewrite",
            users=users,
        )
    with pytest.raises(PermissionError, match="organization"):
        catalog.bind(
            foreign_admin,
            policy,
            target_kind="agent",
            target_id="agent:foreign",
            scope_level="user",
            users=users,
        )
    with pytest.raises(PermissionError, match="organization"):
        catalog.bind(
            owner,
            policy,
            target_kind="agent",
            target_id="agent:foreign-user",
            scope_level="other_user",
            target_user_id="operator",
            users=users,
        )
    with pytest.raises(PermissionError, match="organization"):
        catalog.remove_binding(
            foreign_admin,
            binding.binding_id,
            registry=PermissionRegistry(),
            users=users,
        )


def test_binding_read_scope_and_forward_resolution_are_tenant_scoped():
    users = UserRegistry()
    catalog = PolicyCatalog()
    owner = _actor("binding-owner", "org-binding-a", department="finance")
    colleague = _actor("binding-peer", "org-binding-a", department="finance")
    outsider = _actor("binding-admin", "org-binding-b", profile_id="administrator")
    policy = _create(catalog, owner, users, visibility="organization")

    binding = catalog.bind(
        owner,
        policy,
        target_kind="agent",
        target_id="agent:shared",
        scope_level="organization",
        users=users,
    )

    assert binding.organization_id == owner.organization_id
    assert catalog.can_read_binding(binding, colleague)
    assert not catalog.can_read_binding(binding, outsider)
    assert catalog.get_visible_binding(binding.binding_id, colleague) is not None
    assert catalog.get_visible_binding(binding.binding_id, outsider) is None
    assert binding.binding_id in {
        row.binding_id for row in catalog.list_visible_bindings(colleague)
    }
    assert PolicyCatalog().get_visible_binding(binding.binding_id, colleague) is not None

    with pytest.raises(PermissionError, match="organization"):
        catalog.resolve_forward(
            binding.forwarded_ticket_id,
            approved=True,
            actor=outsider,
        )

    same_org_admin = _actor(
        "binding-admin-a",
        "org-binding-a",
        profile_id="administrator",
    )
    resolved = catalog.resolve_forward(
        binding.forwarded_ticket_id,
        approved=True,
        actor=same_org_admin,
    )
    assert resolved is not None
    assert resolved.state == "active"
