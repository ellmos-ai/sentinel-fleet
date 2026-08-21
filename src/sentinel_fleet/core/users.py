"""User identities, role profiles and capability evaluation.

This is an authorization model, not authentication. The public demo uses one fixed member actor
for bounded organization actions and a separate unguessable browser workspace for private data;
query-string identity aliases are ignored. A real identity provider remains a deployment gate.
"""

import threading
import time
from enum import Enum
from typing import Dict, List, Optional, Set, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from sentinel_fleet.core.permissions import (
    PermissionAction,
    PermissionRegistry,
    PermissionRule,
    PermissionVerdict,
)
from sentinel_fleet.core.storage import BaseStore, get_store


CAPABILITIES = (
    "policy.create",
    "policy.edit.own",
    "policy.edit.foreign",
    "policy.bind.user",
    "policy.bind.user.foreign",
    "policy.bind.department",
    "policy.bind.organization",
    "permissions.edit",
    "template.create",
    "template.manage",
    "template.edit.foreign",
    "task.edit.foreign",
    "approval.decide",
    "user.manage",
    "agent.control",
    "chat.use",
    "document.process",
    "prompt.create",
    "prompt.edit.foreign",
    "skill.create",
    "skill.edit.foreign",
    "component.publish.global",
    "task.manage",
    "ticket.create",
    "web.read",
    "contact.create.personal",
    "contact.manage.department",
    "contact.manage.organization",
    "memory.create.personal",
    "memory.manage.department",
    "memory.manage.organization",
    "artifact.retention.manage",
    "artifact.legal_hold.manage",
    "document.retention.manage",
    "document.legal_hold.manage",
)

# These names currently feed an actual decision point. The remaining profile grants document the
# intended role model only; exposing that distinction keeps the demo from claiming enforcement
# that its deliberately unauthenticated HTTP surface cannot provide yet.
ENFORCED_CAPABILITIES = frozenset({
    "policy.create",
    "policy.edit.own",
    "policy.edit.foreign",
    "policy.bind.user",
    "policy.bind.user.foreign",
    "policy.bind.department",
    "policy.bind.organization",
    "template.edit.foreign",
    "task.edit.foreign",
    "template.create",
    "template.manage",
    "approval.decide",
    "agent.control",
    "chat.use",
    "document.process",
    "prompt.create",
    "prompt.edit.foreign",
    "skill.create",
    "skill.edit.foreign",
    "component.publish.global",
    "task.manage",
    "ticket.create",
    "web.read",
    "contact.create.personal",
    "contact.manage.department",
    "contact.manage.organization",
    "memory.create.personal",
    "memory.manage.department",
    "memory.manage.organization",
    "artifact.retention.manage",
    "artifact.legal_hold.manage",
    "document.retention.manage",
    "document.legal_hold.manage",
})


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class Deviation(BaseModel):
    action: PermissionAction
    reason: str
    granted_by: str
    granted_at: float = Field(default_factory=time.time)

    @field_validator("reason")
    @classmethod
    def _reason_is_evidence(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A capability deviation needs a non-empty reason.")
        return value

    @model_validator(mode="after")
    def _only_allow_or_deny(self) -> "Deviation":
        if self.action == PermissionAction.ASK:
            raise ValueError("A user deviation is allow or deny; forwarding is a binding verdict.")
        return self


class RoleProfile(BaseModel):
    profile_id: str
    name: str
    description: str
    organization_id: Optional[str] = None
    grants: Set[str] = Field(default_factory=set)

    @field_validator("profile_id", "name", "description")
    @classmethod
    def _required_text_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Role profile identity fields must not be blank.")
        return value

    @field_validator("organization_id")
    @classmethod
    def _profile_organization_is_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("A role profile organization must not be blank.")
        return value

    @field_validator("grants")
    @classmethod
    def _grants_are_not_blank(cls, value: Set[str]) -> Set[str]:
        grants = {grant.strip() for grant in value}
        if "" in grants:
            raise ValueError("Role profile grants must not be blank.")
        return grants


class UserIdentity(BaseModel):
    user_id: str
    name: str
    profile_id: str
    organization_id: str = "legacy-unassigned"
    department: Optional[str] = None
    status: UserStatus = UserStatus.ACTIVE
    deviations: Dict[str, Deviation] = Field(default_factory=dict)

    @field_validator("user_id", "name", "profile_id", "organization_id")
    @classmethod
    def _identity_text_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("User identity fields must not be blank.")
        return value

    @field_validator("department")
    @classmethod
    def _department_is_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("A department must not be blank.")
        return value


SEED_PROFILES = (
    RoleProfile(
        profile_id="administrator",
        name="Administrator",
        description="May govern every organization-wide capability.",
        grants={"*"},
    ),
    RoleProfile(
        profile_id="operator",
        name="Operator",
        description="Runs the fleet and decides approvals without changing its security root.",
        grants={
            "policy.create", "policy.edit.own", "policy.edit.foreign", "policy.bind.user",
            "policy.bind.user.foreign", "template.create", "template.edit.foreign",
            "task.edit.foreign",
            "approval.decide",
            "agent.control", "chat.use", "document.process", "prompt.create",
            "prompt.edit.foreign", "skill.create", "skill.edit.foreign",
            "component.publish.global", "task.manage", "ticket.create", "template.manage", "web.read",
            "contact.create.personal", "contact.manage.organization",
            "contact.manage.department", "memory.create.personal",
            "memory.manage.department", "memory.manage.organization",
            "artifact.retention.manage", "artifact.legal_hold.manage",
            "document.retention.manage", "document.legal_hold.manage",
        },
    ),
    RoleProfile(
        profile_id="member",
        name="Member",
        description="Creates policies and binds them to their own work; broader scope is forwarded.",
        grants={
            "policy.create", "policy.edit.own", "policy.bind.user", "template.create",
            "template.manage", "chat.use",
            "document.process", "prompt.create", "skill.create", "task.manage",
            "ticket.create", "web.read",
            "contact.create.personal", "contact.manage.department",
            "memory.create.personal", "memory.manage.department",
        },
    ),
    RoleProfile(
        profile_id="viewer",
        name="Viewer",
        description="Read-only jury or guest view.",
        grants=set(),
    ),
)

SEED_USERS = (
    UserIdentity(user_id="admin:lukas", name="Lukas (administrator)", profile_id="administrator", organization_id="sentinel-demo", department="governance"),
    UserIdentity(user_id="operator", name="Fleet operator", profile_id="operator", organization_id="sentinel-demo", department="operations"),
    UserIdentity(user_id="member:demo", name="Demo member", profile_id="member", organization_id="sentinel-demo", department="finance"),
    UserIdentity(user_id="viewer:judge", name="Judge view", profile_id="viewer", organization_id="sentinel-demo"),
)

DEMO_USER_ID = "member:demo"
_UNSET = object()


class UserRegistry:
    def __init__(
        self,
        profiles_store: Optional[BaseStore[RoleProfile]] = None,
        users_store: Optional[BaseStore[UserIdentity]] = None,
    ):
        self._lock = threading.RLock()
        self._profiles = profiles_store or get_store("role_profiles", RoleProfile)
        self._users = users_store or get_store("users", UserIdentity)
        self._seed()

    def _seed(self) -> None:
        for profile in SEED_PROFILES:
            existing = self._profiles.get(profile.profile_id)
            if existing is None:
                self._profiles.put(profile.profile_id, profile.model_copy(deep=True))
            else:
                # These grants existed in the original public-demo member profile but cross a
                # workspace boundary: approval decisions and fleet lifecycle changes are
                # operator duties. Remove them from the shipped global profile on upgrade;
                # explicit per-user deviations remain the audited way to grant an exception.
                if profile.profile_id == "member" and existing.organization_id is None:
                    existing.grants.difference_update({"approval.decide", "agent.control"})
                if profile.grants.issubset(existing.grants):
                    self._profiles.put(profile.profile_id, existing)
                    continue
                # Add newly enforced capabilities to the shipped profiles on upgrade without
                # erasing any reasoned local extension an operator already added.
                existing.grants.update(profile.grants)
                self._profiles.put(profile.profile_id, existing)
        for user in SEED_USERS:
            existing = self._users.get(user.user_id)
            if existing is None:
                self._users.put(user.user_id, user.model_copy(deep=True))
            elif existing.organization_id in {"", "legacy-unassigned"}:
                existing.organization_id = user.organization_id
                self._users.put(existing.user_id, existing)

    @staticmethod
    def _validate_organization(organization_id: object) -> str:
        if not isinstance(organization_id, str):
            raise ValueError("An organization id must be a string.")
        organization_id = organization_id.strip()
        if not organization_id:
            raise ValueError("An organization id must not be blank.")
        return organization_id

    @classmethod
    def _authorize_organization(
        cls,
        actor_organization: str,
        target_organization: str,
        *,
        system_wide: bool,
    ) -> None:
        actor_organization = cls._validate_organization(actor_organization)
        target_organization = cls._validate_organization(target_organization)
        if actor_organization != target_organization and not system_wide:
            raise PermissionError(
                f"Organization '{actor_organization}' cannot administer "
                f"organization '{target_organization}'."
            )

    def _authorize_profile(
        self,
        profile: RoleProfile,
        *,
        actor_organization: str,
        system_wide: bool,
    ) -> None:
        self._validate_organization(actor_organization)
        if profile.organization_id is None:
            if not system_wide:
                raise PermissionError(
                    f"Global role profile '{profile.profile_id}' requires explicit system-wide authority."
                )
            return
        self._authorize_organization(
            actor_organization,
            profile.organization_id,
            system_wide=system_wide,
        )

    @staticmethod
    def _is_administrator_profile(profile: Optional[RoleProfile]) -> bool:
        return profile is not None and "*" in profile.grants

    @classmethod
    def _is_active_administrator(
        cls,
        user: UserIdentity,
        profile: Optional[RoleProfile],
    ) -> bool:
        if user.status != UserStatus.ACTIVE or not cls._is_administrator_profile(profile):
            return False
        deviations = PermissionRegistry(
            rules=[
                PermissionRule(
                    tool_pattern=name,
                    action=deviation.action,
                    reason=deviation.reason,
                )
                for name, deviation in sorted(
                    user.deviations.items(),
                    key=lambda item: (-len(item[0].rstrip("*")), item[0]),
                )
            ],
            default_action=PermissionAction.ALLOW,
            default_reason="The administrator profile retains user management.",
        )
        return deviations.explain("user.manage").action == PermissionAction.ALLOW

    def _profile_for_user(self, profile_id: str, organization_id: str) -> RoleProfile:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ValueError(f"Role profile '{profile_id}' does not exist.")
        if profile.organization_id not in {None, organization_id}:
            raise ValueError(
                f"Role profile '{profile_id}' does not belong to organization "
                f"'{organization_id}'."
            )
        return profile

    def _ensure_active_administrator_remains(
        self,
        organization_id: str,
        *,
        excluding_user_ids: Set[str] = frozenset(),
        profile_overrides: Optional[Dict[str, RoleProfile]] = None,
    ) -> None:
        overrides = profile_overrides or {}
        for user in self.list_users(organization_id):
            if user.user_id in excluding_user_ids:
                continue
            profile = overrides.get(user.profile_id) or self.get_profile(user.profile_id)
            if self._is_active_administrator(user, profile):
                return
        raise PermissionError(
            f"The last active administrator of organization '{organization_id}' "
            "cannot be suspended, deleted, moved, or degraded."
        )

    def list_profiles(self, organization_id: Optional[str] = None) -> List[RoleProfile]:
        profiles = self._profiles.list_all()
        if organization_id is not None:
            organization_id = self._validate_organization(organization_id)
            profiles = [
                profile
                for profile in profiles
                if profile.organization_id in {None, organization_id}
            ]
        return sorted(profiles, key=lambda profile: profile.profile_id)

    def list_users(self, organization_id: Optional[str] = None) -> List[UserIdentity]:
        users = self._users.list_all()
        if organization_id is not None:
            organization_id = self._validate_organization(organization_id)
            users = [user for user in users if user.organization_id == organization_id]
        return sorted(users, key=lambda user: user.user_id)

    def list_departments(self, organization_id: Optional[str] = None) -> List[str]:
        return sorted({
            user.department
            for user in self.list_users(organization_id)
            if user.department
        })

    def get_profile(self, profile_id: str) -> Optional[RoleProfile]:
        return self._profiles.get(profile_id)

    def get_user(self, user_id: str) -> Optional[UserIdentity]:
        return self._users.get(user_id)

    def require_user(self, user_id: str) -> UserIdentity:
        user = self.get_user(user_id)
        if user is None:
            raise KeyError(f"User '{user_id}' is not registered.")
        return user

    def create_profile(
        self,
        profile: RoleProfile,
        *,
        actor_organization: str = "sentinel-demo",
        system_wide: bool = False,
    ) -> RoleProfile:
        actor_organization = self._validate_organization(actor_organization)
        if profile.organization_id is None and not system_wide:
            profile = profile.model_copy(update={"organization_id": actor_organization})
        else:
            self._authorize_profile(
                profile,
                actor_organization=actor_organization,
                system_wide=system_wide,
            )
        with self._lock:
            if self._profiles.get(profile.profile_id) is not None:
                raise ValueError(f"Role profile '{profile.profile_id}' already exists.")
            return self._profiles.put(profile.profile_id, profile)

    def update_profile(
        self,
        profile_id: str,
        *,
        actor_organization: str = "sentinel-demo",
        name: Optional[str] = None,
        description: Optional[str] = None,
        grants: Optional[Set[str]] = None,
        system_wide: bool = False,
    ) -> RoleProfile:
        with self._lock:
            profile = self.get_profile(profile_id)
            if profile is None:
                raise KeyError(f"Role profile '{profile_id}' is not registered.")
            self._authorize_profile(
                profile,
                actor_organization=actor_organization,
                system_wide=system_wide,
            )
            values = profile.model_dump()
            if name is not None:
                values["name"] = name
            if description is not None:
                values["description"] = description
            if grants is not None:
                values["grants"] = grants
            updated = RoleProfile.model_validate(values)
            if self._is_administrator_profile(profile) and not self._is_administrator_profile(updated):
                affected_organizations = {
                    user.organization_id
                    for user in self.list_users()
                    if user.profile_id == profile.profile_id and user.status == UserStatus.ACTIVE
                }
                for organization_id in affected_organizations:
                    self._ensure_active_administrator_remains(
                        organization_id,
                        profile_overrides={profile.profile_id: updated},
                    )
            return self._profiles.put(profile.profile_id, updated)

    def delete_profile(
        self,
        profile_id: str,
        *,
        actor_organization: str = "sentinel-demo",
        system_wide: bool = False,
    ) -> RoleProfile:
        with self._lock:
            profile = self.get_profile(profile_id)
            if profile is None:
                raise KeyError(f"Role profile '{profile_id}' is not registered.")
            self._authorize_profile(
                profile,
                actor_organization=actor_organization,
                system_wide=system_wide,
            )
            if any(user.profile_id == profile_id for user in self.list_users()):
                raise ValueError(f"Role profile '{profile_id}' is in use and cannot be deleted.")
            if not self._profiles.delete(profile_id):
                raise KeyError(f"Role profile '{profile_id}' is not registered.")
            return profile

    def create_user(
        self,
        user: UserIdentity,
        *,
        actor_organization: str = "sentinel-demo",
        system_wide: bool = False,
    ) -> UserIdentity:
        self._authorize_organization(
            actor_organization,
            user.organization_id,
            system_wide=system_wide,
        )
        self._profile_for_user(user.profile_id, user.organization_id)
        with self._lock:
            if self._users.get(user.user_id) is not None:
                raise ValueError(f"User '{user.user_id}' already exists.")
            return self._users.put(user.user_id, user)

    def update_user(
        self,
        user_id: str,
        *,
        actor_organization: str = "sentinel-demo",
        name: Optional[str] = None,
        profile_id: Optional[str] = None,
        organization_id: object = _UNSET,
        department: object = _UNSET,
        deviations: Optional[Dict[str, Deviation]] = None,
        system_wide: bool = False,
    ) -> UserIdentity:
        with self._lock:
            current = self.require_user(user_id)
            if current.status == UserStatus.DELETED:
                raise ValueError(f"Deleted user ID '{user_id}' cannot be updated or reused.")
            self._authorize_organization(
                actor_organization,
                current.organization_id,
                system_wide=system_wide,
            )
            target_organization = (
                current.organization_id
                if organization_id is _UNSET
                else self._validate_organization(organization_id)
            )
            if target_organization != current.organization_id and not system_wide:
                raise PermissionError(
                    "Moving a user between organizations requires explicit system-wide authority."
                )
            target_profile_id = profile_id or current.profile_id
            target_profile = self._profile_for_user(target_profile_id, target_organization)
            values = current.model_dump()
            values["organization_id"] = target_organization
            values["profile_id"] = target_profile_id
            if name is not None:
                values["name"] = name
            if department is not _UNSET:
                values["department"] = department
            if deviations is not None:
                values["deviations"] = deviations
            updated = UserIdentity.model_validate(values)

            current_profile = self.get_profile(current.profile_id)
            remained_admin_in_origin = (
                updated.organization_id == current.organization_id
                and self._is_active_administrator(updated, target_profile)
            )
            if (
                self._is_active_administrator(current, current_profile)
                and not remained_admin_in_origin
            ):
                self._ensure_active_administrator_remains(
                    current.organization_id,
                    excluding_user_ids={current.user_id},
                )
            return self._users.put(user_id, updated)

    def suspend_user(
        self,
        user_id: str,
        *,
        actor_organization: str = "sentinel-demo",
        system_wide: bool = False,
    ) -> UserIdentity:
        with self._lock:
            current = self.require_user(user_id)
            if current.status == UserStatus.DELETED:
                raise ValueError(f"Deleted user ID '{user_id}' cannot be suspended.")
            self._authorize_organization(
                actor_organization,
                current.organization_id,
                system_wide=system_wide,
            )
            if current.status == UserStatus.SUSPENDED:
                return current
            if self._is_active_administrator(current, self.get_profile(current.profile_id)):
                self._ensure_active_administrator_remains(
                    current.organization_id,
                    excluding_user_ids={current.user_id},
                )
            suspended = UserIdentity.model_validate({
                **current.model_dump(),
                "status": UserStatus.SUSPENDED,
            })
            return self._users.put(user_id, suspended)

    def reactivate_user(
        self,
        user_id: str,
        *,
        actor_organization: str = "sentinel-demo",
        system_wide: bool = False,
    ) -> UserIdentity:
        with self._lock:
            current = self.require_user(user_id)
            if current.status == UserStatus.DELETED:
                raise ValueError(f"Deleted user ID '{user_id}' cannot be reactivated.")
            self._authorize_organization(
                actor_organization,
                current.organization_id,
                system_wide=system_wide,
            )
            if current.status == UserStatus.ACTIVE:
                return current
            active = UserIdentity.model_validate({
                **current.model_dump(),
                "status": UserStatus.ACTIVE,
            })
            return self._users.put(user_id, active)

    def delete_user(
        self,
        user_id: str,
        *,
        actor_organization: str = "sentinel-demo",
        system_wide: bool = False,
    ) -> UserIdentity:
        with self._lock:
            current = self.require_user(user_id)
            self._authorize_organization(
                actor_organization,
                current.organization_id,
                system_wide=system_wide,
            )
            if (
                self._is_active_administrator(current, self.get_profile(current.profile_id))
            ):
                self._ensure_active_administrator_remains(
                    current.organization_id,
                    excluding_user_ids={current.user_id},
                )
            if current.status == UserStatus.DELETED:
                return current
            tombstone = UserIdentity.model_validate({
                **current.model_dump(),
                "name": "Deleted user",
                "profile_id": "viewer",
                "department": None,
                "status": UserStatus.DELETED,
                "deviations": {},
            })
            return self._users.put(user_id, tombstone)

    def explain_capability(
        self, user: Union[str, UserIdentity], capability: str
    ) -> PermissionVerdict:
        identity = self.require_user(user) if isinstance(user, str) else user
        if identity.status != UserStatus.ACTIVE:
            return PermissionVerdict(
                tool_name=capability,
                action=PermissionAction.DENY,
                source="rule",
                reason=f"User '{identity.user_id}' is {identity.status.value}.",
                matched_pattern=f"user.status={identity.status.value}",
            )

        profile = self.get_profile(identity.profile_id)
        if profile is None:
            return PermissionVerdict(
                tool_name=capability,
                action=PermissionAction.DENY,
                source="default",
                reason=f"Role profile '{identity.profile_id}' is missing; fail closed.",
            )

        # Deviations precede profile grants, so a reasoned deny can narrow a wildcard profile.
        rules = [
            PermissionRule(tool_pattern=name, action=deviation.action, reason=deviation.reason)
            for name, deviation in sorted(
                identity.deviations.items(),
                key=lambda item: (-len(item[0].rstrip("*")), item[0]),
            )
        ]
        rules.extend(
            PermissionRule(
                tool_pattern=grant,
                action=PermissionAction.ALLOW,
                reason=f"Granted by role profile '{profile.profile_id}'.",
            )
            for grant in sorted(profile.grants, key=lambda item: (-len(item), item))
        )
        registry = PermissionRegistry(
            rules=rules,
            default_action=PermissionAction.DENY,
            default_reason=f"Role profile '{profile.profile_id}' does not grant this capability.",
        )
        return registry.explain(capability)

    def is_capability_granted(self, user: Union[str, UserIdentity], capability: str) -> bool:
        return self.explain_capability(user, capability).action == PermissionAction.ALLOW

    def capability_matrix(self, organization_id: Optional[str] = None) -> Dict[str, object]:
        users = self.list_users(organization_id)
        return {
            "capabilities": list(CAPABILITIES),
            "capability_status": {
                capability: (
                    "enforced" if capability in ENFORCED_CAPABILITIES else "declared-not-enforced"
                )
                for capability in CAPABILITIES
            },
            "users": [
                {
                    **user.model_dump(),
                    "capabilities": {
                        capability: self.explain_capability(user, capability).action.value
                        for capability in CAPABILITIES
                    },
                }
                for user in users
            ],
            "profiles": [
                profile.model_dump()
                for profile in self.list_profiles(organization_id)
            ],
        }


user_registry = UserRegistry()
