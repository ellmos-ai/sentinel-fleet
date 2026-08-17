"""Model Armor & Inline Guardrails (Anti-Prompt-Injection & PII Masking)."""

import re
from typing import Any, Dict, List, Tuple
from pydantic import BaseModel


class ArmorInspectionResult(BaseModel):
    is_safe: bool
    blocked_patterns: List[str] = []
    sanitized_data: Any = None
    redacted_fields: List[str] = []


class ModelArmor:
    # Injection and Jailbreak patterns
    INJECTION_PATTERNS = [
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
        re.compile(r"system\s*prompt\s*override", re.IGNORECASE),
        re.compile(r"reveal\s+(your\s+)?(system\s+prompt|credentials|api[_\s-]?key)", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+in\s+DAN\s+mode", re.IGNORECASE),
        re.compile(r"<script>.*?</script>", re.IGNORECASE),
    ]

    # Sensitive PII patterns
    IBAN_PATTERN = re.compile(r"\b[A-Z]{2}[0-9]{2}(?:[ ]?[0-9]{4}){4}(?:[ ]?[0-9]{1,2})?\b")
    API_KEY_PATTERN = re.compile(r"(AIza[0-9A-Za-z-_]{30,}|sk-[a-zA-Z0-9]{20,})")
    CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")

    @classmethod
    def inspect_prompt(cls, prompt_text: str) -> ArmorInspectionResult:
        """Scan input prompts for adversarial injections and jailbreaks."""
        detected = []
        for pattern in cls.INJECTION_PATTERNS:
            if pattern.search(prompt_text):
                detected.append(pattern.pattern)

        if detected:
            return ArmorInspectionResult(
                is_safe=False,
                blocked_patterns=detected,
                sanitized_data=None
            )

        return ArmorInspectionResult(
            is_safe=True,
            sanitized_data=prompt_text
        )

    @classmethod
    def sanitize_pii(cls, text: str) -> Tuple[str, List[str]]:
        """Sanitize sensitive data and return sanitized text with list of redacted items."""
        redacted = []

        # Redact API Keys
        if cls.API_KEY_PATTERN.search(text):
            text = cls.API_KEY_PATTERN.sub("[REDACTED_API_KEY]", text)
            redacted.append("API_KEY")

        # Redact Credit Cards
        if cls.CREDIT_CARD_PATTERN.search(text):
            text = cls.CREDIT_CARD_PATTERN.sub("[REDACTED_CREDIT_CARD]", text)
            redacted.append("CREDIT_CARD")

        return text, redacted

    @classmethod
    def sanitize_arguments(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Deep sanitization of dictionary arguments."""
        clean = {}
        for k, v in args.items():
            if isinstance(v, str):
                clean_v, _ = cls.sanitize_pii(v)
                clean[k] = clean_v
            elif isinstance(v, dict):
                clean[k] = cls.sanitize_arguments(v)
            else:
                clean[k] = v
        return clean
