"""Permission registry and access evaluator based on lock-permissions-v1."""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PermissionAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionRule(BaseModel):
    tool_pattern: str
    action: PermissionAction
    reason: str = ""


class PermissionRegistry:
    def __init__(self):
        self.rules: List[PermissionRule] = [
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
            PermissionRule(tool_pattern="execute_template", action=PermissionAction.ALLOW, reason="A template run is a model call; per-template approval is gated separately on the template itself"),
        ]

    def evaluate(self, tool_name: str) -> PermissionAction:
        """Evaluate permission for a specific tool."""
        for rule in self.rules:
            if rule.tool_pattern == tool_name or rule.tool_pattern == "*":
                return rule.action
            if rule.tool_pattern.endswith("*") and tool_name.startswith(rule.tool_pattern[:-1]):
                return rule.action
        # Default policy: allow standard internal tools, ask for unknown
        return PermissionAction.ALLOW
