"""DSGVO Privacy Contacts & Vendor Address Book Engine based on PrivacyMailDesk & .UMBRUCH."""

import time
import uuid
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, model_validator
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.errors import ContactNotFoundError


DEFAULT_ORGANIZATION_ID = "sentinel-demo"
LEGACY_ORGANIZATION_ID = "legacy-unassigned"
RETENTION_SECONDS_BY_LEVEL = {
    "S1": 183 * 24 * 60 * 60,
    "S2": 365 * 24 * 60 * 60,
    "S3": 1095 * 24 * 60 * 60,
}


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
    organization_id: str = LEGACY_ORGANIZATION_ID
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
        if not self.organization_id.strip():
            raise ValueError("a contact needs an organization_id")
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
                dsgvo_notes="Business contact: invoicing correspondence under § 14 UStG",
                organization_id=DEFAULT_ORGANIZATION_ID,
            ),
            PrivacyContact(
                contact_id="cnt-office",
                name="Accounting, Office Supplies Ltd",
                email="invoices@officesupplies.eu",
                organization="Office Supplies Ltd",
                category="vendor",
                protection_level="S3",
                opt_in_status="confirmed",
                dsgvo_notes="Vendor contract & document exchange",
                organization_id=DEFAULT_ORGANIZATION_ID,
            ),
            PrivacyContact(
                contact_id="cnt-cybersec",
                name="CyberSec Defense Corp AP",
                email="ap@cybersec-defense.com",
                organization="CyberSec Defense Corp",
                category="vendor",
                protection_level="S3",
                opt_in_status="confirmed",
                dsgvo_notes="Security services provider",
                organization_id=DEFAULT_ORGANIZATION_ID,
            ),
            PrivacyContact(
                contact_id="cnt-acme",
                name="Acme Consulting Services",
                email="finance@acme-consulting.de",
                organization="Acme Consulting GmbH",
                category="vendor",
                protection_level="S3",
                opt_in_status="confirmed",
                dsgvo_notes="Consulting contract",
                organization_id=DEFAULT_ORGANIZATION_ID,
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
            stored.organization_id = DEFAULT_ORGANIZATION_ID
            stored.visibility = "organization"
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
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
        include_tombstones: bool = False,
    ) -> List[PrivacyContact]:
        return [
            contact
            for contact in self.list_all(include_tombstones=include_tombstones)
            if (
                contact.organization_id == requested_organization
                and (
                    contact.visibility == "organization"
                    or (
                        contact.visibility == "personal"
                        and contact.owner_id == requested_by
                    )
                    or (
                        contact.visibility == "department"
                        and bool(requested_department)
                        and contact.department_id == requested_department
                    )
                )
            )
        ]

    def get_contact_by_id(self, contact_id: str) -> Optional[PrivacyContact]:
        return self._store.get(contact_id)

    def get_contact_by_email(
        self,
        email: str,
        requested_by: str = "operator",
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
    ) -> Optional[PrivacyContact]:
        """Return a visible match, preferring a visible suppression over an active duplicate."""
        matches = [
            contact
            for contact in self.list_visible(
                requested_by,
                requested_department,
                requested_organization,
                include_tombstones=True,
            )
            if contact.email.lower() == (email or "").lower()
        ]
        if not matches:
            return None
        return next(
            (
                contact for contact in matches
                if contact.is_tombstone
                or contact.opt_in_status in {"unsubscribed", "blacklisted"}
            ),
            matches[0],
        )

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
        organization_id: str = DEFAULT_ORGANIZATION_ID,
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
            organization_id=organization_id,
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
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
        can_manage_department: bool = False,
        can_manage_organization: bool = False,
    ) -> PrivacyContact:
        contact = self._store.get(contact_id)
        if not contact:
            raise ContactNotFoundError(contact_id)
        if requested_by is not None:
            same_organization = contact.organization_id == requested_organization
            personal_owner = (
                same_organization
                and contact.visibility == "personal"
                and contact.owner_id == requested_by
            )
            department_manager = (
                same_organization
                and contact.visibility == "department"
                and bool(requested_department)
                and contact.department_id == requested_department
                and can_manage_department
            )
            organization_manager = (
                same_organization
                and contact.visibility == "organization"
                and can_manage_organization
            )
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

    def validate_send_permission(
        self,
        email: str,
        requested_by: str = "operator",
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
    ) -> Dict[str, Any]:
        """Validate correspondence against suppressions visible in the caller's tenant scope."""
        contact = self.get_contact_by_email(
            email,
            requested_by=requested_by,
            requested_department=requested_department,
            requested_organization=requested_organization,
        )
        if not contact:
            return {
                "allowed": True,
                "reason": (
                    "New transaction contact (Ad-hoc B2B) in organization "
                    f"{requested_organization}"
                ),
                "scope": None,
            }

        if contact.is_tombstone or contact.opt_in_status in ["unsubscribed", "blacklisted"]:
            return {
                "allowed": False,
                "reason": (
                    f"GDPR block in {contact.visibility} scope: {email} has objected to "
                    f"further contact ({contact.dsgvo_notes})."
                ),
                "scope": contact.visibility,
            }

        return {
            "allowed": True,
            "reason": f"GDPR clear: protection level {contact.protection_level} in force.",
            "scope": contact.visibility,
        }

    def run_dsgvo_retention_audit(
        self,
        requested_by: Optional[str] = None,
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
        *,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Report configured retention expiries in the caller's visible contact set.

        This is deliberately an audit, not an automatic deletion job: a human must resolve
        purpose, legal hold and any overriding obligation before destructive processing.
        Suppression tombstones remain excluded because deleting their address would allow an
        objecting contact to be contacted again.
        """
        all_contacts = (
            self.list_visible(
                requested_by,
                requested_department,
                requested_organization,
                include_tombstones=True,
            )
            if requested_by is not None
            else self._store.list_all()
        )
        total = len(all_contacts)
        active = len([c for c in all_contacts if not c.is_tombstone])
        tombstones = len([c for c in all_contacts if c.is_tombstone])
        audited_at = time.time() if now is None else now
        retention_due = []
        unknown_levels = []
        for contact in all_contacts:
            if contact.is_tombstone or contact.protection_level == "S4":
                continue
            retention_seconds = RETENTION_SECONDS_BY_LEVEL.get(contact.protection_level)
            if retention_seconds is None:
                unknown_levels.append(contact.contact_id)
                continue
            expires_at = contact.last_contacted_at + retention_seconds
            if expires_at <= audited_at:
                retention_due.append({
                    "contact_id": contact.contact_id,
                    "protection_level": contact.protection_level,
                    "expired_at": expires_at,
                })

        return {
            "total_records": total,
            "active_contacts": active,
            "tombstones_protected": tombstones,
            "retention_policy": (
                "Configured operational windows: S1 183 days, S2 365 days, "
                "S3 1095 days, S4 until revocation"
            ),
            "retention_due": retention_due,
            "unknown_protection_levels": unknown_levels,
            "status": "ACTION_REQUIRED" if retention_due or unknown_levels else "COMPLIANT",
            "assessment_scope": "operational policy audit; not a legal-compliance determination",
        }


privacy_contact_hub = PrivacyContactHub()
