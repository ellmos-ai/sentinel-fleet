"""Persistent Memory Bank based on USMC (Universal Semantic Memory Core)."""

import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
from sentinel_fleet.core.errors import MemoryEntryNotFoundError, MemoryPermissionError
from sentinel_fleet.core.storage import get_store


SEED_OWNER = "system"

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
    # Entries the deployment ships own themselves (SEED_OWNER) and are curatable by anyone,
    # because they belong to the installation rather than to a person.
    owner: str = "operator"
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
            if existing is None or existing.content != text:
                self.store_memory(cat, k, text, metadata={"seed": True}, owner=SEED_OWNER)

    def store_memory(
        self,
        category: str,
        key: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        owner: str = "operator",
    ) -> MemoryEntry:
        entry = MemoryEntry(
            id=f"mem-{uuid.uuid4().hex[:8]}",
            category=category,
            key=key,
            content=content,
            owner=owner,
            metadata=metadata or {}
        )
        self._store.put(key, entry)
        return entry

    def _authorise(self, key: str, requested_by: str) -> MemoryEntry:
        entry = self._store.get(key)
        if entry is None:
            raise MemoryEntryNotFoundError(key)
        if entry.owner != requested_by and entry.owner != SEED_OWNER:
            raise MemoryPermissionError(key, requested_by, entry.owner)
        return entry

    def update_memory(
        self,
        key: str,
        category: str,
        content: str,
        requested_by: str = "operator",
    ) -> MemoryEntry:
        """Correct an entry in place. The key is the identity, so it does not change here.

        Nothing in the gate ledger is rewritten by this: a span records the tool name and the
        agent that called it, never the retrieved entry's text, so an edit changes what agents
        will read next - not what the record says they read before.
        """
        entry = self._authorise(key, requested_by)
        entry.category = normalise_category(category)
        entry.content = content
        entry.updated_at = time.time()
        # Marks the entry as curated so the startup seeding stops healing it back.
        entry.metadata = {**entry.metadata, "edited_by": requested_by}
        self._store.put(key, entry)
        return entry

    def delete_memory(self, key: str, requested_by: str = "operator") -> bool:
        self._authorise(key, requested_by)
        return self._store.delete(key)

    def get_memory(self, key: str) -> Optional[MemoryEntry]:
        return self._store.get(key)

    def search_memories(self, query: str) -> List[MemoryEntry]:
        query_lower = query.lower()
        results = []
        for entry in self._store.list_all():
            if query_lower in entry.key.lower() or query_lower in entry.content.lower():
                results.append(entry)
        return results

    def list_all(self) -> List[MemoryEntry]:
        return self._store.list_all()


memory_bank = MemoryBank()
