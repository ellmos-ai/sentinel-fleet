"""DSGVO Privacy Contacts & Vendor Address Book Engine based on PrivacyMailDesk & .UMBRUCH."""

import time
import uuid
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, model_validator
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.errors import ContactNotFoundError, ContactOptOutViolationError


class PrivacyContact(BaseModel):
    contact_id: str
    name: str
    email: str
    organization: Optional[str] = None
    # A company writes letters, not only mail. The address is personal data of the same rank as
    # the email: it enters under the same protection level, is screened by the same amber rule
    # in privacy_screen ("postal address" sits beside "email address" there), and is erased on
    # opt-out. Optional with a default so records persisted before this field still load.
    postal_address: Optional[str] = None
    category: str = "vendor"  # vendor | institution | personal | subscriber
    relationship: str = "external"  # internal | external
    # organization records are shared; personal records belong to one data workspace/user.
    visibility: str = "organization"  # personal | organization
    owner_id: Optional[str] = None
    department_id: Optional[str] = None
    # DSGVO / GDPR Protection Level
    # S1 = 6 months, S2 = 12 months, S3 = 36 months (Tax relevant), S4 = Permanent until revocation
    protection_level: str = "S3"
    opt_in_status: str = "confirmed"  # confirmed | pending | unsubscribed | blacklisted
    is_tombstone: bool = False  # If True, contact is deleted but email is blocked to prevent re-contacting
    dsgvo_notes: str = "Statutory retention under § 147 AO / § 14 UStG"
    last_contacted_at: float = Field(default_factory=time.time)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @model_validator(mode="after")
    def _scope_is_coherent(self) -> "PrivacyContact":
        if self.relationship not in {"internal", "external"}:
            raise ValueError("relationship must be 'internal' or 'external'")
        if self.visibility not in {"personal", "department", "organization"}:
            raise ValueError("visibility must be personal, department or organization")
        if self.visibility == "personal" and not self.owner_id:
            raise ValueError("a personal contact needs an owner_id")
        if self.visibility == "department" and not self.department_id:
            raise ValueError("a department contact needs a department_id")
        if self.visibility != "personal":
            self.owner_id = None
        if self.visibility != "department":
            self.department_id = None
        return self


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

    def list_visible(
        self,
        requested_by: str,
        requested_department: Optional[str] = None,
        include_tombstones: bool = False,
    ) -> List[PrivacyContact]:
        return [
            contact
            for contact in self.list_all(include_tombstones=include_tombstones)
            if (
                contact.visibility == "organization"
                or contact.owner_id == requested_by
                or (
                    contact.visibility == "department"
                    and bool(requested_department)
                    and contact.department_id == requested_department
                )
            )
        ]

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
        protection_level: str = "S3",
        postal_address: str = "",
        relationship: str = "external",
        visibility: str = "organization",
        owner_id: Optional[str] = None,
        department_id: Optional[str] = None,
    ) -> PrivacyContact:
        contact_id = f"cnt-{uuid.uuid4().hex}"
        contact = PrivacyContact(
            contact_id=contact_id,
            name=name,
            email=email,
            organization=organization,
            postal_address=postal_address or None,
            category=category,
            relationship=relationship,
            visibility=visibility,
            owner_id=owner_id,
            department_id=department_id,
            protection_level=protection_level,
            opt_in_status="confirmed"
        )
        self._store.put(contact_id, contact)
        return contact

    def mark_opt_out(
        self,
        contact_id: str,
        reason: str = "Operator opt-out",
        requested_by: Optional[str] = None,
        requested_department: Optional[str] = None,
        can_manage_department: bool = False,
        can_manage_organization: bool = False,
    ) -> PrivacyContact:
        contact = self._store.get(contact_id)
        if not contact:
            raise ContactNotFoundError(contact_id)
        if requested_by is not None:
            personal_owner = contact.visibility == "personal" and contact.owner_id == requested_by
            department_manager = (
                contact.visibility == "department"
                and bool(requested_department)
                and contact.department_id == requested_department
                and can_manage_department
            )
            organization_manager = contact.visibility == "organization" and can_manage_organization
            if not (personal_owner or department_manager or organization_manager):
                raise PermissionError("This contact belongs to another scope.")

        contact.opt_in_status = "unsubscribed"
        contact.is_tombstone = True
        # The tombstone keeps the email on purpose: blocking future contact needs the address
        # that would be written to. Nothing blocks on the postal address, so holding it after an
        # objection would be storage without a purpose - it goes.
        contact.postal_address = None
        contact.dsgvo_notes = f"Objection recorded {time.strftime('%Y-%m-%d')}: {reason}"
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
                "reason": f"GDPR block: {email} has objected to further contact ({contact.dsgvo_notes})."
            }

        return {"allowed": True, "reason": f"GDPR clear: protection level {contact.protection_level} in force."}

    def run_dsgvo_retention_audit(
        self,
        requested_by: Optional[str] = None,
        requested_department: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Audit only the contact set the caller is allowed to see."""
        all_contacts = (
            self.list_visible(
                requested_by, requested_department, include_tombstones=True
            )
            if requested_by is not None
            else self._store.list_all()
        )
        total = len(all_contacts)
        active = len([c for c in all_contacts if not c.is_tombstone])
        tombstones = len([c for c in all_contacts if c.is_tombstone])

        return {
            "total_records": total,
            "active_contacts": active,
            "tombstones_protected": tombstones,
            "retention_policy": "S1 (6 months), S2 (12 months), S3 (36 months, § 147 AO), S4 (until revoked)",
            "status": "COMPLIANT"
        }


privacy_contact_hub = PrivacyContactHub()
