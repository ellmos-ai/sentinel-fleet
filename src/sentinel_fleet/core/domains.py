"""Domain Hub & Multi-Tenant Domain Configuration Registry."""

import time
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class EnterpriseDomain(BaseModel):
    domain_id: str
    name: str
    code: str
    icon: str
    description: str
    is_active: bool = True
    active_policies: List[str] = Field(default_factory=list)
    bound_agents: List[str] = Field(default_factory=list)
    bound_skills: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)


class DomainRegistry:
    def __init__(self):
        self._domains: Dict[str, EnterpriseDomain] = {}
        self._seed_default_domains()

    def _seed_default_domains(self):
        seeds = [
            EnterpriseDomain(
                domain_id="domain:omniledger",
                name="OmniLedger Finance & Tax Hub",
                code="FIN-TAX",
                icon="⚡",
                description="Autonome Rechnungsverarbeitung, § 14 UStG Compliance-Prüfung, GoBD-Ledger & Dispute Loop.",
                is_active=True,
                active_policies=["policy:ustg-14-compliance", "policy:ledger-consistency-math", "policy:auto-dispute-vendor"],
                bound_agents=["agent:invoice-extractor", "agent:compliance-auditor", "agent:ledger-reconciler", "agent:vendor-dispute"],
                bound_skills=["skill:tax-compliance-v1", "skill:pdf-vision-extractor", "skill:vendor-dispute-generator"]
            ),
            EnterpriseDomain(
                domain_id="domain:cloudops",
                name="Google Cloud Infrastructure & Ops",
                code="CLOUD-OPS",
                icon="☁️",
                description="Serverless Orchestrierung auf Google Cloud Run, Cloud Pub/Sub Messaging & Cloud Trace Tracing.",
                is_active=True,
                active_policies=["policy:zero-trust-model-armor", "policy:rate-limiting-circuit-breaker"],
                bound_agents=["agent:orchestrator", "agent:system-auditor", "agent:task-maintainer"],
                bound_skills=["skill:model-armor-sentry", "skill:task-lifecycle-maintainer"]
            ),
            EnterpriseDomain(
                domain_id="domain:legal-sentry",
                name="Legal, GoBD & DSGVO Governance",
                code="LEGAL-SENTRY",
                icon="⚖️",
                description="Automatisierte Prüfung auf DSGVO-PII-Maskierung, Haftungsausschlüsse und Revisionssicherheit.",
                is_active=True,
                active_policies=["policy:pii-redaction-mandatory", "policy:hitl-approval-on-dispute"],
                bound_agents=["agent:system-auditor", "agent:task-solver"],
                bound_skills=["skill:model-armor-sentry", "skill:tax-compliance-v1"]
            ),
            EnterpriseDomain(
                domain_id="domain:vendor-ops",
                name="Vendor & Partner Communications",
                code="VENDOR-OPS",
                icon="🤝",
                description="Automatische Klärungsprozesse, Lieferantenstammdaten-Synchronisation und SLA-Monitoring.",
                is_active=True,
                active_policies=["policy:vendor-formal-notice-sla"],
                bound_agents=["agent:vendor-dispute", "agent:task-writer"],
                bound_skills=["skill:vendor-dispute-generator", "skill:memory-bank-connector"]
            )
        ]
        for d in seeds:
            self._domains[d.domain_id] = d

    def list_all(self) -> List[EnterpriseDomain]:
        return list(self._domains.values())

    def get_domain(self, domain_id: str) -> Optional[EnterpriseDomain]:
        return self._domains.get(domain_id)


domain_registry = DomainRegistry()
