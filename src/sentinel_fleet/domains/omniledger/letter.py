"""The vendor correction request as a real document instead of a string.

Adapted from the `report-forge` module (MIT, same author). What was taken is its three-phase
shape, which keeps generated documents auditable:

  source document  ->  a schema the content is bound to  ->  a template that renders it

Here that is `InvoiceDocument` -> `CorrectionLetter` -> `render_correction_letter_pdf()`. The
middle step is the point: the renderer never reaches into the invoice, so what a letter may state
is exactly the set of fields the schema declares, and a defect list can be read off the document
before anything is drawn.

What was deliberately not taken: report-forge renders Word templates through python-docx and
carries a session workspace with an anonymisation pass. Both are wrong here - the deployment
already depends on fpdf2 for transcript export (no new dependency for a second document type),
a container has no session directory worth keeping, and the pseudonymisation this fleet needs is
already in Model Armor and the privacy contact hub.

The letter is never stored. It is derived, byte-identical, from the invoice plus the moment the
approval ticket was opened - so a download today and a download next week produce the same
document with the same deadline, without a copy anywhere that could drift from the ticket.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fpdf import FPDF
from pydantic import BaseModel, Field

from sentinel_fleet.core.pdf_text import pdf_safe
from sentinel_fleet.domains.omniledger.models import InvoiceDocument

# § 271 BGB leaves the period to the parties; two weeks is the customary window for a corrected
# invoice and matches the wording of the drafted email, so both artefacts state the same term.
CORRECTION_DEADLINE_DAYS = 14

SENDER_NAME = "SentinelFleet Autonomous Accounting Governance"
SENDER_ADDRESS = "OmniLedger Intake, Accounts Payable"

# Layout constants of a plain business letter, in millimetres.
PAGE_MARGIN = 20.0
LINE_HEIGHT = 5.2


class CorrectionLetter(BaseModel):
    """The bound schema: everything a correction letter may say, and nothing else."""

    reference: str
    recipient_name: str
    recipient_address: Optional[str] = None
    recipient_email: Optional[str] = None
    subject: str
    invoice_number: str
    invoice_date: str
    gross_amount: float
    currency: str
    defects: List[str] = Field(default_factory=list)
    statute: str = "§ 14 UStG"
    issued_on: str
    deadline_on: str
    payment_hold: bool = True
    privacy_notice: str = (
        "Your contact details are processed under GDPR protection level S3 for the sole purpose "
        "of meeting our statutory tax obligations."
    )


def build_correction_letter(doc: InvoiceDocument, issued_at: float) -> CorrectionLetter:
    """Bind one audited invoice to the letter schema.

    `issued_at` is the epoch second the approval ticket was opened, not the current time: the
    deadline has to be the same on every render, and a letter that silently moves its own due
    date each time it is downloaded would be worthless as evidence.
    """
    issued = datetime.fromtimestamp(issued_at, tz=timezone.utc)
    deadline = issued + timedelta(days=CORRECTION_DEADLINE_DAYS)

    return CorrectionLetter(
        reference=f"{doc.id} / {doc.invoice_number}",
        recipient_name=doc.vendor_name or "Vendor",
        recipient_address=doc.vendor_address,
        recipient_email=doc.vendor_email,
        subject=f"Request for a corrected invoice - no. {doc.invoice_number}",
        invoice_number=doc.invoice_number or "(no invoice number stated)",
        invoice_date=doc.invoice_date or "(no date stated)",
        gross_amount=doc.gross_amount,
        currency=doc.currency,
        defects=list(doc.compliance_violations),
        issued_on=issued.strftime("%Y-%m-%d"),
        deadline_on=deadline.strftime("%Y-%m-%d"),
    )


class _LetterCanvas(FPDF):
    """The template. Everything it draws comes from the schema above."""

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(120, 131, 142)
        self.cell(
            0, 4,
            pdf_safe(f"{SENDER_NAME} - generated document, page {self.page_no()}"),
            align="C",
        )


def render_correction_letter_pdf(letter: CorrectionLetter) -> bytes:
    """Draw the bound letter. Pure rendering: no field is read from anywhere but the schema."""
    pdf = _LetterCanvas()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    pdf.add_page()

    def block(text: str, height: float = LINE_HEIGHT):
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(w=0, h=height, text=pdf_safe(text), align="L")

    # Letterhead
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(14, 20, 25)
    block(SENDER_NAME, 6.5)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(120, 131, 142)
    block(SENDER_ADDRESS, 4.5)
    pdf.ln(2)
    pdf.set_draw_color(205, 211, 218)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)

    # Recipient block
    pdf.set_font("Helvetica", "", 10.5)
    pdf.set_text_color(14, 20, 25)
    block(letter.recipient_name)
    if letter.recipient_address:
        block(letter.recipient_address)
    if letter.recipient_email:
        block(letter.recipient_email)
    pdf.ln(6)

    # Reference line and date
    pdf.set_font("Courier", "", 8.5)
    pdf.set_text_color(120, 131, 142)
    block(f"Our reference {letter.reference}   Date {letter.issued_on}", 4.5)
    pdf.ln(3)

    # Subject
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(14, 20, 25)
    block(letter.subject, 6)
    pdf.ln(3)

    # Body
    pdf.set_font("Helvetica", "", 10.5)
    block("Dear Sir or Madam,")
    pdf.ln(2)
    block(
        f"thank you for your invoice no. {letter.invoice_number} dated {letter.invoice_date} "
        f"for a gross amount of {letter.gross_amount:.2f} {letter.currency}."
    )
    pdf.ln(2)
    block(
        f"Our automated intake audit under {letter.statute} found the following formal defects "
        "in that document:"
    )
    pdf.ln(1)

    # Defect list
    pdf.set_font("Helvetica", "", 10)
    if letter.defects:
        for index, defect in enumerate(letter.defects, start=1):
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(w=0, h=LINE_HEIGHT, text=pdf_safe(f"{index}.  {defect}"), align="L")
    else:
        pdf.set_x(pdf.l_margin + 4)
        pdf.multi_cell(w=0, h=LINE_HEIGHT, text=pdf_safe("(no defects recorded)"), align="L")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10.5)
    block(
        "Under German tax law we may only deduct input VAT once all mandatory fields are present. "
        "We therefore ask you to send us a corrected invoice, or a formal invoice correction, "
        f"by {letter.deadline_on} ({CORRECTION_DEADLINE_DAYS} days from the date of this letter)."
    )
    pdf.ln(2)
    if letter.payment_hold:
        block(
            "Until the corrected document reaches us, the automatic payment instruction for this "
            "invoice remains on hold."
        )
        pdf.ln(2)

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(120, 131, 142)
    block(f"Data protection notice: {letter.privacy_notice}", 4.5)
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 10.5)
    pdf.set_text_color(14, 20, 25)
    block("Kind regards")
    block(SENDER_NAME)

    return bytes(pdf.output())


def letter_filename(letter: CorrectionLetter) -> str:
    """A file name an operator can file without renaming it."""
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in letter.invoice_number)
    return f"correction-letter-{stem or 'invoice'}.pdf"
