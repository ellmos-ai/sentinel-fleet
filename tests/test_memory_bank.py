"""Unit tests for USMC Memory Bank & GARDENER RAG."""

import pytest
from sentinel_fleet.memory.bank import MemoryBank
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
