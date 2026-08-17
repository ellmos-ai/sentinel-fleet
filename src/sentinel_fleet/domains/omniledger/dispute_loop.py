"""Autonomous Self-Healing Vendor Dispute & Correction Loop with GDPR Privacy Gates."""

from typing import Dict, Any
from sentinel_fleet.domains.omniledger.models import InvoiceDocument
from sentinel_fleet.memory.hooker import memory_hooker
from sentinel_fleet.core.privacy_contacts import privacy_contact_hub


class DisputeCommunicator:
    @staticmethod
    def generate_dispute_resolution(doc: InvoiceDocument) -> str:
        """Generates a legally sound, courteous correction request to the vendor under strict GDPR controls."""
        # 1. Check Privacy Contact Hub & Opt-Out Blacklist
        perm = privacy_contact_hub.validate_send_permission(doc.vendor_email)
        if not perm["allowed"]:
            doc.dispute_email_draft = f"BLOCKED BY PRIVACY GATE: {perm['reason']}"
            return doc.dispute_email_draft

        violations_formatted = "\n".join(f"- {v}" for v in doc.compliance_violations)
        
        # 2. Inject corporate memory / policy context
        memory_clues = memory_hooker.inject_context("Rechnungsprüfung § 14 UStG Korrekturanforderung")

        body = (
            f"Sehr geehrte Damen und Herren,\n\n"
            f"vielen Dank für die Zusendung Ihrer Rechnung Nr. {doc.invoice_number} vom {doc.invoice_date} über brutto {doc.gross_amount:.2f} {doc.currency}.\n\n"
            f"Bei unserer automatisierten steuerlichen Eingangsprüfung gemäß § 14 UStG wurden folgende formale Abweichungen festgestellt:\n"
            f"{violations_formatted}\n\n"
            f"Gemäß den steuerrechtlichen Vorgaben der Bundesrepublik Deutschland sind wir zum Vorsteuerabzug nur bei Vorliegen aller Pflichtangaben berechtigt. "
            f"Wir bitten Sie daher höflich, uns eine entsprechend korrigierte Rechnung (oder Rechnungskorrektur) zukommen zu lassen.\n\n"
            f"Bis zum Eingang des korrigierten Belegs wurde die automatische Zahlungsanweisung für diese Rechnung temporär pausiert.\n\n"
            f"Datenschutz-Hinweis: Ihre Kontaktdaten werden bei uns gemäß DSGVO Schutzstufe S3 zur steuerlichen Erfüllung verarbeitet.\n\n"
            f"Mit freundlichen Grüßen\n"
            f"SentinelFleet Autonomous Accounting Governance"
        )

        doc.dispute_email_draft = body
        return body


dispute_communicator = DisputeCommunicator()
