"""Agent identity and role management."""

from enum import Enum
from typing import Set
from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    FINANCE_TASKMASTER = "finance_taskmaster"
    COMPLIANCE_AUDITOR = "compliance_auditor"
    LEDGER_RECONCILER = "ledger_reconciler"
    VENDOR_COMMUNICATOR = "vendor_communicator"
    SECURITY_SENTRY = "security_sentry"
    WEB_RESEARCHER = "web_researcher"


class AgentStatus(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    WAITING_APPROVAL = "waiting_approval"
    QUARANTINED = "quarantined"
    ERROR = "error"


class AgentIdentity(BaseModel):
    agent_id: str
    name: str
    role: AgentRole
    description: str
    allowed_tools: Set[str] = Field(default_factory=set)
    status: AgentStatus = AgentStatus.IDLE
    consecutive_steps: int = 0
    quarantine_reason: str = ""

    def is_tool_scoped(self, tool_name: str) -> bool:
        """Check if a tool is explicitly permitted for this agent's identity."""
        if "*" in self.allowed_tools:
            return True
        return tool_name in self.allowed_tools
