"""TicketMaster: Human-in-the-Loop Triage, Capture & Approval Gate."""

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
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
        priority: TicketPriority = TicketPriority.NORMAL
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
            status=TicketStatus.PENDING_APPROVAL
        )
        self._store.put(ticket_id, ticket)
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        return self._store.get(ticket_id)

    def approve_ticket(self, ticket_id: str, comment: str = "Approved by operator") -> Ticket:
        ticket = self._store.get(ticket_id)
        if not ticket:
            raise TicketNotFoundError(ticket_id)
        if ticket.status != TicketStatus.PENDING_APPROVAL:
            raise TicketResolutionError(ticket_id, f"already resolved as '{ticket.status.value}'")

        ticket.status = TicketStatus.APPROVED
        ticket.resolved_at = time.time()
        ticket.resolution_comment = comment
        self._store.put(ticket_id, ticket)
        return ticket

    def reject_ticket(self, ticket_id: str, reason: str = "Rejected by operator") -> Ticket:
        ticket = self._store.get(ticket_id)
        if not ticket:
            raise TicketNotFoundError(ticket_id)
        if ticket.status != TicketStatus.PENDING_APPROVAL:
            raise TicketResolutionError(ticket_id, f"already resolved as '{ticket.status.value}'")

        ticket.status = TicketStatus.REJECTED
        ticket.resolved_at = time.time()
        ticket.resolution_comment = reason
        self._store.put(ticket_id, ticket)
        return ticket

    def get_pending_tickets(self) -> List[Ticket]:
        return [t for t in self._store.list_all() if t.status == TicketStatus.PENDING_APPROVAL]

    def list_all(self) -> List[Ticket]:
        tickets = self._store.list_all()
        tickets.sort(key=lambda t: t.created_at, reverse=True)
        return tickets


ticket_master = TicketMaster()
