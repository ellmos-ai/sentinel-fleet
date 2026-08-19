"""Persistent Memory Bank based on USMC (Universal Semantic Memory Core)."""

import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sentinel_fleet.core.errors import MemoryEntryNotFoundError, MemoryPermissionError
from sentinel_fleet.core.storage import get_store


SEED_OWNER = "system"


class MemoryEntry(BaseModel):
    id: str
    category: str  # "fact", "lesson", "session_checkpoint", "entity"
    key: str
    content: str
    # Who may change this entry, following the same rule TaskTemplate uses: the owner decides.
    # Entries the deployment ships own themselves (SEED_OWNER) and are curatable by anyone,
    # because they belong to the installation rather than to a person.
    owner: str = "operator"
    created_at: float = Field(default_factory=time.time)
    updated_at: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

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
            ("fact", "org:tax_id", "Our company VAT ID is DE314159265 (Acme Corp GmbH)."),
            ("fact", "org:vat_policy", "Invoices without a valid issuer VAT ID must not be released under § 14 UStG."),
            ("lesson", "vendor:cloud_solutions", "Cloud Solutions Inc. frequently omits the delivery date. Always verify it."),
            ("entity", "vendor:acme_supplier", "Acme Supplier GmbH | IBAN: DE89370400440532013000 | Standard payment term: 14 days"),
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
        entry.category = category
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
