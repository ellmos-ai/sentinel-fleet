"""GARDENER RAG: Organic Document & Context Search."""

import re
from typing import List, Dict, Any
from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    chunk_id: str
    source_name: str
    content: str
    score: float = 1.0


class GardenerRAG:
    def __init__(self):
        self.corpus: List[DocumentChunk] = []
        self._seed_legal_corpus()

    def _seed_legal_corpus(self):
        docs = [
            ("UStG_Paragraph_14", "§ 14 UStG Ausstellung von Rechnungen: Eine Rechnung muss vollständigen Namen, Anschrift, Steuernummer oder USt-IdNr, Ausstellungsdatum, Rechnungsnummer, Menge und Art der gelieferten Gegenstände oder Umfang der Leistung, Zeitpunkt der Lieferung und das Entgelt aufgeschlüsselt nach Steuersätzen enthalten."),
            ("GoBD_Compliance_Guideline", "GoBD Grundsätze ordnungsmäßiger Buchführung: Alle Belege müssen zeitnah, unveränderbar und auditierbar archiviert werden. Rechnungsänderungen bedürfen eines Stornos und Neuausstellung."),
            ("Vendor_Dispute_Procedure", "Standard Operating Procedure: for defective invoices (for example a wrong VAT rate or missing mandatory fields) the vendor is asked in a formal letter to issue a correction within 14 days. Payment is put on hold until the corrected document arrives.")
        ]
        for name, text in docs:
            self.add_document(name, text)

    def add_document(self, source_name: str, content: str):
        chunk_id = f"chunk-{len(self.corpus)+1:04d}"
        self.corpus.append(DocumentChunk(chunk_id=chunk_id, source_name=source_name, content=content))

    def search(self, query: str, top_k: int = 3) -> List[DocumentChunk]:
        """Perform keyword and semantic match across document corpus."""
        terms = set(re.findall(r"\w+", query.lower()))
        scored = []
        for chunk in self.corpus:
            chunk_terms = set(re.findall(r"\w+", chunk.content.lower()))
            overlap = len(terms.intersection(chunk_terms))
            if overlap > 0:
                score = overlap / max(len(terms), 1)
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k]]


gardener = GardenerRAG()
