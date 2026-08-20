"""User identities, role profiles and capability evaluation.

This is an authorization model, not authentication.  The web demo names a user through the
query string; a real identity provider is deliberately outside the hackathon cut.  The useful
part here is still real: one registry, named profiles, reasoned deviations and one wildcard
matcher shared with the agent gateway.
"""

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
from sentinel_fleet.core.storage import get_store


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
    "template.edit.foreign",
    "approval.decide",
    "user.manage",
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
})


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


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
    grants: Set[str] = Field(default_factory=set)


class UserIdentity(BaseModel):
    user_id: str
    name: str
    profile_id: str
    department: Optional[str] = None
    status: UserStatus = UserStatus.ACTIVE
    deviations: Dict[str, Deviation] = Field(default_factory=dict)


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
            "approval.decide",
        },
    ),
    RoleProfile(
        profile_id="member",
        name="Member",
        description="Creates policies and binds them to their own work; broader scope is forwarded.",
        grants={"policy.create", "policy.edit.own", "policy.bind.user", "template.create"},
    ),
    RoleProfile(
        profile_id="viewer",
        name="Viewer",
        description="Read-only jury or guest view.",
        grants=set(),
    ),
)

SEED_USERS = (
    UserIdentity(user_id="admin:lukas", name="Lukas (administrator)", profile_id="administrator", department="governance"),
    UserIdentity(user_id="operator", name="Fleet operator", profile_id="operator", department="operations"),
    UserIdentity(user_id="member:demo", name="Demo member", profile_id="member", department="finance"),
    UserIdentity(user_id="viewer:judge", name="Judge view", profile_id="viewer"),
)

DEMO_USER_ID = "member:demo"


class UserRegistry:
    def __init__(self):
        self._profiles = get_store("role_profiles", RoleProfile)
        self._users = get_store("users", UserIdentity)
        self._seed()

    def _seed(self) -> None:
        for profile in SEED_PROFILES:
            if self._profiles.get(profile.profile_id) is None:
                self._profiles.put(profile.profile_id, profile.model_copy(deep=True))
        for user in SEED_USERS:
            if self._users.get(user.user_id) is None:
                self._users.put(user.user_id, user.model_copy(deep=True))

    def list_profiles(self) -> List[RoleProfile]:
        return sorted(self._profiles.list_all(), key=lambda profile: profile.profile_id)

    def list_users(self) -> List[UserIdentity]:
        return sorted(self._users.list_all(), key=lambda user: user.user_id)

    def list_departments(self) -> List[str]:
        return sorted({user.department for user in self.list_users() if user.department})

    def get_profile(self, profile_id: str) -> Optional[RoleProfile]:
        return self._profiles.get(profile_id)

    def get_user(self, user_id: str) -> Optional[UserIdentity]:
        return self._users.get(user_id)

    def require_user(self, user_id: str) -> UserIdentity:
        user = self.get_user(user_id)
        if user is None:
            raise KeyError(f"User '{user_id}' is not registered.")
        return user

    def create_profile(self, profile: RoleProfile) -> RoleProfile:
        if self._profiles.get(profile.profile_id) is not None:
            raise ValueError(f"Role profile '{profile.profile_id}' already exists.")
        return self._profiles.put(profile.profile_id, profile)

    def create_user(self, user: UserIdentity) -> UserIdentity:
        if self.get_profile(user.profile_id) is None:
            raise ValueError(f"Role profile '{user.profile_id}' does not exist.")
        if self._users.get(user.user_id) is not None:
            raise ValueError(f"User '{user.user_id}' already exists.")
        return self._users.put(user.user_id, user)

    def explain_capability(
        self, user: Union[str, UserIdentity], capability: str
    ) -> PermissionVerdict:
        identity = self.require_user(user) if isinstance(user, str) else user
        if identity.status != UserStatus.ACTIVE:
            return PermissionVerdict(
                tool_name=capability,
                action=PermissionAction.DENY,
                source="rule",
                reason=f"User '{identity.user_id}' is suspended.",
                matched_pattern="user.status=suspended",
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

    def capability_matrix(self) -> Dict[str, object]:
        users = self.list_users()
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
            "profiles": [profile.model_dump() for profile in self.list_profiles()],
        }


user_registry = UserRegistry()
