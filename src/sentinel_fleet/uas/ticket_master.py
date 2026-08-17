"""TicketMaster: Human-in-the-Loop Triage, Capture & Approval Gate."""

import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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
        self._tickets: Dict[str, Ticket] = {}

    def create_approval_ticket(
        self,
        title: str,
        description: str,
        agent_id: str,
        tool_name: str,
        payload: Dict[str, Any],
        priority: TicketPriority = TicketPriority.NORMAL
    ) -> Ticket:
        ticket_id = f"TICK-{len(self._tickets)+1:04d}"
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
        self._tickets[ticket_id] = ticket
        return ticket

    def approve_ticket(self, ticket_id: str, comment: str = "Approved by operator") -> Optional[Ticket]:
        ticket = self._tickets.get(ticket_id)
        if ticket:
            ticket.status = TicketStatus.APPROVED
            ticket.resolved_at = time.time()
            ticket.resolution_comment = comment
        return ticket

    def reject_ticket(self, ticket_id: str, reason: str = "Rejected by operator") -> Optional[Ticket]:
        ticket = self._tickets.get(ticket_id)
        if ticket:
            ticket.status = TicketStatus.REJECTED
            ticket.resolved_at = time.time()
            ticket.resolution_comment = reason
        return ticket

    def get_pending_tickets(self) -> List[Ticket]:
        return [t for t in self._tickets.values() if t.status == TicketStatus.PENDING_APPROVAL]

    def list_all(self) -> List[Ticket]:
        return list(reversed(list(self._tickets.values())))


ticket_master = TicketMaster()
