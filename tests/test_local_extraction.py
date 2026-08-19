"""Unit tests for the local text-layer extraction path.

The PDF fixtures are built here with fpdf2 rather than checked in as binaries: the repository
already depends on fpdf2 for transcript export, and a generated fixture cannot drift away from
what the test claims it contains.
"""

import pytest
from fpdf import FPDF

from sentinel_fleet.domains.omniledger import local_text
from sentinel_fleet.domains.omniledger.extractor import MultimodalExtractor
from sentinel_fleet.domains.omniledger.models import ExtractionMode

INVOICE_LINES = [
    "Nordlicht Datentechnik GmbH",
    "Hafenstrasse 8, 20457 Hamburg",
    "billing@nordlicht-datentechnik.example",
    "USt-IdNr.: DE 264718392",
    "",
    "Rechnungsnummer: ND-2026-4471",
    "Rechnungsdatum: 04.08.2026",
    "Lieferdatum: 01.08.2026",
    "",
    "Nettobetrag: 1.480,00 EUR",
    "MwSt. 19 %: 281,20 EUR",
    "Gesamtbetrag: 1.761,20 EUR",
]


def _pdf_bytes(lines) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    for line in lines:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(w=0, h=6, text=line.encode("latin-1", "replace").decode("latin-1") or " ")
    return bytes(pdf.output())


def test_pdf_text_layer_is_read_with_pypdf():
    result = local_text.extract_text_layer("invoice.pdf", _pdf_bytes(INVOICE_LINES))

    assert result.has_text_layer is True
    assert result.backend == "pypdf"
    assert "ND-2026-4471" in result.text


def test_plain_text_upload_survives_cp1252():
    payload = "Rechnungsnummer: X-1\nGesamtbetrag: 10,00 EUR\nStrasse".encode("cp1252")

    result = local_text.extract_text_layer("invoice.txt", payload)

    assert result.has_text_layer is True
    assert result.backend.startswith("decoded-")


def test_image_upload_is_reported_as_unreadable_not_empty():
    result = local_text.extract_text_layer("scan.png", b"\x89PNG\r\n\x1a\n")

    assert result.has_text_layer is False
    assert "OCR" in result.note


def test_pdf_without_a_text_layer_says_so():
    empty_pdf = _pdf_bytes([" "])

    result = local_text.extract_text_layer("scan.pdf", empty_pdf)

    assert result.has_text_layer is False
    assert "text layer" in result.note


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.480,00", 1480.00),
        ("1,480.00", 1480.00),
        ("281,20", 281.20),
        ("2500", 2500.0),
        ("1.234", 1234.0),
        ("12,5", 12.5),
        ("nonsense", None),
    ],
)
def test_amount_parsing_handles_both_notations(raw, expected):
    """German and English thousands separators are the same characters in opposite roles."""
    assert local_text.parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("04.08.2026", "2026-08-04"),
        ("2026-08-04", "2026-08-04"),
        ("4/8/26", "2026-08-04"),
        ("31.13.2026", None),
        ("not a date", None),
    ],
)
def test_date_normalisation(raw, expected):
    assert local_text.normalise_date(raw) == expected


def test_field_parser_reads_what_the_text_states():
    fields, notes = local_text.parse_invoice_fields("\n".join(INVOICE_LINES))

    assert fields["vendor_name"] == "Nordlicht Datentechnik GmbH"
    assert fields["vendor_vat_id"] == "DE264718392"
    assert fields["vendor_email"] == "billing@nordlicht-datentechnik.example"
    assert fields["invoice_number"] == "ND-2026-4471"
    assert fields["invoice_date"] == "2026-08-04"
    assert fields["delivery_date"] == "2026-08-01"
    assert fields["net_amount"] == 1480.00
    assert fields["tax_amount"] == 281.20
    assert fields["gross_amount"] == 1761.20
    assert fields["tax_rate"] == 19.0
    assert fields["currency"] == "EUR"
    assert any("line items" in note for note in notes)


def test_missing_fields_are_named_and_never_invented():
    text = "Some Vendor Ltd\nRechnungsnummer: A-9\nNettobetrag: 100,00 EUR"

    fields, notes = local_text.parse_invoice_fields(text)

    assert "gross_amount" not in fields
    assert "vendor_vat_id" not in fields
    missing = next(note for note in notes if note.startswith("not found"))
    assert "gross amount" in missing and "VAT ID" in missing


@pytest.mark.asyncio
async def test_uploaded_pdf_yields_its_own_values_not_a_demo_document():
    """The dishonesty this path exists to remove: a real upload coming back as canned data."""
    extractor = MultimodalExtractor()

    doc = await extractor.extract_invoice(
        filename="invoice.pdf", file_bytes=_pdf_bytes(INVOICE_LINES)
    )

    assert doc.extraction_mode is ExtractionMode.LOCAL_TEXT_LAYER
    assert doc.vendor_name == "Nordlicht Datentechnik GmbH"
    assert doc.invoice_number == "ND-2026-4471"
    assert doc.gross_amount == 1761.20
    assert "Acme" not in doc.vendor_name
    assert any("local fallback (text layer only)" in note for note in doc.extraction_notes)


@pytest.mark.asyncio
async def test_upload_without_a_readable_text_layer_says_why_it_fell_back():
    extractor = MultimodalExtractor()

    doc = await extractor.extract_invoice(filename="scan.png", file_bytes=b"\x89PNG\r\n\x1a\n")

    assert doc.extraction_mode is ExtractionMode.DETERMINISTIC_DEMO
    assert any("fixed demo document served" in note for note in doc.extraction_notes)
    assert any("unscreened" in note for note in doc.extraction_notes)


@pytest.mark.asyncio
async def test_preset_without_an_upload_keeps_serving_the_labelled_demo():
    """Console presets carry a filename and no document; the demo invoices are their content."""
    extractor = MultimodalExtractor()

    doc = await extractor.extract_invoice(filename="Invoice_MissingVAT_CS.pdf")

    assert doc.extraction_mode is ExtractionMode.DETERMINISTIC_DEMO
    assert doc.vendor_name == "Cloud Solutions Global Inc."


@pytest.mark.asyncio
async def test_extraction_carries_the_privacy_verdict_of_the_document():
    extractor = MultimodalExtractor()

    doc = await extractor.extract_invoice(
        filename="invoice.pdf", file_bytes=_pdf_bytes(INVOICE_LINES)
    )

    verdict_note = next(note for note in doc.extraction_notes if note.startswith("privacy screen"))
    # The fixture carries a vendor mailbox and a street address, both amber patterns
    assert "amber" in verdict_note
    assert "email address" in verdict_note
