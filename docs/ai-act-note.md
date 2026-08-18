# AI Act Note (informational)

**What this is.** SentinelFleet is a software *component/platform demo* that orchestrates
general-purpose AI models (Google Gemini) behind a governance gateway. It is not itself a
general-purpose AI model, and it is published as an open-source demo without a deployed
service operated by the author.

**Intended purpose (limited).** Demonstration of governed agent orchestration: tool-call
gating, prompt-injection screening, PII redaction, human-in-the-loop approvals, and
observability — on synthetic demo data.

**Not intended for** high-risk contexts within the meaning of Annex III of the EU AI Act
(e.g. employment decisions, credit scoring, law enforcement, critical infrastructure), nor
for unreviewed production accounting or tax filing.

**Transparency.** Model responses are labelled with the mode they ran in
("gemini-3.5" vs. "deterministic-demo"); simulated output is never presented as live model
output. Operators deploying this software for third parties assume the corresponding
provider/deployer duties and should reassess classification for their concrete use.
