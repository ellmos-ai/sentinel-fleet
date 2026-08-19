"""Unit tests for USMC Memory Bank & GARDENER RAG."""

import pytest
from sentinel_fleet.memory.bank import MemoryBank, memory_bank
from sentinel_fleet.memory.gardener_rag import GardenerRAG
from sentinel_fleet.memory.hooker import MemoryHooker


def test_memory_bank_store_and_search():
    bank = MemoryBank()
    bank.store_memory("fact", "policy:invoice_deadline", "Payment term is 30 days from receipt of the invoice.")
    
    results = bank.search_memories("invoice_deadline")
    assert len(results) >= 1
    assert "30 days" in results[0].content


def test_gardener_rag_search():
    rag = GardenerRAG()
    hits = rag.search("UStG mandatory fields VAT id", top_k=2)
    assert len(hits) >= 1
    # The German statute chunk stays retrievable from an English query via the § 14 UStG tokens
    assert any("§ 14 UStG" in hit.content for hit in hits)


def test_memory_hooker_injects_context():
    context_text = MemoryHooker.inject_context("invoice audit § 14 UStG")
    assert "CONTEXT HOOK INJECTION" in context_text
    assert len(context_text) > 50


# ---------------------------------------------------------------------------
# Correctability. The live test read an unchangeable memory bank as the same powerlessness the
# overview cards caused: "if CEO is filed under the wrong category, there is nothing I can do".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_entry_can_be_corrected_and_deleted():
    from httpx import AsyncClient, ASGITransport
    from sentinel_fleet.web.server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/memory/create", data={
            "category": "working", "key": "person:ceo", "content": "Filed wrong."
        })
        assert created.status_code == 200
        assert created.json()["entry"]["owner"] == "operator"

        updated = await client.put("/api/memory/person:ceo", data={
            "category": "facts", "content": "Jane Doe, CEO, Acme Corp GmbH."
        })
        assert updated.status_code == 200
        entry = updated.json()["entry"]
        assert entry["category"] == "facts"
        assert entry["content"] == "Jane Doe, CEO, Acme Corp GmbH."
        assert entry["updated_at"] is not None

        removed = await client.delete("/api/memory/person:ceo")
        assert removed.status_code == 200
        assert memory_bank.get_memory("person:ceo") is None


def test_only_the_owner_may_change_an_entry():
    """The same rule TaskTemplate uses, so the console has one answer to "who may change this"."""
    from sentinel_fleet.core.errors import MemoryPermissionError

    memory_bank.store_memory("fact", "test:owned", "Belongs to someone else.", owner="alice")
    with pytest.raises(MemoryPermissionError):
        memory_bank.update_memory("test:owned", category="fact", content="Nope.", requested_by="bob")
    with pytest.raises(MemoryPermissionError):
        memory_bank.delete_memory("test:owned", requested_by="bob")

    kept = memory_bank.get_memory("test:owned")
    assert kept.content == "Belongs to someone else."
    memory_bank.delete_memory("test:owned", requested_by="alice")


def test_an_edited_seed_is_not_healed_back_on_startup():
    """A seeded entry is editable rather than silently protected - but the seeding used to
    rewrite any seed whose content had changed, so an edit would have appeared to work and then
    vanished on the next restart, with nothing saying so."""
    from sentinel_fleet.memory.bank import MemoryBank

    key = "org:tax_id"
    seeded = memory_bank.get_memory(key)
    assert seeded is not None and seeded.metadata.get("seed") is True
    assert seeded.owner == "system", "a shipped entry belongs to the deployment, not to a person"

    memory_bank.update_memory(key, category="facts", content="Corrected by the operator.",
                              requested_by="operator")

    # A second MemoryBank runs the same seeding a restart would.
    MemoryBank()
    assert memory_bank.get_memory(key).content == "Corrected by the operator."

    # Put the seed back so later tests see the shipped corpus.
    entry = memory_bank.get_memory(key)
    entry.category = "facts"
    entry.metadata = {"seed": True}
    entry.content = "Our company VAT ID is DE314159265 (Acme Corp GmbH)."
    memory_bank._store.put(key, entry)


# ---------------------------------------------------------------------------
# The four USMC types. The operator's own memory system sorts what it remembers into facts,
# lessons, working state and sessions; this bank is the same idea as its own instance, so it
# uses the same vocabulary - "or a reason why it differs".
# ---------------------------------------------------------------------------


def test_entries_are_sorted_into_the_four_usmc_types():
    from sentinel_fleet.memory.bank import MEMORY_TYPES

    assert MEMORY_TYPES == ("facts", "lessons", "working", "sessions")
    for entry in memory_bank.list_all():
        assert entry.category in MEMORY_TYPES, f"{entry.key} is filed under {entry.category!r}"


def test_an_entry_written_under_an_older_label_still_loads():
    """No migration script runs and nothing is rewritten on disk, so an entry persisted before
    this vocabulary existed has to map on read or the bank would refuse to open."""
    from sentinel_fleet.memory.bank import MemoryEntry

    cases = {
        "fact": "facts",
        "policy": "facts",
        "entity": "facts",
        "lesson": "lessons",
        "session_checkpoint": "sessions",
    }
    for legacy, expected in cases.items():
        entry = MemoryEntry(id="mem-test", category=legacy, key="k", content="c")
        assert entry.category == expected
        assert entry.metadata["legacy_category"] == legacy, \
            "a derived category the operator cannot check is a claim, so the original is kept"


def test_an_unknown_label_lands_in_working_rather_than_being_dropped():
    from sentinel_fleet.memory.bank import MemoryEntry

    entry = MemoryEntry(id="mem-test", category="something-else", key="k", content="c")
    assert entry.category == "working"
    assert entry.metadata["legacy_category"] == "something-else"


def test_an_edit_cannot_smuggle_in_a_label_the_model_would_refuse():
    """Assigning to a pydantic field does not re-run a before-validator, so update_memory was
    the one path that could have stored a category the model itself rejects."""
    from sentinel_fleet.memory.bank import MEMORY_TYPES

    memory_bank.store_memory("facts", "test:normalise", "Before.", owner="operator")
    updated = memory_bank.update_memory(
        "test:normalise", category="entity", content="After.", requested_by="operator"
    )
    assert updated.category in MEMORY_TYPES
    assert updated.category == "facts"
    memory_bank.delete_memory("test:normalise", requested_by="operator")
