"""Agent Lifecycle & Spawning Manager based on coma."""

import threading
from typing import Dict, List, Optional
from sentinel_fleet.core.identity import AgentIdentity, AgentRole, AgentStatus


class LifecycleManager:
    def __init__(self):
        self._fleet: Dict[str, AgentIdentity] = {}
        self._lock = threading.RLock()
        self._seed_default_fleet()

    def _seed_default_fleet(self):
        default_agents = [
            AgentIdentity(
                agent_id="agent:orchestrator",
                name="Fleet Conductor",
                role=AgentRole.ORCHESTRATOR,
                description="Central coordinator for task decomposition and swarm delegation.",
                allowed_tools={"query_memory_bank", "create_task", "assign_task", "dispatch_swarm"}
            ),
            AgentIdentity(
                agent_id="agent:task-writer",
                name="TaskWriter",
                role=AgentRole.ORCHESTRATOR,
                description="Turns vague requests into atomic, idempotent task specifications.",
                allowed_tools={"query_memory_bank", "create_task"}
            ),
            AgentIdentity(
                agent_id="agent:task-maintainer",
                name="TaskMaintainer",
                role=AgentRole.ORCHESTRATOR,
                description="Watches the task lifecycle, clears blockers and cleans up orphaned tasks.",
                allowed_tools={"query_memory_bank", "update_task_state", "audit_task_health"}
            ),
            AgentIdentity(
                agent_id="agent:task-solver",
                name="TaskSolver",
                role=AgentRole.ORCHESTRATOR,
                description="Runs complex calculations, RAG research and code synthesis autonomously.",
                allowed_tools={"query_memory_bank", "execute_calculation", "solve_task", "execute_template"}
            ),
            AgentIdentity(
                agent_id="agent:system-auditor",
                name="SystemAuditor",
                role=AgentRole.SECURITY_SENTRY,
                description="Checks policies, validates audit receipts and watches OpenTelemetry spans.",
                allowed_tools={"query_memory_bank", "verify_receipts", "audit_telemetry"}
            ),
            AgentIdentity(
                agent_id="agent:invoice-extractor",
                name="Vision Extractor",
                role=AgentRole.FINANCE_TASKMASTER,
                description="Multimodal Gemini 3.5 Flash vision agent for document and table extraction.",
                allowed_tools={"extract_invoice_multimodal", "query_memory_bank"}
            ),
            AgentIdentity(
                agent_id="agent:compliance-auditor",
                name="Tax Compliance Sentinel",
                role=AgentRole.COMPLIANCE_AUDITOR,
                description="Audits documents against § 14 UStG mandatory fields and GoBD guidelines.",
                allowed_tools={"validate_tax_compliance", "query_memory_bank", "flag_compliance_error"}
            ),
            AgentIdentity(
                agent_id="agent:ledger-reconciler",
                name="Ledger Reconciler",
                role=AgentRole.LEDGER_RECONCILER,
                description="Books validated invoices into the ledger store and generates journal entries.",
                allowed_tools={"store_memory_bank", "create_reconciliation_draft", "execute_bank_transfer"}
            ),
            AgentIdentity(
                agent_id="agent:vendor-dispute",
                name="Dispute Communicator",
                role=AgentRole.VENDOR_COMMUNICATOR,
                description="Drafts autonomous, legally sound correction letters to vendors when defects are found.",
                allowed_tools={
                    "draft_vendor_dispute_email",
                    "render_dispute_letter",
                    "send_external_email",
                    "query_memory_bank",
                }
            ),
            AgentIdentity(
                agent_id="agent:chat-operator",
                name="Chat Operator",
                role=AgentRole.ORCHESTRATOR,
                description="Carries operator conversations and race verdicts through the gateway to the model.",
                allowed_tools={"chat_completion", "query_memory_bank"}
            )
        ]
        # One identity per race lane. The gateway holds a lock per agent, so lanes that shared
        # an identity would run one after another and their latencies would report the wait.
        for lane in range(1, 5):
            default_agents.append(AgentIdentity(
                agent_id=f"agent:race-lane-{lane}",
                name=f"Race Lane {lane}",
                role=AgentRole.ORCHESTRATOR,
                description=f"Isolated identity for lane {lane} of a side-by-side model race.",
                allowed_tools={"chat_completion"}
            ))
        for a in default_agents:
            self._fleet[a.agent_id] = a

    def get_agent(self, agent_id: str) -> Optional[AgentIdentity]:
        with self._lock:
            return self._fleet.get(agent_id)

    def list_fleet(self) -> List[AgentIdentity]:
        with self._lock:
            return list(self._fleet.values())

    def update_agent_status(self, agent_id: str, status: AgentStatus, reason: str = ""):
        with self._lock:
            agent = self.get_agent(agent_id)
            if agent:
                agent.status = status
                agent.quarantine_reason = reason if status == AgentStatus.QUARANTINED else ""
                if status == AgentStatus.ACTIVE or status == AgentStatus.IDLE:
                    agent.consecutive_steps = 0


lifecycle_manager = LifecycleManager()
