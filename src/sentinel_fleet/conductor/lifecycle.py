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
                description="Zentraler Koordinator für Task-Dekomposition und Schwarm-Delegation.",
                allowed_tools={"query_memory_bank", "create_task", "assign_task", "dispatch_swarm"}
            ),
            AgentIdentity(
                agent_id="agent:task-writer",
                name="TaskWriter",
                role=AgentRole.ORCHESTRATOR,
                description="Spezifiziert und strukturiert unklare Aufträge in atomare, idempotente Tasks.",
                allowed_tools={"query_memory_bank", "create_task"}
            ),
            AgentIdentity(
                agent_id="agent:task-maintainer",
                name="TaskMaintainer",
                role=AgentRole.ORCHESTRATOR,
                description="Überwacht den Lebenszyklus, beseitigt Blockaden und bereinigt verwaiste Tasks.",
                allowed_tools={"query_memory_bank", "update_task_state", "audit_task_health"}
            ),
            AgentIdentity(
                agent_id="agent:task-solver",
                name="TaskSolver",
                role=AgentRole.ORCHESTRATOR,
                description="Führt komplexe Berechnungen, RAG-Recherchen und Code-Synthesen autonom aus.",
                allowed_tools={"query_memory_bank", "execute_calculation", "solve_task"}
            ),
            AgentIdentity(
                agent_id="agent:system-auditor",
                name="SystemAuditor",
                role=AgentRole.SECURITY_SENTRY,
                description="Prüft Richtlinien, validiert Audit-Receipts und überwacht OpenTelemetry Spans.",
                allowed_tools={"query_memory_bank", "verify_receipts", "audit_telemetry"}
            ),
            AgentIdentity(
                agent_id="agent:invoice-extractor",
                name="Vision Extractor",
                role=AgentRole.FINANCE_TASKMASTER,
                description="Multimodaler Gemini 3.5 Flash Vision Agent für Beleg- und Tabellenextraktion.",
                allowed_tools={"extract_invoice_multimodal", "query_memory_bank"}
            ),
            AgentIdentity(
                agent_id="agent:compliance-auditor",
                name="Tax Compliance Sentinel",
                role=AgentRole.COMPLIANCE_AUDITOR,
                description="Auditiert Belege gegen § 14 UStG Pflichtfelder und GoBD-Richtlinien.",
                allowed_tools={"validate_tax_compliance", "query_memory_bank", "flag_compliance_error"}
            ),
            AgentIdentity(
                agent_id="agent:ledger-reconciler",
                name="Ledger Reconciler",
                role=AgentRole.LEDGER_RECONCILER,
                description="Verbucht validierte Rechnungen in Firestore und generiert Buchungssätze.",
                allowed_tools={"store_memory_bank", "create_reconciliation_draft", "execute_bank_transfer"}
            ),
            AgentIdentity(
                agent_id="agent:vendor-dispute",
                name="Dispute Communicator",
                role=AgentRole.VENDOR_COMMUNICATOR,
                description="Generiert autonome, rechtssichere Korrektur-Mails an Lieferanten bei Fehlern.",
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
            agent.quarantine_reason = reason if status == AgentStatus.QUARANTINED else ""
            if status == AgentStatus.ACTIVE or status == AgentStatus.IDLE:
                agent.consecutive_steps = 0


lifecycle_manager = LifecycleManager()
