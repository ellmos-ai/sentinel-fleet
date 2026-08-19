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
            "category": "fact", "key": "person:ceo", "content": "Filed wrong."
        })
        assert created.status_code == 200
        assert created.json()["entry"]["owner"] == "operator"

        updated = await client.put("/api/memory/person:ceo", data={
            "category": "entity", "content": "Jane Doe, CEO, Acme Corp GmbH."
        })
        assert updated.status_code == 200
        entry = updated.json()["entry"]
        assert entry["category"] == "entity"
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

    memory_bank.update_memory(key, category="fact", content="Corrected by the operator.",
                              requested_by="operator")

    # A second MemoryBank runs the same seeding a restart would.
    MemoryBank()
    assert memory_bank.get_memory(key).content == "Corrected by the operator."

    # Put the seed back so later tests see the shipped corpus.
    entry = memory_bank.get_memory(key)
    entry.metadata = {"seed": True}
    entry.content = "Our company VAT ID is DE314159265 (Acme Corp GmbH)."
    memory_bank._store.put(key, entry)
