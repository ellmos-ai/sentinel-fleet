"""MemoryHooker: Dynamic, low-overhead context clue injector."""

from typing import List
from sentinel_fleet.memory.bank import memory_bank
from sentinel_fleet.memory.gardener_rag import gardener


class MemoryHooker:
    @staticmethod
    def inject_context(task_description: str, max_clues: int = 3) -> str:
        """Inject curated facts and relevant document snippets into agent prompt context."""
        clues: List[str] = []

        # 1. Search Curated Facts from USMC Memory Bank
        memories = memory_bank.search_memories(task_description)
        for m in memories[:max_clues]:
            clues.append(f"[{m.category.upper()}] {m.content}")

        # 2. Search Document RAG Chunks from GARDENER
        rag_hits = gardener.search(task_description, top_k=2)
        for doc in rag_hits:
            clues.append(f"[LEGAL_DOC: {doc.source_name}] {doc.content}")

        if not clues:
            return ""

        formatted_clues = "\n".join(f"- {c}" for c in clues)
        return f"\n--- [CONTEXT HOOK INJECTION: MEMORY BANK & RAG] ---\n{formatted_clues}\n--- [END CONTEXT HOOK] ---\n"


memory_hooker = MemoryHooker()
