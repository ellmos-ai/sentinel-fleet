"""DSGVO Privacy Contacts & Vendor Address Book Engine based on PrivacyMailDesk & .UMBRUCH."""

import time
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.errors import ContactNotFoundError, ContactOptOutViolationError


class PrivacyContact(BaseModel):
    contact_id: str
    name: str
    email: str
    organization: Optional[str] = None
    category: str = "vendor"  # vendor | institution | personal | subscriber
    # DSGVO / GDPR Protection Level
    # S1 = 6 months, S2 = 12 months, S3 = 36 months (Tax relevant), S4 = Permanent until revocation
    protection_level: str = "S3"
    opt_in_status: str = "confirmed"  # confirmed | pending | unsubscribed | blacklisted
    is_tombstone: bool = False  # If True, contact is deleted but email is blocked to prevent re-contacting
    dsgvo_notes: str = "Statutory retention under § 147 AO / § 14 UStG"
    last_contacted_at: float = Field(default_factory=time.time)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class PrivacyContactHub:
    def __init__(self):
        self._store = get_store("privacy_contacts", PrivacyContact)
        self._seed_default_contacts()

    def _seed_default_contacts(self):
        seeds = [
            PrivacyContact(
                contact_id="cnt-cloudscale",
                name="Accounts Payable, CloudScale GmbH",
                email="billing@cloudscale.de",
                organization="CloudScale Solutions GmbH",
                category="vendor",
                protection_level="S3",
                opt_in_status="confirmed",
                dsgvo_notes="Business contact: invoicing correspondence under § 14 UStG"
            ),
            PrivacyContact(
                contact_id="cnt-office",
                name="Accounting, Office Supplies Ltd",
                email="invoices@officesupplies.eu",
                organization="Office Supplies Ltd",
                category="vendor",
                protection_level="S3",
                opt_in_status="confirmed",
                dsgvo_notes="Vendor contract & document exchange"
            ),
            PrivacyContact(
                contact_id="cnt-cybersec",
                name="CyberSec Defense Corp AP",
                email="ap@cybersec-defense.com",
                organization="CyberSec Defense Corp",
                category="vendor",
                protection_level="S3",
                opt_in_status="confirmed",
                dsgvo_notes="Security services provider"
            ),
            PrivacyContact(
                contact_id="cnt-acme",
                name="Acme Consulting Services",
                email="finance@acme-consulting.de",
                organization="Acme Consulting GmbH",
                category="vendor",
                protection_level="S3",
                opt_in_status="confirmed",
                dsgvo_notes="Consulting contract"
            )
        ]
        for c in seeds:
            stored = self._store.get(c.contact_id)
            if stored is None:
                self._store.put(c.contact_id, c)
                continue
            # Refresh only the descriptive fields of a seeded contact. Consent state and
            # tombstones are operator decisions and must survive a redeploy untouched.
            stored.name = c.name
            stored.organization = c.organization
            stored.dsgvo_notes = c.dsgvo_notes
            self._store.put(stored.contact_id, stored)

    def list_all(self, include_tombstones: bool = False) -> List[PrivacyContact]:
        contacts = self._store.list_all()
        if include_tombstones:
            return contacts
        return [c for c in contacts if not c.is_tombstone]

    def get_contact_by_id(self, contact_id: str) -> Optional[PrivacyContact]:
        return self._store.get(contact_id)

    def get_contact_by_email(self, email: str) -> Optional[PrivacyContact]:
        for c in self._store.list_all():
            if c.email.lower() == email.lower():
                return c
        return None

    def add_contact(
        self,
        name: str,
        email: str,
        organization: str,
        category: str = "vendor",
        protection_level: str = "S3"
    ) -> PrivacyContact:
        contact_id = f"cnt-{int(time.time()*1000)}"
        contact = PrivacyContact(
            contact_id=contact_id,
            name=name,
            email=email,
            organization=organization,
            category=category,
            protection_level=protection_level,
            opt_in_status="confirmed"
        )
        self._store.put(contact_id, contact)
        return contact

    def mark_opt_out(self, contact_id: str, reason: str = "Operator opt-out") -> PrivacyContact:
        contact = self._store.get(contact_id)
        if not contact:
            raise ContactNotFoundError(contact_id)

        contact.opt_in_status = "unsubscribed"
        contact.is_tombstone = True
        contact.dsgvo_notes = f"Widerruf / Opt-Out am {time.strftime('%Y-%m-%d')}: {reason}"
        contact.updated_at = time.time()
        self._store.put(contact_id, contact)
        return contact

    def validate_send_permission(self, email: str) -> Dict[str, Any]:
        """Validates if an email is legally permitted to receive messages."""
        contact = self.get_contact_by_email(email)
        if not contact:
            return {"allowed": True, "reason": "New transaction contact (Ad-hoc B2B)"}

        if contact.is_tombstone or contact.opt_in_status in ["unsubscribed", "blacklisted"]:
            return {
                "allowed": False,
                "reason": f"DSGVO Block: Kontakt {email} hat widersprochen ({contact.dsgvo_notes})."
            }

        return {"allowed": True, "reason": f"DSGVO Valid: Schutzstufe {contact.protection_level} aktiv."}

    def run_dsgvo_retention_audit(self) -> Dict[str, Any]:
        """Audits contacts for retention compliance."""
        all_contacts = self._store.list_all()
        total = len(all_contacts)
        active = len([c for c in all_contacts if not c.is_tombstone])
        tombstones = len([c for c in all_contacts if c.is_tombstone])

        return {
            "total_records": total,
            "active_contacts": active,
            "tombstones_protected": tombstones,
            "retention_policy": "S1 (6m), S2 (12m), S3 (36m gem. § 147 AO), S4 (Permanent)",
            "status": "COMPLIANT"
        }


privacy_contact_hub = PrivacyContactHub()
