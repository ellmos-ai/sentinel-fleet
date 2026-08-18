"""Persistent Memory Bank based on USMC (Universal Semantic Memory Core)."""

import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sentinel_fleet.core.storage import get_store


class MemoryEntry(BaseModel):
    id: str
    category: str  # "fact", "lesson", "session_checkpoint", "entity"
    key: str
    content: str
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryBank:
    def __init__(self):
        self._store = get_store("memory", MemoryEntry)
        # Pre-seed canonical corporate memory (idempotent: seeds are keyed and overwrite themselves)
        self._seed_default_memory()

    def _seed_default_memory(self):
        seeds = [
            ("fact", "org:tax_id", "Unsere Firmen-USt-IdNr lautet DE314159265 (Acme Corp GmbH)."),
            ("fact", "org:vat_policy", "Rechnungen ohne gültige Steuernummer des Ausstellers dürfen nach § 14 UStG nicht freigegeben werden."),
            ("lesson", "vendor:cloud_solutions", "Cloud Solutions Inc. vergisst häufig das Leistungsdatum. Immer prüfen!"),
            ("entity", "vendor:acme_supplier", "Acme Supplier GmbH | IBAN: DE89370400440532013000 | Standard-Zahlungsziel: 14 Tage"),
        ]
        for cat, k, text in seeds:
            if self._store.get(k) is None:
                self.store_memory(cat, k, text)

    def store_memory(self, category: str, key: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> MemoryEntry:
        entry = MemoryEntry(
            id=f"mem-{uuid.uuid4().hex[:8]}",
            category=category,
            key=key,
            content=content,
            metadata=metadata or {}
        )
        self._store.put(key, entry)
        return entry

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
