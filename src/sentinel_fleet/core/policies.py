"""Policy Engine for business, compliance, and runtime constraints."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PolicyDecisionType(str, Enum):
    PASS = "pass"
    BLOCK = "block"
    FLAG = "flag"


# The mandatory fields and the thresholds below are named rather than inlined so the governance
# board can list what this engine actually checks, and with which limits, by importing them -
# a board that restated them in its own words would drift the moment one of them changed.
UST_REQUIRED_FIELDS = [
    ("vendor_name", "Vendor name is missing"),
    ("vendor_vat_id", "Issuer VAT ID is missing (§ 14 Abs. 4 Nr. 2 UStG)"),
    ("invoice_number", "Sequential invoice number is missing (§ 14 Abs. 4 Nr. 4 UStG)"),
    ("invoice_date", "Issue date is missing (§ 14 Abs. 4 Nr. 3 UStG)"),
    ("delivery_date", "Delivery or service date is missing (§ 14 Abs. 4 Nr. 6 UStG)"),
    ("net_amount", "Net amount is missing"),
    ("tax_rate", "Tax rate is missing"),
    ("gross_amount", "Gross amount is missing")
]

# Rounding slack allowed between net + tax and the stated gross, in euro. Two cents: enough for
# per-line-item rounding, small enough that a real arithmetic error still trips the check.
MATH_TOLERANCE_EUR = 0.02

# Consecutive gateway steps an agent may take without the run state advancing.
DEFAULT_MAX_CONSECUTIVE_STEPS = 5


class PolicyEvaluationResult(BaseModel):
    decision: PolicyDecisionType
    policy_name: str
    violations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PolicyEngine:
    @staticmethod
    def evaluate_tax_compliance(invoice_data: Dict[str, Any]) -> PolicyEvaluationResult:
        """Enforces § 14 UStG mandatory invoice fields."""
        violations = []

        for field, error_msg in UST_REQUIRED_FIELDS:
            val = invoice_data.get(field)
            if val is None or val == "" or val == 0:
                # For tax_rate 0 might be valid (e.g. 0%), check if key exists
                if field == "tax_rate" and "tax_rate" in invoice_data:
                    continue
                violations.append(error_msg)

        # Mathematical consistency check (Net + Tax = Gross)
        net = float(invoice_data.get("net_amount") or 0.0)
        tax_rate = float(invoice_data.get("tax_rate") or 0.0)
        gross = float(invoice_data.get("gross_amount") or 0.0)
        
        if net > 0 and gross > 0:
            expected_tax = round(net * (tax_rate / 100.0), 2)
            expected_gross = round(net + expected_tax, 2)
            diff = abs(expected_gross - gross)
            if diff > MATH_TOLERANCE_EUR:
                violations.append(f"Invoice total is arithmetically inconsistent: net {net} + tax {expected_tax} != gross {gross}")

        if violations:
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.BLOCK,
                policy_name="§ 14 UStG Tax Compliance & Math Integrity",
                violations=violations
            )

        return PolicyEvaluationResult(
            decision=PolicyDecisionType.PASS,
            policy_name="§ 14 UStG Tax Compliance",
            violations=[]
        )

    @staticmethod
    def evaluate_step_budget(
        consecutive_steps: int, max_allowed: int = DEFAULT_MAX_CONSECUTIVE_STEPS
    ) -> PolicyEvaluationResult:
        """Prevents infinite agent loops and hallucinations."""
        if consecutive_steps >= max_allowed:
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.BLOCK,
                policy_name="Loop Prevention & Step Budget",
                violations=[f"Agent reached {consecutive_steps} consecutive steps without state advance (limit: {max_allowed})"]
            )
        return PolicyEvaluationResult(
            decision=PolicyDecisionType.PASS,
            policy_name="Step Budget OK"
        )
