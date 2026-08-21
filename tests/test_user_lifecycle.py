"""Tenant-safe role profile and user lifecycle behaviour."""

import uuid

import pytest
from pydantic import ValidationError

from sentinel_fleet.core.permissions import PermissionAction
from sentinel_fleet.core.storage import LocalJsonStore
from sentinel_fleet.core.users import (
    CAPABILITIES,
    Deviation,
    ENFORCED_CAPABILITIES,
    RoleProfile,
    UserIdentity,
    UserRegistry,
    UserStatus,
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _registry() -> UserRegistry:
    return UserRegistry(
        profiles_store=LocalJsonStore("test-role-profiles", RoleProfile),
        users_store=LocalJsonStore("test-users", UserIdentity),
    )


def _profile(
    registry: UserRegistry,
    organization_id: str,
    *,
    grants: set[str] | None = None,
) -> RoleProfile:
    suffix = _suffix()
    return registry.create_profile(
        RoleProfile(
            profile_id=f"profile-{suffix}",
            name=f"Profile {suffix}",
            description="Lifecycle test profile",
            organization_id=organization_id,
            grants=grants or set(),
        ),
        actor_organization=organization_id,
    )


def _user(
    registry: UserRegistry,
    organization_id: str,
    profile_id: str,
    *,
    department: str | None = "operations",
) -> UserIdentity:
    suffix = _suffix()
    return registry.create_user(
        UserIdentity(
            user_id=f"user-{suffix}",
            name=f"User {suffix}",
            profile_id=profile_id,
            organization_id=organization_id,
            department=department,
        ),
        actor_organization=organization_id,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", " "),
        ("name", " "),
        ("profile_id", " "),
        ("organization_id", " "),
        ("department", " "),
    ],
)
def test_user_identity_rejects_blank_identity_scope_fields(field: str, value: str):
    values = {
        "user_id": "person",
        "name": "Person",
        "profile_id": "member",
        "organization_id": "org-a",
        "department": "operations",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        UserIdentity(**values)


def test_profile_rejects_blank_identity_fields_and_grants():
    with pytest.raises(ValidationError):
        RoleProfile(profile_id=" ", name="Role", description="Test")
    with pytest.raises(ValidationError):
        RoleProfile(profile_id="role", name=" ", description="Test")
    with pytest.raises(ValidationError):
        RoleProfile(profile_id="role", name="Role", description=" ")
    with pytest.raises(ValidationError):
        RoleProfile(profile_id="role", name="Role", description="Test", grants={" "})


def test_profiles_are_organization_scoped_and_must_match_the_user():
    registry = _registry()
    org_a = f"org-a-{_suffix()}"
    org_b = f"org-b-{_suffix()}"
    profile = _profile(registry, org_a)

    with pytest.raises(PermissionError):
        registry.update_profile(
            profile.profile_id,
            actor_organization=org_b,
            name="Forbidden rename",
        )
    with pytest.raises(ValueError, match="does not belong"):
        _user(registry, org_b, profile.profile_id)
    with pytest.raises(PermissionError):
        registry.create_user(
            UserIdentity(
                user_id=f"cross-org-{_suffix()}",
                name="Cross org",
                profile_id="member",
                organization_id=org_b,
            ),
            actor_organization=org_a,
        )


def test_profile_update_and_delete_are_complete_and_in_use_profiles_are_protected():
    registry = _registry()
    organization_id = f"org-profile-{_suffix()}"
    profile = _profile(registry, organization_id, grants={"chat.use"})

    updated = registry.update_profile(
        profile.profile_id,
        actor_organization=organization_id,
        name="Updated role",
        description="Updated description",
        grants={"chat.use", "web.read"},
    )
    assert updated.name == "Updated role"
    assert updated.description == "Updated description"
    assert updated.grants == {"chat.use", "web.read"}

    _user(registry, organization_id, profile.profile_id)
    with pytest.raises(ValueError, match="in use"):
        registry.delete_profile(profile.profile_id, actor_organization=organization_id)

    unused = _profile(registry, organization_id)
    deleted = registry.delete_profile(unused.profile_id, actor_organization=organization_id)
    assert deleted.profile_id == unused.profile_id
    assert registry.get_profile(unused.profile_id) is None


def test_global_seed_profile_mutation_requires_explicit_system_wide_authority():
    registry = _registry()

    with pytest.raises(PermissionError, match="system-wide"):
        registry.update_profile(
            "viewer",
            actor_organization="sentinel-demo",
            description="Changed",
        )

    updated = registry.update_profile(
        "viewer",
        actor_organization="sentinel-demo",
        description="Read-only global role",
        system_wide=True,
    )
    assert updated.description == "Read-only global role"


def test_user_update_suspend_reactivate_and_delete_are_tenant_safe():
    registry = _registry()
    org_a = f"org-user-a-{_suffix()}"
    org_b = f"org-user-b-{_suffix()}"
    profile = _profile(registry, org_a)
    identity = _user(registry, org_a, profile.profile_id)

    with pytest.raises(PermissionError):
        registry.update_user(identity.user_id, actor_organization=org_b, name="No")

    updated = registry.update_user(
        identity.user_id,
        actor_organization=org_a,
        name="Updated user",
        department=None,
        profile_id="viewer",
    )
    assert updated.name == "Updated user"
    assert updated.department is None
    assert updated.profile_id == "viewer"

    suspended = registry.suspend_user(identity.user_id, actor_organization=org_a)
    assert suspended.status == UserStatus.SUSPENDED
    assert not registry.is_capability_granted(suspended, "web.read")
    reactivated = registry.reactivate_user(identity.user_id, actor_organization=org_a)
    assert reactivated.status == UserStatus.ACTIVE

    with pytest.raises(PermissionError):
        registry.delete_user(identity.user_id, actor_organization=org_b)
    deleted = registry.delete_user(identity.user_id, actor_organization=org_a)
    assert deleted.user_id == identity.user_id
    assert deleted.status == UserStatus.DELETED
    assert deleted.name == "Deleted user"
    assert deleted.profile_id == "viewer"
    assert deleted.department is None
    assert deleted.deviations == {}
    assert registry.get_user(identity.user_id) == deleted
    assert not registry.is_capability_granted(deleted, "web.read")

    with pytest.raises(ValueError, match="already exists"):
        registry.create_user(
            UserIdentity(
                user_id=identity.user_id,
                name="Identity reuse",
                profile_id="member",
                organization_id=org_a,
            ),
            actor_organization=org_a,
        )
    with pytest.raises(ValueError, match="cannot be reactivated"):
        registry.reactivate_user(identity.user_id, actor_organization=org_a)
    with pytest.raises(ValueError, match="cannot be updated"):
        registry.update_user(
            identity.user_id,
            actor_organization=org_a,
            name="Identity reuse",
        )


def test_user_cannot_be_moved_to_another_organization_without_system_wide_authority():
    registry = _registry()
    org_a = f"org-move-a-{_suffix()}"
    org_b = f"org-move-b-{_suffix()}"
    identity = registry.create_user(
        UserIdentity(
            user_id=f"move-{_suffix()}",
            name="Move target",
            profile_id="member",
            organization_id=org_a,
        ),
        actor_organization=org_a,
    )

    with pytest.raises(PermissionError):
        registry.update_user(
            identity.user_id,
            actor_organization=org_a,
            organization_id=org_b,
        )

    moved = registry.update_user(
        identity.user_id,
        actor_organization=org_a,
        organization_id=org_b,
        system_wide=True,
    )
    assert moved.organization_id == org_b


def test_last_active_organization_administrator_cannot_be_removed_or_degraded():
    registry = _registry()
    organization_id = f"org-admin-{_suffix()}"
    admin_profile = _profile(registry, organization_id, grants={"*"})
    admin = _user(registry, organization_id, admin_profile.profile_id)

    with pytest.raises(PermissionError, match="last active administrator"):
        registry.suspend_user(admin.user_id, actor_organization=organization_id)
    with pytest.raises(PermissionError, match="last active administrator"):
        registry.delete_user(admin.user_id, actor_organization=organization_id)
    with pytest.raises(PermissionError, match="last active administrator"):
        registry.update_user(
            admin.user_id,
            actor_organization=organization_id,
            profile_id="member",
        )
    with pytest.raises(PermissionError, match="last active administrator"):
        registry.update_profile(
            admin_profile.profile_id,
            actor_organization=organization_id,
            grants={"user.manage"},
        )
    with pytest.raises(PermissionError, match="last active administrator"):
        registry.update_user(
            admin.user_id,
            actor_organization=organization_id,
            deviations={
                "user.manage": Deviation(
                    action=PermissionAction.DENY,
                    reason="Temporary separation of duties",
                    granted_by="security-root",
                )
            },
        )

    second_profile = _profile(registry, organization_id, grants={"*"})
    _user(registry, organization_id, second_profile.profile_id)
    degraded = registry.update_user(
        admin.user_id,
        actor_organization=organization_id,
        profile_id="member",
    )
    assert degraded.profile_id == "member"


def test_user_lists_and_capability_matrix_can_be_filtered_by_organization():
    registry = _registry()
    org_a = f"org-list-a-{_suffix()}"
    org_b = f"org-list-b-{_suffix()}"
    user_a = registry.create_user(
        UserIdentity(
            user_id=f"list-a-{_suffix()}",
            name="A",
            profile_id="member",
            organization_id=org_a,
        ),
        actor_organization=org_a,
    )
    user_b = registry.create_user(
        UserIdentity(
            user_id=f"list-b-{_suffix()}",
            name="B",
            profile_id="member",
            organization_id=org_b,
        ),
        actor_organization=org_b,
    )

    assert {user.user_id for user in registry.list_users(org_a)} == {user_a.user_id}
    assert {user.user_id for user in registry.list_users(org_b)} == {user_b.user_id}
    assert {item["user_id"] for item in registry.capability_matrix(org_a)["users"]} == {
        user_a.user_id
    }


def test_retention_legal_hold_and_foreign_task_edit_capabilities_are_enforced_by_role():
    registry = _registry()
    capabilities = {
        "artifact.retention.manage",
        "artifact.legal_hold.manage",
        "document.retention.manage",
        "document.legal_hold.manage",
        "task.edit.foreign",
    }

    assert capabilities.issubset(CAPABILITIES)
    assert capabilities.issubset(ENFORCED_CAPABILITIES)
    for capability in capabilities:
        assert registry.is_capability_granted("admin:lukas", capability)
        assert registry.is_capability_granted("operator", capability)
        assert not registry.is_capability_granted("member:demo", capability)
