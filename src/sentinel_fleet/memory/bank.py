"""Persistent Memory Bank based on USMC (Universal Semantic Memory Core)."""

import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
from sentinel_fleet.core.errors import MemoryEntryNotFoundError, MemoryPermissionError
from sentinel_fleet.core.storage import get_store


SEED_OWNER = "system"
DEFAULT_ORGANIZATION_ID = "sentinel-demo"
LEGACY_ORGANIZATION_ID = "legacy-unassigned"

# The operator's own memory system (USMC) sorts what it remembers into four tables, and this
# bank is the same idea running as its own instance for this stack. Using its vocabulary is the
# point: an operator who knows one can read the other without a translation table.
#
#   facts    - things that are true and stay true (identifiers, rules, counterparty details)
#   lessons  - what went wrong once and should not again
#   working  - state of something still in flight
#   sessions - what a run or a conversation left behind
MEMORY_TYPES = ("facts", "lessons", "working", "sessions")

# What the bank held before it spoke that vocabulary. Entries persisted under the old labels map
# on read, so no migration script runs and nothing has to be rewritten on disk; the original
# label is kept alongside so the derivation stays visible rather than being asserted.
LEGACY_TYPE_MAP = {
    "fact": "facts",
    # A policy is a rule the agents read as given, and a counterparty's stable details are facts
    # about that counterparty. Both belong with the things that are true and stay true.
    "policy": "facts",
    "entity": "facts",
    "lesson": "lessons",
    "session_checkpoint": "sessions",
    "session": "sessions",
}


def normalise_category(value: str) -> str:
    """Map any label onto one of MEMORY_TYPES.

    Shared by the model's load-time validator and by `update_memory`: assigning to a pydantic
    field does not re-run a before-validator, so an edit would otherwise be the one path that
    could store a category the model itself would have rejected.
    """
    lowered = (value or "").strip().lower()
    if lowered in MEMORY_TYPES:
        return lowered
    return LEGACY_TYPE_MAP.get(lowered, "working")


class MemoryEntry(BaseModel):
    id: str
    # One of MEMORY_TYPES. Old labels are accepted and mapped rather than rejected: a stored
    # entry written before this vocabulary existed must still load.
    category: str
    key: str
    content: str
    # Who may change this entry, following the same rule TaskTemplate uses: the owner decides.
    # Entries shipped by the deployment use SEED_OWNER. HTTP callers still need the
    # organization-memory capability to curate them; trusted service calls keep compatibility.
    owner: str = "legacy-unassigned"
    # Older entries were organization-wide. New personal entries set this explicitly and are
    # filtered by their unforgeable request owner rather than a submitted form field.
    visibility: str = "personal"  # personal | department | organization
    organization_id: str = LEGACY_ORGANIZATION_ID
    department_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalise_category(cls, data):
        """Map an older label onto the four types, and keep what it used to say.

        Runs on every load, so an entry persisted before this vocabulary existed still opens -
        no migration script, nothing rewritten on disk. The previous label is kept in metadata
        rather than dropped, because a derived category the operator cannot check is a claim.
        """
        if not isinstance(data, dict):
            return data
        raw = data.get("category")
        if not isinstance(raw, str):
            return data

        mapped = normalise_category(raw)
        data["category"] = mapped
        if raw.strip().lower() not in MEMORY_TYPES:
            # An unrecognised label lands in `working`: the honest bucket for something whose
            # place is not settled, and it keeps the entry rather than dropping it. Either way
            # the original is recorded - a derived category the operator cannot check is a claim.
            metadata = dict(data.get("metadata") or {})
            metadata.setdefault("legacy_category", raw)
            data["metadata"] = metadata
        return data

    @model_validator(mode="after")
    def _scope_is_coherent(self) -> "MemoryEntry":
        if not self.organization_id.strip():
            raise ValueError("memory needs an organization_id")
        if self.visibility not in {"personal", "department", "organization"}:
            raise ValueError("visibility must be personal, department or organization")
        if self.visibility == "department" and not self.department_id:
            raise ValueError("department memory needs a department_id")
        if self.visibility != "department":
            self.department_id = None
        return self

    @property
    def is_seed(self) -> bool:
        return bool(self.metadata.get("seed"))


class MemoryBank:
    def __init__(self):
        self._store = get_store("memory", MemoryEntry)
        # Pre-seed canonical corporate memory (idempotent: seeds are keyed and overwrite themselves)
        self._seed_default_memory()

    def _seed_default_memory(self):
        """Write the canonical seeds and refresh outdated ones.

        The seed keys belong to the seeds: a stale persisted copy is healed on startup, so a
        redeployed build never serves memory content the current code no longer contains.
        Operator entries use their own keys and are never touched.

        An entry an operator has edited is left alone too. Without that, an edit to a seeded
        entry would appear to work and then silently revert on the next restart - which is worse
        than refusing the edit, because nothing would say so.
        """
        seeds = [
            ("facts", "org:tax_id", "Our company VAT ID is DE314159265 (Acme Corp GmbH)."),
            ("facts", "org:vat_policy", "Invoices without a valid issuer VAT ID must not be released under § 14 UStG."),
            ("lessons", "vendor:cloud_solutions", "Cloud Solutions Inc. frequently omits the delivery date. Always verify it."),
            ("facts", "vendor:acme_supplier", "Acme Supplier GmbH | IBAN: DE89370400440532013000 | Standard payment term: 14 days"),
        ]
        for cat, k, text in seeds:
            existing = self._store.get(k)
            if existing is not None and existing.metadata.get("edited_by"):
                continue
            if (
                existing is None
                or existing.content != text
                or existing.owner != SEED_OWNER
                or existing.organization_id != DEFAULT_ORGANIZATION_ID
                or existing.visibility != "organization"
            ):
                self.store_memory(
                    cat, k, text, metadata={"seed": True}, owner=SEED_OWNER,
                    visibility="organization", organization_id=DEFAULT_ORGANIZATION_ID,
                )

    def store_memory(
        self,
        category: str,
        key: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        owner: str = "operator",
        visibility: str = "personal",
        department_id: Optional[str] = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> MemoryEntry:
        entry = MemoryEntry(
            id=f"mem-{uuid.uuid4().hex[:8]}",
            category=category,
            key=key,
            content=content,
            owner=owner,
            visibility=visibility,
            department_id=department_id,
            organization_id=organization_id,
            metadata=metadata or {}
        )
        self._store.put(self._storage_key(entry), entry)
        return entry

    @staticmethod
    def _storage_key(entry: MemoryEntry) -> str:
        # Preserve the deployed demo's historical keys while still allowing another tenant to
        # use the same logical key without overwriting it.
        if entry.organization_id == DEFAULT_ORGANIZATION_ID:
            if entry.visibility == "organization":
                return entry.key
            if entry.visibility == "department":
                return f"department:{entry.department_id}::{entry.key}"
            return f"{entry.owner}::{entry.key}"
        prefix = f"organization:{entry.organization_id}"
        if entry.visibility == "organization":
            return f"{prefix}::{entry.key}"
        if entry.visibility == "department":
            return f"{prefix}:department:{entry.department_id}::{entry.key}"
        return f"{prefix}:owner:{entry.owner}::{entry.key}"

    @classmethod
    def _lookup_key(
        cls,
        key: str,
        visibility: str,
        organization_id: str,
        owner: str = "",
        department_id: Optional[str] = None,
    ) -> str:
        return cls._storage_key(MemoryEntry(
            id="lookup",
            category="working",
            key=key,
            content="",
            owner=owner,
            visibility=visibility,
            organization_id=organization_id,
            department_id=department_id,
        ))

    @staticmethod
    def _is_visible(
        entry: MemoryEntry,
        requested_by: str,
        requested_department: Optional[str],
        requested_organization: str,
    ) -> bool:
        if entry.organization_id != requested_organization:
            return False
        if entry.visibility == "organization":
            return True
        if entry.visibility == "personal":
            return entry.owner == requested_by
        return bool(requested_department) and entry.department_id == requested_department

    def _find(
        self,
        key: str,
        requested_by: Optional[str] = None,
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
    ) -> tuple[Optional[str], Optional[MemoryEntry]]:
        if requested_by is not None:
            scoped_key = self._lookup_key(
                key, "personal", requested_organization, owner=requested_by
            )
            personal = self._store.get(scoped_key)
            if personal is not None and self._is_visible(
                personal, requested_by, requested_department, requested_organization
            ) and personal.visibility == "personal":
                return scoped_key, personal
        if requested_department is not None:
            scoped_key = self._lookup_key(
                key,
                "department",
                requested_organization,
                department_id=requested_department,
            )
            department_entry = self._store.get(scoped_key)
            if department_entry is not None and self._is_visible(
                department_entry,
                requested_by or "",
                requested_department,
                requested_organization,
            ) and department_entry.visibility == "department":
                return scoped_key, department_entry
        organization_key = self._lookup_key(
            key, "organization", requested_organization
        )
        organization = self._store.get(organization_key)
        if (
            organization is not None
            and organization.visibility == "organization"
            and organization.organization_id == requested_organization
        ):
            return organization_key, organization
        # Trusted internal compatibility for direct callers/tests that know the logical key but
        # not the owner's storage namespace. Ambiguous keys are intentionally not guessed.
        matches = [
            entry for entry in self._store.list_all()
            if entry.key == key
            and entry.organization_id == requested_organization
            and (
                requested_by is None
                or entry.visibility == "organization"
                or (entry.visibility == "personal" and entry.owner == requested_by)
                or (
                    entry.visibility == "department"
                    and bool(requested_department)
                    and entry.department_id == requested_department
                )
            )
        ]
        if len(matches) == 1:
            entry = matches[0]
            return self._storage_key(entry), entry
        return None, None

    def _authorise(
        self,
        key: str,
        requested_by: str,
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
        can_manage_department: Optional[bool] = None,
        can_manage_organization: Optional[bool] = None,
    ) -> MemoryEntry:
        _store_key, entry = self._find(
            key,
            requested_by=requested_by,
            requested_department=requested_department,
            requested_organization=requested_organization,
        )
        if entry is None and can_manage_organization is None:
            # Trusted internal callers historically addressed entries by logical key only. Keep
            # that API while HTTP callers remain non-enumerating and owner-scoped.
            _store_key, entry = self._find(
                key, requested_organization=requested_organization
            )
        if entry is None:
            raise MemoryEntryNotFoundError(key)
        if entry.visibility == "organization":
            # ``None`` is the trusted internal/service path retained for direct callers. HTTP
            # routes always pass a real capability verdict (True/False).
            allowed = (
                can_manage_organization is True
                or (can_manage_organization is None and entry.owner in {requested_by, SEED_OWNER})
            )
        elif entry.visibility == "department":
            allowed = (
                bool(requested_department)
                and entry.department_id == requested_department
                and can_manage_department is not False
            )
        else:
            allowed = entry.owner == requested_by
        if not allowed:
            raise MemoryPermissionError(key, requested_by, entry.owner)
        return entry

    def update_memory(
        self,
        key: str,
        category: str,
        content: str,
        requested_by: str = "operator",
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
        can_manage_department: Optional[bool] = None,
        can_manage_organization: Optional[bool] = None,
    ) -> MemoryEntry:
        """Correct an entry in place. The key is the identity, so it does not change here.

        Nothing in the gate ledger is rewritten by this: a span records the tool name and the
        agent that called it, never the retrieved entry's text, so an edit changes what agents
        will read next - not what the record says they read before.
        """
        entry = self._authorise(
            key,
            requested_by,
            requested_department,
            requested_organization,
            can_manage_department,
            can_manage_organization,
        )
        entry.category = normalise_category(category)
        entry.content = content
        entry.updated_at = time.time()
        # Marks the entry as curated so the startup seeding stops healing it back.
        entry.metadata = {**entry.metadata, "edited_by": requested_by}
        self._store.put(self._storage_key(entry), entry)
        return entry

    def delete_memory(
        self,
        key: str,
        requested_by: str = "operator",
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
        can_manage_department: Optional[bool] = None,
        can_manage_organization: Optional[bool] = None,
    ) -> bool:
        entry = self._authorise(
            key,
            requested_by,
            requested_department,
            requested_organization,
            can_manage_department,
            can_manage_organization,
        )
        return self._store.delete(self._storage_key(entry))

    def get_memory(
        self,
        key: str,
        requested_by: Optional[str] = None,
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
    ) -> Optional[MemoryEntry]:
        return self._find(
            key,
            requested_by=requested_by,
            requested_department=requested_department,
            requested_organization=requested_organization,
        )[1]

    def search_memories(
        self,
        query: str,
        requested_by: str = "operator",
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
    ) -> List[MemoryEntry]:
        """Search only records visible to the concrete request principal."""
        query_lower = query.lower()
        results = []
        for entry in self.list_visible(
            requested_by, requested_department, requested_organization
        ):
            if query_lower in entry.key.lower() or query_lower in entry.content.lower():
                results.append(entry)
        return results

    def list_all(self) -> List[MemoryEntry]:
        return self._store.list_all()

    def list_visible(
        self,
        requested_by: str,
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
    ) -> List[MemoryEntry]:
        return [
            entry for entry in self._store.list_all()
            if self._is_visible(
                entry,
                requested_by,
                requested_department,
                requested_organization,
            )
        ]


memory_bank = MemoryBank()
