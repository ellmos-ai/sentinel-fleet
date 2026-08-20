"""Local text-layer extraction and field parsing - the path that needs no model at all.

Adapted from the `doc-services` module (`doc_services/extract.py`, MIT, same author). What was
taken is its shape: a preference chain of small backends, and a result that names the backend it
came from plus what it could not do. What was left out is everything this deployment cannot
honestly carry: no OCR (Tesseract would multiply the container size and this build ships none),
no LibreOffice or antiword subprocesses (there is no such binary in the runtime image), no
learning backend statistics (a stateless container has nowhere to learn).

The point of the local path is honesty under failure. Before this module existed, an upload
processed without a `GEMINI_API_KEY` came back as one of three canned demo invoices - real
document in, fabricated vendor out. Now a real upload yields whatever its text layer actually
says, with every field it could not find named in the notes.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sentinel_fleet.core.config import settings

# Suffixes the local path can read at all. Images and scanned PDFs carry pixels, not text; they
# are reported as unreadable rather than guessed at.
PDF_SUFFIXES = (".pdf",)
PLAIN_TEXT_SUFFIXES = (".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".eml")

# Windows-authored invoices are routinely cp1252, and a strict utf-8 read would throw away a
# perfectly readable document over one umlaut.
TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


class LocalTextResult(BaseModel):
    """What the local reader got out of a file, and by which route."""

    text: str = ""
    backend: str = ""
    note: str = ""

    @property
    def has_text_layer(self) -> bool:
        return bool(self.text.strip())


def extract_text_layer(filename: str, file_bytes: Optional[bytes]) -> LocalTextResult:
    """Read a document's text layer locally. Never raises: an unreadable file is a result."""
    if not file_bytes:
        return LocalTextResult(note="no file content was uploaded")

    suffix = os.path.splitext(filename or "")[1].lower()

    if suffix in PDF_SUFFIXES:
        return _read_pdf(file_bytes)
    if suffix in PLAIN_TEXT_SUFFIXES:
        return _read_plain(file_bytes)
    return LocalTextResult(
        note=(
            f"no local reader for '{suffix or 'unknown suffix'}'; images and scans need OCR, "
            "which this build deliberately does not bundle"
        )
    )


def _read_pdf(file_bytes: bytes) -> LocalTextResult:
    import io

    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - pypdf is a declared dependency
        return LocalTextResult(note="pypdf is not installed in this deployment")

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if len(reader.pages) > settings.max_pdf_pages:
            return LocalTextResult(
                backend="pypdf",
                note=f"PDF exceeds the {settings.max_pdf_pages}-page local parser limit",
            )
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        return LocalTextResult(note=f"PDF could not be parsed locally ({type(exc).__name__})")

    text = "\n".join(pages).strip()
    if len(text) > settings.max_extracted_chars:
        return LocalTextResult(
            backend="pypdf",
            note=f"PDF text exceeds the {settings.max_extracted_chars}-character limit",
        )
    if not text:
        return LocalTextResult(
            backend="pypdf",
            note=(
                "PDF carries no extractable text layer (a scan or an image-only export); "
                "local extraction reads text layers only"
            ),
        )
    return LocalTextResult(text=text, backend="pypdf", note=f"read {len(reader.pages)} page(s)")


def _read_plain(file_bytes: bytes) -> LocalTextResult:
    if len(file_bytes) > settings.max_extracted_chars:
        return LocalTextResult(
            note=f"text document exceeds the {settings.max_extracted_chars}-byte local parser limit"
        )
    for encoding in TEXT_ENCODINGS:
        try:
            return LocalTextResult(text=file_bytes.decode(encoding), backend=f"decoded-{encoding}")
        except UnicodeDecodeError:
            continue
    return LocalTextResult(
        text=file_bytes.decode("utf-8", errors="replace"),
        backend="decoded-utf-8-lossy",
        note="no encoding read the file cleanly; undecodable bytes were replaced",
    )


# ---------------------------------------------------------------------------
# Field parsing
#
# German invoices label their fields in German. Matching those labels is document data handling,
# not user-facing text - the same reason the demo vendors carry German postal addresses (see the
# whitelist in tests/test_i18n.py).
# ---------------------------------------------------------------------------

_LABEL_INVOICE_NUMBER = r"(?:invoice\s*(?:no\.?|number|#)|rechnungs?[-\s]*(?:nr\.?|nummer))"
_LABEL_INVOICE_DATE = r"(?:invoice\s*date|date\s*of\s*issue|rechnungsdatum|belegdatum)"
_LABEL_DELIVERY_DATE = r"(?:delivery\s*date|service\s*date|liefer(?:datum|zeitpunkt)|leistungsdatum)"
_LABEL_VAT_ID = r"(?:vat\s*(?:id|no\.?|number)?|ust[-\s]?id(?:nr)?\.?|umsatzsteuer[-\s]?id(?:entifikationsnummer)?)"
_LABEL_NET = r"(?:net(?:\s*(?:amount|total))?|nettobetrag|netto(?:summe)?|zwischensumme)"
# The lookahead keeps the tax-amount label off the VAT *identifier*: "USt-IdNr." and
# "Umsatzsteuer-Identifikationsnummer" start with the same word as the tax line, and without it
# the parser reads the leading digits of a VAT number as a euro amount.
_LABEL_TAX = r"(?:vat\s*amount|tax\s*amount|mwst\.?(?:\s*betrag)?|(?:umsatzsteuer|ust)(?![-\s]?id)\.?)"
# Between the tax label and its amount an invoice usually states the rate ("MwSt. 19 %: 281,20").
_TAX_RATE_GAP = r"(?:\s*\d{1,2}(?:[.,]\d)?\s*%)?"
_LABEL_GROSS = r"(?:gross(?:\s*(?:amount|total))?|total\s*(?:due|amount)?|bruttobetrag|brutto(?:summe)?|gesamtbetrag|rechnungsbetrag)"

# A money token in either notation: 1.234,56 (German) or 1,234.56 (English).
_AMOUNT = r"([-+]?\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?|[-+]?\d+(?:[.,]\d{1,2})?)"
_CURRENCY_SIGN = r"(?:EUR|€|USD|\$|GBP|£|CHF)?"

_RE_INVOICE_NUMBER = re.compile(rf"(?i){_LABEL_INVOICE_NUMBER}\s*[:.#]?\s*([A-Za-z0-9][A-Za-z0-9/_-]{{2,30}})")
_RE_INVOICE_DATE = re.compile(rf"(?i){_LABEL_INVOICE_DATE}\s*[:.]?\s*(\d{{1,4}}[.\-/]\d{{1,2}}[.\-/]\d{{2,4}})")
_RE_DELIVERY_DATE = re.compile(rf"(?i){_LABEL_DELIVERY_DATE}\s*[:.]?\s*(\d{{1,4}}[.\-/]\d{{1,2}}[.\-/]\d{{2,4}})")
_RE_VAT_ID = re.compile(rf"(?i){_LABEL_VAT_ID}\s*[:.]?\s*([A-Z]{{2}}\s?[0-9A-Z]{{8,12}})")
_RE_NET = re.compile(rf"(?i){_LABEL_NET}\s*[:.]?\s*{_CURRENCY_SIGN}\s*{_AMOUNT}")
_RE_TAX = re.compile(rf"(?i){_LABEL_TAX}{_TAX_RATE_GAP}\s*[:.]?\s*{_CURRENCY_SIGN}\s*{_AMOUNT}")
_RE_GROSS = re.compile(rf"(?i){_LABEL_GROSS}\s*[:.]?\s*{_CURRENCY_SIGN}\s*{_AMOUNT}")
_RE_TAX_RATE = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*%")
_RE_EMAIL = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")

_CURRENCY_TOKENS = {"€": "EUR", "EUR": "EUR", "$": "USD", "USD": "USD", "£": "GBP", "GBP": "GBP", "CHF": "CHF"}

# Lines that are a heading or a label rather than a party name.
_RE_VENDOR_NOISE = re.compile(
    r"(?i)^(?:invoice|rechnung|bill|receipt|quote|page|seite|customer|kunde)\b|^[\W\d]+$"
)


def parse_amount(raw: str) -> Optional[float]:
    """Read a money token in German or English notation.

    Which separator is decimal cannot be decided per character - it depends on which one comes
    last. "1.234,56" and "1,234.56" are the same amount written by different conventions, and
    picking the wrong one is a factor of a thousand on an invoice total.
    """
    token = (raw or "").strip().replace(" ", "")
    if not token:
        return None

    last_comma = token.rfind(",")
    last_dot = token.rfind(".")
    if last_comma >= 0 and last_dot >= 0:
        decimal_sep, thousands_sep = (",", ".") if last_comma > last_dot else (".", ",")
        token = token.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif last_comma >= 0:
        # A lone comma is a decimal point when it separates one or two trailing digits, and a
        # thousands separator otherwise ("1,234" is not 1.234 euro).
        token = token.replace(",", "." if len(token) - last_comma - 1 in (1, 2) else "")
    elif last_dot >= 0 and len(token) - last_dot - 1 == 3 and token.count(".") == 1:
        token = token.replace(".", "")

    try:
        return float(token)
    except ValueError:
        return None


def normalise_date(raw: str) -> Optional[str]:
    """Bring a date into ISO form. Ambiguous day/month order is resolved by the separator.

    German invoices write 17.08.2026, ISO writes 2026-08-17. Both are unambiguous once the
    separator is known, so no guessing is needed.
    """
    token = (raw or "").strip()
    iso = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", token)
    if iso:
        year, month, day = iso.groups()
    else:
        dmy = re.fullmatch(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", token)
        if not dmy:
            return None
        day, month, year = dmy.groups()
        if len(year) == 2:
            year = f"20{year}"

    try:
        if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
            return None
    except ValueError:
        return None
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _first_group(regex: re.Pattern, text: str) -> Optional[str]:
    match = regex.search(text)
    return match.group(1) if match else None


def _guess_vendor_name(text: str) -> Optional[str]:
    """The issuer's letterhead is the first substantial line of an invoice.

    A heuristic, and labelled as one in the notes: no statement in a text layer says "this line
    is the vendor", so this is the one field the local path infers rather than reads.
    """
    for line in text.splitlines():
        candidate = line.strip()
        if len(candidate) < 3 or len(candidate) > 80:
            continue
        if _RE_VENDOR_NOISE.search(candidate):
            continue
        if _RE_EMAIL.search(candidate):
            continue
        return candidate
    return None


def parse_invoice_fields(text: str) -> Tuple[Dict[str, object], List[str]]:
    """Pull invoice fields out of a text layer. Returns (fields found, notes about the rest).

    Nothing is inferred from nothing: a field the text does not state stays absent and is named
    in the notes. In particular the gross amount is never computed from net plus tax - that would
    manufacture the very arithmetic consistency the § 14 UStG audit is supposed to test.
    """
    fields: Dict[str, object] = {}
    missing: List[str] = []

    vendor_name = _guess_vendor_name(text)
    if vendor_name:
        fields["vendor_name"] = vendor_name
    else:
        missing.append("vendor name")

    vat_id = _first_group(_RE_VAT_ID, text)
    if vat_id:
        fields["vendor_vat_id"] = vat_id.replace(" ", "").upper()
    else:
        missing.append("VAT ID")

    email = _RE_EMAIL.search(text)
    if email:
        fields["vendor_email"] = email.group(0)
    else:
        missing.append("vendor email")

    invoice_number = _first_group(_RE_INVOICE_NUMBER, text)
    if invoice_number:
        fields["invoice_number"] = invoice_number
    else:
        missing.append("invoice number")

    for key, regex, label in (
        ("invoice_date", _RE_INVOICE_DATE, "invoice date"),
        ("delivery_date", _RE_DELIVERY_DATE, "delivery date"),
    ):
        raw = _first_group(regex, text)
        iso = normalise_date(raw) if raw else None
        if iso:
            fields[key] = iso
        else:
            missing.append(label)

    for key, regex, label in (
        ("net_amount", _RE_NET, "net amount"),
        ("tax_amount", _RE_TAX, "tax amount"),
        ("gross_amount", _RE_GROSS, "gross amount"),
    ):
        raw = _first_group(regex, text)
        amount = parse_amount(raw) if raw else None
        if amount is not None:
            fields[key] = amount
        else:
            missing.append(label)

    rate = _first_group(_RE_TAX_RATE, text)
    parsed_rate = parse_amount(rate) if rate else None
    if parsed_rate is not None:
        fields["tax_rate"] = parsed_rate
    else:
        missing.append("tax rate")

    for token, code in _CURRENCY_TOKENS.items():
        if token in text:
            fields["currency"] = code
            break

    notes = [
        "line items are not parsed by the local reader; only invoice totals are read",
    ]
    if vendor_name:
        notes.append(f"vendor name taken from the first letterhead line: '{vendor_name}'")
    if missing:
        notes.append("not found in the text layer: " + ", ".join(missing))
    return fields, notes
