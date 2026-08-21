"""TicketMaster: Human-in-the-Loop Triage, Capture & Approval Gate."""

import time
import uuid
from enum import Enum
from typing import Any, Dict, Iterable, List, Literal, Optional
from pydantic import BaseModel, Field
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.errors import TicketNotFoundError, TicketResolutionError


class TicketStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class TicketPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Ticket(BaseModel):
    ticket_id: str
    title: str
    description: str
    agent_id: str
    tool_name: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: TicketPriority = TicketPriority.NORMAL
    status: TicketStatus = TicketStatus.PENDING_APPROVAL
    created_at: float = Field(default_factory=time.time)
    resolved_at: Optional[float] = None
    resolution_comment: Optional[str] = None
    requested_by: Optional[str] = None
    owner_id: str = "legacy-unassigned"
    assigned_to_role: Optional[str] = None
    assigned_to_user: Optional[str] = None
    organization_id: str = "legacy-unassigned"
    department_id: Optional[str] = None
    visibility: Literal["private", "department", "organization"] = "private"
    resolved_by: Optional[str] = None


class TicketMaster:
    def __init__(self):
        self._store = get_store("tickets", Ticket)

    def create_approval_ticket(
        self,
        title: str,
        description: str,
        agent_id: str,
        tool_name: str,
        payload: Dict[str, Any],
        priority: TicketPriority = TicketPriority.NORMAL,
        requested_by: Optional[str] = None,
        assigned_to_role: Optional[str] = None,
        assigned_to_user: Optional[str] = None,
        organization_id: str = "legacy-unassigned",
        owner_id: Optional[str] = None,
        department_id: Optional[str] = None,
        visibility: Literal["private", "department", "organization"] = "private",
    ) -> Ticket:
        # Collision-free: a counter over a shared store races and repeats ids after deletions
        ticket_id = f"TICK-{uuid.uuid4().hex[:8].upper()}"
        ticket = Ticket(
            ticket_id=ticket_id,
            title=title,
            description=description,
            agent_id=agent_id,
            tool_name=tool_name,
            payload=payload,
            priority=priority,
            status=TicketStatus.PENDING_APPROVAL,
            requested_by=requested_by,
            owner_id=owner_id or requested_by or "legacy-unassigned",
            assigned_to_role=assigned_to_role,
            assigned_to_user=assigned_to_user,
            organization_id=organization_id,
            department_id=department_id,
            visibility=visibility,
        )
        self._store.put(ticket_id, ticket)
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        return self._store.get(ticket_id)

    @staticmethod
    def can_read(
        ticket: Ticket,
        requested_by: str,
        actor_user_id: str,
        organization_id: str,
        department_id: Optional[str] = None,
        actor_roles: Optional[Iterable[str]] = None,
    ) -> bool:
        """Ticket payloads are private unless ownership, assignment or sharing says otherwise."""
        if ticket.organization_id in {"", "legacy-unassigned"}:
            return False
        if ticket.organization_id != organization_id:
            return False
        if ticket.owner_id == requested_by or ticket.requested_by == requested_by:
            return True
        roles = set(actor_roles or ())
        if ticket.assigned_to_user or ticket.assigned_to_role:
            user_match = not ticket.assigned_to_user or ticket.assigned_to_user == actor_user_id
            role_match = not ticket.assigned_to_role or ticket.assigned_to_role in roles
            return user_match and role_match
        if ticket.visibility == "organization":
            return True
        if ticket.visibility == "department":
            return bool(department_id and ticket.department_id == department_id)
        return False

    def list_visible(
        self,
        requested_by: str,
        actor_user_id: str,
        organization_id: str,
        department_id: Optional[str] = None,
        actor_roles: Optional[Iterable[str]] = None,
    ) -> List[Ticket]:
        return [
            ticket for ticket in self.list_all()
            if self.can_read(
                ticket,
                requested_by,
                actor_user_id,
                organization_id,
                department_id,
                actor_roles,
            )
        ]

    @staticmethod
    def _require_assigned_actor(
        ticket: Ticket,
        decided_by: Optional[str],
        decider_user_id: Optional[str],
        decider_roles: Optional[Iterable[str]],
        decider_organization_id: Optional[str],
    ) -> None:
        """Enforce tenant, explicit user and explicit role assignment before resolution."""
        decider_user_id = decider_user_id or decided_by
        if not decided_by or not decider_user_id or not decider_organization_id:
            raise PermissionError(f"Ticket '{ticket.ticket_id}' requires a verified actor.")
        if decider_organization_id != ticket.organization_id:
            raise PermissionError(
                f"Actor organization cannot resolve ticket '{ticket.ticket_id}'."
            )
        if ticket.assigned_to_user and decider_user_id != ticket.assigned_to_user:
            raise PermissionError(
                f"Ticket '{ticket.ticket_id}' is assigned to user '{ticket.assigned_to_user}'."
            )
        roles = {decider_roles} if isinstance(decider_roles, str) else set(decider_roles or ())
        if ticket.assigned_to_role and ticket.assigned_to_role not in roles:
            raise PermissionError(
                f"Ticket '{ticket.ticket_id}' is assigned to role '{ticket.assigned_to_role}'."
            )
        if not ticket.assigned_to_user and not ticket.assigned_to_role:
            if ticket.owner_id != decided_by:
                raise PermissionError(
                    f"Only the ticket owner may resolve unassigned ticket '{ticket.ticket_id}'."
                )

    def approve_ticket(
        self,
        ticket_id: str,
        comment: str = "Approved by operator",
        *,
        decided_by: Optional[str] = None,
        decider_user_id: Optional[str] = None,
        decider_roles: Optional[Iterable[str]] = None,
        decider_organization_id: Optional[str] = None,
    ) -> Ticket:
        ticket = self._store.get(ticket_id)
        if not ticket:
            raise TicketNotFoundError(ticket_id)
        if ticket.status != TicketStatus.PENDING_APPROVAL:
            raise TicketResolutionError(ticket_id, f"already resolved as '{ticket.status.value}'")
        self._require_assigned_actor(
            ticket, decided_by, decider_user_id, decider_roles, decider_organization_id
        )

        ticket.status = TicketStatus.APPROVED
        ticket.resolved_at = time.time()
        ticket.resolution_comment = comment
        ticket.resolved_by = decided_by
        self._store.put(ticket_id, ticket)
        return ticket

    def reject_ticket(
        self,
        ticket_id: str,
        reason: str = "Rejected by operator",
        *,
        decided_by: Optional[str] = None,
        decider_user_id: Optional[str] = None,
        decider_roles: Optional[Iterable[str]] = None,
        decider_organization_id: Optional[str] = None,
    ) -> Ticket:
        ticket = self._store.get(ticket_id)
        if not ticket:
            raise TicketNotFoundError(ticket_id)
        if ticket.status != TicketStatus.PENDING_APPROVAL:
            raise TicketResolutionError(ticket_id, f"already resolved as '{ticket.status.value}'")
        self._require_assigned_actor(
            ticket, decided_by, decider_user_id, decider_roles, decider_organization_id
        )

        ticket.status = TicketStatus.REJECTED
        ticket.resolved_at = time.time()
        ticket.resolution_comment = reason
        ticket.resolved_by = decided_by
        self._store.put(ticket_id, ticket)
        return ticket

    def withdraw_ticket(
        self,
        ticket_id: str,
        *,
        requested_by: str,
        requester_organization_id: str,
        reason: str = "Withdrawn by requester",
    ) -> Ticket:
        """Let the original requester withdraw a still-pending approval request.

        Withdrawal is intentionally separate from an approver rejection: it neither bypasses
        the assigned user/role nor pretends the requester acted as that approver.
        """
        ticket = self._store.get(ticket_id)
        if not ticket:
            raise TicketNotFoundError(ticket_id)
        if ticket.status != TicketStatus.PENDING_APPROVAL:
            raise TicketResolutionError(ticket_id, f"already resolved as '{ticket.status.value}'")
        if (
            ticket.requested_by != requested_by
            or ticket.organization_id != requester_organization_id
        ):
            raise PermissionError(f"Only the in-organization requester may withdraw '{ticket_id}'.")
        ticket.status = TicketStatus.REJECTED
        ticket.resolved_at = time.time()
        ticket.resolution_comment = reason
        ticket.resolved_by = requested_by
        self._store.put(ticket_id, ticket)
        return ticket

    def get_pending_tickets(self) -> List[Ticket]:
        return [t for t in self._store.list_all() if t.status == TicketStatus.PENDING_APPROVAL]

    def list_all(self) -> List[Ticket]:
        tickets = self._store.list_all()
        tickets.sort(key=lambda t: t.created_at, reverse=True)
        return tickets


ticket_master = TicketMaster()
