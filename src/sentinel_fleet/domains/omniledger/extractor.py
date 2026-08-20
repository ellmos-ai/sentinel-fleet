"""Multimodal Vision Document Extractor using Gemini 3.5 Flash.

Three backends, in this order of preference and each labelled in the result it produces:

1. **Gemini 3.5 Flash vision** when a key is configured and the call succeeds.
2. **The document's own text layer**, read locally (`local_text.py`), for real uploads. This is
   what runs when there is no key or the model call fails - a real document then yields its real
   values, sparse and annotated, instead of a fabricated stand-in.
3. **Three fixed demo invoices** for the console's preset buttons, which supply a filename and no
   document at all. They are the demo scenarios of this deployment, not a fallback for real input.

Before anything leaves for the model, the local text view is screened for sensitive content
(`core/privacy_screen.py`) and the verdict is written onto the gate-ledger row of the call.
"""

import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from sentinel_fleet.domains.omniledger.models import (
    InvoiceDocument,
    InvoiceLineItem,
    InvoiceStatus,
    ExtractionMode
)
from sentinel_fleet.domains.omniledger import local_text
from sentinel_fleet.core.config import settings
from sentinel_fleet.core.privacy_screen import PrivacyVerdict, ScreenLevel, screen_text
from sentinel_fleet.core.telemetry import telemetry

logger = logging.getLogger(__name__)

_GEMINI_CONCURRENCY = asyncio.Semaphore(2)

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
        if ext not in SUPPORTED_MIME_TYPES:
            raise ValueError(f"Unsupported document extension '{ext or '(none)'}'.")
        return SUPPORTED_MIME_TYPES[ext]

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

        # The local text view is read first even when the model is available: it is what the
        # privacy screen inspects, and the screen has to run before the content travels.
        try:
            local = await asyncio.wait_for(
                asyncio.to_thread(local_text.extract_text_layer, filename, file_bytes),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            local = local_text.LocalTextResult(note="local parser exceeded the 8 second limit")
        screen_verdict, screen_notes = self._screen_before_dispatch(filename, local, text_content)

        if not self.api_key:
            logger.warning("No GEMINI_API_KEY - using the local extraction path")
            return self._extract_without_model(doc_id, filename, local, text_content, screen_notes)

        if (
            screen_verdict.level in {ScreenLevel.RED, ScreenLevel.UNSCREENED}
            or screen_verdict.truncated
        ):
            reason = (
                "model dispatch blocked by privacy policy: RED, UNSCREENED and partially "
                "screened documents stay local"
            )
            logger.warning("%s (%s)", reason, filename)
            return self._extract_without_model(
                doc_id, filename, local, text_content, screen_notes + [reason]
            )

        try:
            doc = await self._extract_with_gemini(doc_id, filename, file_bytes, text_content)
            doc.extraction_notes = screen_notes + doc.extraction_notes
            return doc
        except Exception as exc:
            logger.warning(
                "Gemini extraction failed (%s: %s) - falling back to the local extraction path",
                type(exc).__name__, exc
            )
            notes = screen_notes + [f"Gemini call failed ({type(exc).__name__}); read locally instead"]
            return self._extract_without_model(doc_id, filename, local, text_content, notes)

    def _screen_before_dispatch(
        self,
        filename: str,
        local: local_text.LocalTextResult,
        text_content: Optional[str]
    ) -> tuple[PrivacyVerdict, List[str]]:
        """Classify the document's content before it can reach a model, and log the verdict.

        RED, UNSCREENED and truncated content is recorded here and kept on the local path by the
        caller. AMBER content may travel because ordinary invoices necessarily contain business
        addresses and billing mailboxes; the verdict remains visible in the ledger.
        """
        readable = local.text or text_content
        verdict = screen_text(
            readable,
            unscreened_reason=local.note or "the upload carries no text this build can read",
        )
        telemetry.record_on_active_span(
            "privacy_screen",
            {"document": filename, **verdict.as_span_payload()},
        )
        if verdict.level is ScreenLevel.RED:
            logger.warning("Privacy screen RED for %s: %s", filename, verdict.summary())
        return verdict, [verdict.summary()]

    def _extract_without_model(
        self,
        doc_id: str,
        filename: str,
        local: local_text.LocalTextResult,
        text_content: Optional[str],
        notes: List[str]
    ) -> InvoiceDocument:
        """Local path: read the real document if there is one, otherwise serve a demo preset.

        The split matters. A preset button sends a filename and no document - there the fixed demo
        invoices are the intended, correctly labelled content. A real upload must never come back
        as one of them, no matter how little its text layer yields.
        """
        if local.has_text_layer:
            return self._document_from_text_layer(doc_id, filename, local, notes)

        doc = self._deterministic_extract(doc_id, filename, text_content or "")
        reason = local.note or "no document content was uploaded"
        doc.extraction_notes = notes + [f"fixed demo document served: {reason}"]
        return doc

    def _document_from_text_layer(
        self,
        doc_id: str,
        filename: str,
        local: local_text.LocalTextResult,
        notes: List[str]
    ) -> InvoiceDocument:
        """Build an invoice out of what the text layer actually states, and nothing else."""
        fields, parse_notes = local_text.parse_invoice_fields(local.text)
        doc = InvoiceDocument(
            id=doc_id,
            filename=filename,
            vendor_name=str(fields.get("vendor_name", "")),
            vendor_vat_id=fields.get("vendor_vat_id"),
            vendor_address=None,
            vendor_email=fields.get("vendor_email"),
            invoice_number=str(fields.get("invoice_number", "")),
            invoice_date=str(fields.get("invoice_date", "")),
            delivery_date=fields.get("delivery_date"),
            items=[],
            net_amount=float(fields.get("net_amount", 0.0)),
            tax_rate=float(fields.get("tax_rate", 0.0)),
            tax_amount=float(fields.get("tax_amount", 0.0)),
            gross_amount=float(fields.get("gross_amount", 0.0)),
            currency=str(fields.get("currency", "EUR")),
            status=InvoiceStatus.EXTRACTED,
            extraction_mode=ExtractionMode.LOCAL_TEXT_LAYER,
        )
        doc.extraction_notes = notes + [
            f"local fallback (text layer only), backend {local.backend}"
            + (f", {local.note}" if local.note else ""),
            *parse_notes,
        ]
        logger.info("Local text-layer extraction for %s via %s", filename, local.backend)
        return doc

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

        async with _GEMINI_CONCURRENCY:
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
                    InvoiceLineItem(description="Ergonomic Office Chair Pro", quantity=2, unit_price=400.0, total_price=800.0),
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
                InvoiceLineItem(description="Development Server Cluster Node A", quantity=1, unit_price=2500.0, total_price=2500.0),
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
            vendor_name=data.get("vendor_name", "Unknown"),
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
