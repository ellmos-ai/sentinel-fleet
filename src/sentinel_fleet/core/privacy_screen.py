"""Rule-based privacy screen for content that is about to leave for a third party.

Adapted from the `doc-services` module (`doc_services/privacy.py`, MIT, same author). Two
properties of that module are the reason it was adapted rather than reinvented:

1. It screens **content, not file names**. A name filter passes a credential file that happens
   to be called `webhosting.md`; a content filter does not.
2. It **masks its own findings**. A verdict that quotes the IBAN it found leaks the very value
   it was meant to protect, into the span log of all places.

Deliberately *not* adopted: the upstream fail-closed gate (`darf_weitergegeben_werden`, which
refuses to hand RED content on). Blocking a model call on a regex verdict would be a new policy,
and this fleet keeps policy in the permission registry and the approval gate. The screen states
what it found; the operator sees the verdict on the same gate-ledger row as the call it ran under.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

# Regex work is linear in the input, and an uploaded document can be large. The cap bounds the
# screen's cost; a document whose first 200k characters are clean but whose tail is not would be
# reported as partially screened rather than as clean.
MAX_SCREENED_CHARS = 200_000

# At most this many masked examples per pattern - enough to recognise the shape of a finding,
# not enough to reconstruct the values.
MAX_SAMPLES = 3


class ScreenLevel(str, Enum):
    """Verdict of one screening pass.

    UNSCREENED is not a fourth severity but the honest answer to "there was nothing to read":
    an image without a text layer produces no findings, and reporting that as GREEN would claim
    a clean result the screen never actually established.
    """

    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    UNSCREENED = "unscreened"


# Definitely sensitive: a hit means this content must not travel unnoticed.
RED_PATTERNS: Dict[str, str] = {
    "iban": r"\b[A-Z]{2}\d{2}\s?[\dA-Z]{4}(?:\s?[\dA-Z]{4}){2,7}\b",
    "payment card number": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    "german tax number": r"\b\d{2,3}/\d{3}/\d{5}\b",
    "german tax id": r"\b\d{2}\s\d{3}\s\d{3}\s\d{3}\b",
    "social insurance number": r"\b\d{2}\s?\d{6}\s?[A-Z]\s?\d{3}\b",
    "private key block": r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----",
    "api token": r"\b(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})\b",
    "credential assignment": r"(?i)\b(?:password|passwort|api[_-]?key|secret|token)\s*[:=]\s*\S{6,}",
}

# Possibly sensitive: a hit means look before handing it on. On an invoice most of these are
# expected - a vendor address and a billing mailbox are what an invoice is made of - which is
# exactly why AMBER states a fact instead of raising an alarm.
AMBER_PATTERNS: Dict[str, str] = {
    "email address": r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
    "phone number": r"(?i)\b(?:tel|fon|telefon|mobil|phone)[.:\s]*[+\d][\d\s/()-]{8,}\b",
    "date of birth": r"(?i)\b(?:geb\.|geboren|date of birth|dob)[:\s]*\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}\b",
    # German street names are compounds ("Musterstrasse 12"), so the generic word has to match as
    # a SUFFIX - a word boundary in front of it would never fire.
    "postal address": r"(?i)\b[a-zäöüß-]*(?:stra(?:ß|ss)e|str\.|weg|platz|gasse|allee|ring)\s+\d{1,4}\s?[a-z]?\b",
}

_RED_COMPILED = {name: re.compile(pattern) for name, pattern in RED_PATTERNS.items()}
_AMBER_COMPILED = {name: re.compile(pattern) for name, pattern in AMBER_PATTERNS.items()}


def _mask(value: str) -> str:
    """Never pass a hit on in clear text - the report would leak what it reports about."""
    stripped = value.strip()
    if len(stripped) > 8:
        return f"{stripped[:2]}...{stripped[-2:]}"
    return "..."


class PrivacyFinding(BaseModel):
    pattern: str
    level: ScreenLevel
    count: int
    samples: List[str] = Field(default_factory=list)


class PrivacyVerdict(BaseModel):
    level: ScreenLevel
    findings: List[PrivacyFinding] = Field(default_factory=list)
    # Why the screen could not read anything (UNSCREENED), or how much of the input it read.
    reason: str = ""
    screened_chars: int = 0
    truncated: bool = False

    def summary(self) -> str:
        """One line for the gate ledger and the extraction notes."""
        if self.level is ScreenLevel.UNSCREENED:
            return f"privacy screen: unscreened, {self.reason}"
        if not self.findings:
            return f"privacy screen: green, no sensitive pattern in {self.screened_chars} characters"
        detail = ", ".join(f"{f.pattern} x{f.count}" for f in self.findings)
        suffix = " (input truncated)" if self.truncated else ""
        return f"privacy screen: {self.level.value}, {len(self.findings)} pattern types ({detail}){suffix}"

    def as_span_payload(self) -> Dict[str, object]:
        """Span attributes stay primitive, so the verdict survives the OpenTelemetry export."""
        return {
            "verdict": self.level.value,
            "patterns": ", ".join(f.pattern for f in self.findings) or "none",
            "findings": len(self.findings),
            "screened_chars": self.screened_chars,
            "reason": self.reason,
        }


def screen_text(text: Optional[str], unscreened_reason: str = "no readable text") -> PrivacyVerdict:
    """Classify one piece of outbound content.

    Empty input yields UNSCREENED with the caller's reason, never GREEN: "found nothing" and
    "could not look" are different answers and the difference is the whole point of the screen.
    """
    if not text or not text.strip():
        return PrivacyVerdict(level=ScreenLevel.UNSCREENED, reason=unscreened_reason)

    truncated = len(text) > MAX_SCREENED_CHARS
    window = text[:MAX_SCREENED_CHARS]

    findings: List[PrivacyFinding] = []
    for level, compiled in ((ScreenLevel.RED, _RED_COMPILED), (ScreenLevel.AMBER, _AMBER_COMPILED)):
        for name, regex in compiled.items():
            hits = regex.findall(window)
            if not hits:
                continue
            flat = [hit if isinstance(hit, str) else " ".join(hit) for hit in hits]
            findings.append(PrivacyFinding(
                pattern=name,
                level=level,
                count=len(flat),
                samples=[_mask(hit) for hit in flat[:MAX_SAMPLES]],
            ))

    if any(f.level is ScreenLevel.RED for f in findings):
        level = ScreenLevel.RED
    elif findings:
        level = ScreenLevel.AMBER
    else:
        level = ScreenLevel.GREEN

    return PrivacyVerdict(
        level=level,
        findings=findings,
        screened_chars=len(window),
        truncated=truncated,
        reason="input truncated to the screening cap" if truncated else "",
    )
