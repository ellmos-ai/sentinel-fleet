"""Multimodal Vision Document Extractor using Gemini 3.5 Flash."""

import os
import json
import asyncio
import logging
from typing import Dict, Any, Optional
from sentinel_fleet.domains.omniledger.models import (
    InvoiceDocument,
    InvoiceLineItem,
    InvoiceStatus,
    ExtractionMode
)
from sentinel_fleet.core.config import settings

logger = logging.getLogger(__name__)

# Mime types accepted by the Gemini multimodal file part
SUPPORTED_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain"
}

EXTRACTION_PROMPT = (
    "Extract structured JSON from this invoice with fields: "
    "vendor_name, vendor_vat_id, vendor_address, vendor_email, invoice_number, "
    "invoice_date, delivery_date, net_amount, tax_rate, tax_amount, gross_amount, "
    "currency, items: [{description, quantity, unit_price, total_price}]. "
    "Return strictly valid JSON only."
)


class MultimodalExtractor:
    @property
    def api_key(self) -> str:
        """Read the key from settings on every call so runtime environment changes are honoured."""
        return settings.gemini_api_key

    @staticmethod
    def guess_mime_type(filename: str) -> str:
        ext = os.path.splitext(filename or "")[1].lower()
        return SUPPORTED_MIME_TYPES.get(ext, "application/pdf")

    @staticmethod
    def _strip_code_fence(raw: str) -> str:
        """Remove a markdown code fence around a JSON payload without eating payload characters."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        return text.strip()

    async def extract_invoice(
        self,
        filename: str,
        file_bytes: Optional[bytes] = None,
        text_content: Optional[str] = None
    ) -> InvoiceDocument:
        """Extract structured invoice metadata from an uploaded document, raw text or a demo preset."""
        doc_id = f"INV-{os.urandom(4).hex().upper()}"

        if not self.api_key:
            logger.warning("MOCK MODE: no GEMINI_API_KEY - deterministic demo extraction")
            return self._deterministic_extract(doc_id, filename, text_content or "")

        try:
            return await self._extract_with_gemini(doc_id, filename, file_bytes, text_content)
        except Exception as exc:
            logger.warning(
                "MOCK MODE: Gemini extraction failed (%s: %s) - falling back to deterministic demo extraction",
                type(exc).__name__, exc
            )
            return self._deterministic_extract(doc_id, filename, text_content or "")

    async def _extract_with_gemini(
        self,
        doc_id: str,
        filename: str,
        file_bytes: Optional[bytes],
        text_content: Optional[str]
    ) -> InvoiceDocument:
        """Call Gemini via the google-genai SDK. Binary uploads are passed as a multimodal file part."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        if file_bytes:
            payload = types.Part.from_bytes(
                data=file_bytes,
                mime_type=self.guess_mime_type(filename)
            )
        else:
            payload = text_content or filename

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.gemini_default_model,
            contents=[EXTRACTION_PROMPT, payload]
        )

        data = json.loads(self._strip_code_fence(response.text))
        doc = self._dict_to_document(doc_id, filename, data)
        doc.extraction_mode = ExtractionMode.GEMINI
        logger.info("Gemini extraction succeeded for %s using %s", filename, settings.gemini_default_model)
        return doc

    def _deterministic_extract(self, doc_id: str, filename: str, text: str) -> InvoiceDocument:
        # Check if text contains flawed demo invoice or clean invoice
        if "MissingVAT" in filename or "ohne_steuer" in text.lower():
            return InvoiceDocument(
                id=doc_id,
                filename=filename,
                vendor_name="Cloud Solutions Global Inc.",
                vendor_vat_id="",  # Missing intentionally to trigger § 14 UStG violation
                vendor_address="100 Tech Blvd, Mountain View, CA",
                vendor_email="billing@cloudsolutions-global.example",
                invoice_number="CS-2026-9912",
                invoice_date="2026-08-15",
                delivery_date="2026-08-15",
                items=[
                    InvoiceLineItem(description="Cloud GPU Server Hosting - August 2026", quantity=1, unit_price=1200.0, total_price=1200.0)
                ],
                net_amount=1200.0,
                tax_rate=19.0,
                tax_amount=228.0,
                gross_amount=1428.0,
                currency="EUR",
                status=InvoiceStatus.EXTRACTED,
                extraction_mode=ExtractionMode.DETERMINISTIC_DEMO
            )

        if "MathError" in filename or "rechenfehler" in text.lower():
            return InvoiceDocument(
                id=doc_id,
                filename=filename,
                vendor_name="Office Supplies Direct GmbH",
                vendor_vat_id="DE812345678",
                vendor_address="Hauptstraße 12, 10115 Berlin",
                vendor_email="rechnung@officesupplies.example",
                invoice_number="OS-84920",
                invoice_date="2026-08-16",
                delivery_date="2026-08-16",
                items=[
                    InvoiceLineItem(description="Ergonomischer Bürostuhl Pro", quantity=2, unit_price=400.0, total_price=800.0),
                ],
                net_amount=800.0,
                tax_rate=19.0,
                tax_amount=152.0,
                gross_amount=1050.0,  # Intentional math error (800 + 152 != 1050)
                currency="EUR",
                status=InvoiceStatus.EXTRACTED,
                extraction_mode=ExtractionMode.DETERMINISTIC_DEMO
            )

        # Standard Perfect Invoice
        return InvoiceDocument(
            id=doc_id,
            filename=filename,
            vendor_name="Acme Tech Supplies GmbH",
            vendor_vat_id="DE987654321",
            vendor_address="Gewerbepark 4, 80333 München",
            vendor_email="finance@acme-supplies.example",
            invoice_number="INV-2026-0441",
            invoice_date="2026-08-17",
            delivery_date="2026-08-17",
            items=[
                InvoiceLineItem(description="Entwicklungs-Server Cluster Node A", quantity=1, unit_price=2500.0, total_price=2500.0),
                InvoiceLineItem(description="NVMe Enterprise Storage 4TB", quantity=2, unit_price=250.0, total_price=500.0)
            ],
            net_amount=3000.0,
            tax_rate=19.0,
            tax_amount=570.0,
            gross_amount=3570.0,
            currency="EUR",
            status=InvoiceStatus.EXTRACTED,
            extraction_mode=ExtractionMode.DETERMINISTIC_DEMO
        )

    def _dict_to_document(self, doc_id: str, filename: str, data: Dict[str, Any]) -> InvoiceDocument:
        items = []
        for it in data.get("items", []):
            items.append(InvoiceLineItem(
                description=it.get("description", "Position"),
                quantity=float(it.get("quantity", 1)),
                unit_price=float(it.get("unit_price", 0)),
                total_price=float(it.get("total_price", 0))
            ))
        return InvoiceDocument(
            id=doc_id,
            filename=filename,
            vendor_name=data.get("vendor_name", "Unbekannt"),
            vendor_vat_id=data.get("vendor_vat_id"),
            vendor_address=data.get("vendor_address"),
            vendor_email=data.get("vendor_email"),
            invoice_number=data.get("invoice_number", "INV-UNKNOWN"),
            invoice_date=data.get("invoice_date", "2026-08-17"),
            delivery_date=data.get("delivery_date"),
            items=items,
            net_amount=float(data.get("net_amount", 0)),
            tax_rate=float(data.get("tax_rate", 19)),
            tax_amount=float(data.get("tax_amount", 0)),
            gross_amount=float(data.get("gross_amount", 0)),
            currency=data.get("currency", "EUR"),
            status=InvoiceStatus.EXTRACTED
        )


extractor = MultimodalExtractor()
