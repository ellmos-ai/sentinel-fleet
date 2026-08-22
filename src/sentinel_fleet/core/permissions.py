"""Permission registry and access evaluator based on lock-permissions-v1."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel


class PermissionAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionRule(BaseModel):
    tool_pattern: str
    action: PermissionAction
    reason: str = ""


# What a tool with no matching rule gets. Named so the governance board can show which cells
# rest on an explicit rule and which only inherit this fall-through - several tools that agents
# really carry (create_task, dispatch_swarm, verify_receipts, ...) have no rule of their own.
DEFAULT_ACTION = PermissionAction.DENY
DEFAULT_REASON = "No explicit rule matches this tool name; the registry fails closed."


class PermissionVerdict(BaseModel):
    """Why a tool got the action it got - the rule that matched, or the default."""
    tool_name: str
    action: PermissionAction
    source: str = "rule"          # "rule" | "default"
    reason: str = ""
    matched_pattern: Optional[str] = None


class PermissionRegistry:
    def __init__(
        self,
        rules: Optional[List[PermissionRule]] = None,
        default_action: PermissionAction = DEFAULT_ACTION,
        default_reason: str = DEFAULT_REASON,
    ):
        """Create a registry over one matching implementation.

        The gateway keeps using the built-in tool rules when ``rules`` is omitted.  User-role
        capabilities reuse the same matcher with an injected rule set and a fail-closed default;
        this avoids a second wildcard implementation that could disagree with the gateway.
        """
        self.default_action = default_action
        self.default_reason = default_reason
        self.rules: List[PermissionRule] = list(rules) if rules is not None else [
            # Hard Denials (Destructive or Credential operations)
            PermissionRule(tool_pattern="bash_rm_rf", action=PermissionAction.DENY, reason="Destructive file removal forbidden"),
            PermissionRule(tool_pattern="write_credentials", action=PermissionAction.DENY, reason="Direct credential writing forbidden"),
            PermissionRule(tool_pattern="export_raw_secrets", action=PermissionAction.DENY, reason="Secret exfiltration forbidden"),
            
            # Hard Gates / Human-in-the-Loop (ask)
            PermissionRule(tool_pattern="send_external_email", action=PermissionAction.ASK, reason="External email dispatch requires human review"),
            PermissionRule(tool_pattern="execute_bank_transfer", action=PermissionAction.ASK, reason="Financial disbursements require human signoff"),
            PermissionRule(tool_pattern="publish_public_record", action=PermissionAction.ASK, reason="Public state changes require human verification"),
            
            # Soft Gates / Autonomous Execution (allow)
            PermissionRule(tool_pattern="extract_invoice_multimodal", action=PermissionAction.ALLOW),
            PermissionRule(tool_pattern="validate_tax_compliance", action=PermissionAction.ALLOW),
            PermissionRule(tool_pattern="query_memory_bank", action=PermissionAction.ALLOW),
            PermissionRule(tool_pattern="store_memory_bank", action=PermissionAction.ALLOW),
            PermissionRule(tool_pattern="create_reconciliation_draft", action=PermissionAction.ALLOW),
            PermissionRule(tool_pattern="draft_vendor_dispute_email", action=PermissionAction.ALLOW),
            PermissionRule(tool_pattern="render_dispute_letter", action=PermissionAction.ALLOW, reason="Rendering the correction letter has no external effect; sending it is what hits the ASK gate"),
            PermissionRule(tool_pattern="chat_completion", action=PermissionAction.ALLOW, reason="Model calls are read-only and carry no external effect"),
            PermissionRule(tool_pattern="read_web_page", action=PermissionAction.ALLOW, reason="An unauthenticated GET changes nothing at the target; the control on it is the SSRF guard, not an approval"),
            PermissionRule(tool_pattern="execute_template", action=PermissionAction.ALLOW, reason="A template run is a model call; per-template approval is gated separately on the template itself"),

            # Explicit internal operations. Unknown tools do not inherit these rights: the
            # registry default is DENY, so adding a tool to an identity requires adding its
            # policy here as a separate, reviewable change.
            PermissionRule(tool_pattern="create_task", action=PermissionAction.ALLOW, reason="Creates an internal queued task record"),
            PermissionRule(tool_pattern="assign_task", action=PermissionAction.ALLOW, reason="Assigns work inside the fleet"),
            PermissionRule(tool_pattern="dispatch_swarm", action=PermissionAction.ALLOW, reason="Dispatches scoped internal agents"),
            PermissionRule(tool_pattern="update_task_state", action=PermissionAction.ALLOW, reason="Updates an internal task lifecycle"),
            PermissionRule(tool_pattern="audit_task_health", action=PermissionAction.ALLOW, reason="Read-only task health inspection"),
            PermissionRule(tool_pattern="execute_calculation", action=PermissionAction.ALLOW, reason="Runs a bounded internal calculation"),
            PermissionRule(tool_pattern="solve_task", action=PermissionAction.ALLOW, reason="Runs a scoped internal task"),
            PermissionRule(tool_pattern="verify_receipts", action=PermissionAction.ALLOW, reason="Read-only audit verification"),
            PermissionRule(tool_pattern="audit_telemetry", action=PermissionAction.ALLOW, reason="Read-only telemetry inspection"),
            PermissionRule(tool_pattern="flag_compliance_error", action=PermissionAction.ALLOW, reason="Records an internal compliance finding"),
        ]

    def evaluate(self, tool_name: str) -> PermissionAction:
        """Evaluate permission for a specific tool."""
        return self.explain(tool_name).action

    def explain(self, tool_name: str) -> PermissionVerdict:
        """The same decision `evaluate()` makes, plus what it rests on.

        One matching implementation for both: a board that re-derived the match would be free to
        disagree with the gateway, which is the one thing a governance view must never do.
        """
        for rule in self.rules:
            matched = (
                rule.tool_pattern in (tool_name, "*")
                or (rule.tool_pattern.endswith("*") and tool_name.startswith(rule.tool_pattern[:-1]))
            )
            if matched:
                return PermissionVerdict(
                    tool_name=tool_name,
                    action=rule.action,
                    source="rule",
                    reason=rule.reason,
                    matched_pattern=rule.tool_pattern
                )
        return PermissionVerdict(
            tool_name=tool_name,
            action=self.default_action,
            source="default",
            reason=self.default_reason,
        )
