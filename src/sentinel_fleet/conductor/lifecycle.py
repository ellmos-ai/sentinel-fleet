"""Agent Lifecycle & Spawning Manager based on coma."""

from typing import Dict, List, Optional
from sentinel_fleet.core.identity import AgentIdentity, AgentRole, AgentStatus


class LifecycleManager:
    def __init__(self):
        self._fleet: Dict[str, AgentIdentity] = {}
        self._seed_default_fleet()

    def _seed_default_fleet(self):
        default_agents = [
            AgentIdentity(
                agent_id="agent:orchestrator",
                name="Fleet Conductor",
                role=AgentRole.ORCHESTRATOR,
                description="Central coordinator that decomposes tasks and delegates to sub-agents.",
                allowed_tools={"query_memory_bank", "create_task", "assign_task", "dispatch_swarm"}
            ),
            AgentIdentity(
                agent_id="agent:invoice-extractor",
                name="Vision Extractor",
                role=AgentRole.FINANCE_TASKMASTER,
                description="Multimodal vision agent that extracts structured line items from PDFs/images.",
                allowed_tools={"extract_invoice_multimodal", "query_memory_bank"}
            ),
            AgentIdentity(
                agent_id="agent:compliance-auditor",
                name="Tax Compliance Sentinel",
                role=AgentRole.COMPLIANCE_AUDITOR,
                description="Audits invoice data against § 14 UStG and accounting standards.",
                allowed_tools={"validate_tax_compliance", "query_memory_bank", "flag_compliance_error"}
            ),
            AgentIdentity(
                agent_id="agent:ledger-reconciler",
                name="Ledger Reconciler",
                role=AgentRole.LEDGER_RECONCILER,
                description="Books verified records into Firestore and generates exports.",
                allowed_tools={"store_memory_bank", "create_reconciliation_draft", "execute_bank_transfer"}
            ),
            AgentIdentity(
                agent_id="agent:vendor-dispute",
                name="Dispute Communicator",
                role=AgentRole.VENDOR_COMMUNICATOR,
                description="Self-healing communication agent that drafts resolution emails to vendors.",
                allowed_tools={"draft_vendor_dispute_email", "send_external_email", "query_memory_bank"}
            )
        ]
        for a in default_agents:
            self._fleet[a.agent_id] = a

    def get_agent(self, agent_id: str) -> Optional[AgentIdentity]:
        return self._fleet.get(agent_id)

    def list_fleet(self) -> List[AgentIdentity]:
        return list(self._fleet.values())

    def update_agent_status(self, agent_id: str, status: AgentStatus, reason: str = ""):
        agent = self.get_agent(agent_id)
        if agent:
            agent.status = status
            if reason:
                agent.quarantine_reason = reason


lifecycle_manager = LifecycleManager()
