"""Regression guard for competition rule 6: code and UI ship in English.

The project targets a German VAT use case, so a handful of strings are genuinely
German data rather than untranslated UI. Those are whitelisted explicitly below,
each with the reason it must stay German.
"""

import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
TEMPLATE_DIR = SRC_ROOT / "sentinel_fleet" / "web" / "templates"
GERMAN_CHARS = re.compile(r"[äöüÄÖÜß]")
# Umlauts alone miss plenty of German ("Rechnungsstelle", "Beratungsvertrag"), so common
# stems are checked as well. Extend the list when a new one slips through.
GERMAN_STEMS = re.compile(
    r"rechnung|lieferant|buchhaltung|belegwesen|gesetzlich|aufbewahrung|steuernummer|"
    r"zahlungsziel|korrekturschreiben|vertrag|anschrift|freigabe|verwaltung|abrechnung|"
    r"bestellung|sicherheitsdienst|schaltplan|warteschlange",
    re.IGNORECASE
)
SCANNED_SUFFIXES = (".py", ".html", ".js", ".css")

# path (relative to src/) -> line markers that may legitimately contain German characters
ALLOWED_GERMAN = {
    # Verbatim German statute and bookkeeping-principle texts. The compliance domain cites
    # these sources in its audit and in the dispute letter; translating them would misquote
    # the law the whole § 14 UStG check rests on.
    "sentinel_fleet/memory/gardener_rag.py": (
        "UStG_Paragraph_14",
        "GoBD_Compliance_Guideline",
    ),
    # Postal addresses and the mailbox name of the demo vendors. German invoices carry
    # German addresses; anglicising them would make the sample data unrealistic.
    "sentinel_fleet/domains/omniledger/extractor.py": (
        "vendor_address=",
        "vendor_email=\"rechnung@officesupplies.example\"",
    ),
    # Patterns that match German *document content*, not UI text. A screen that only recognised
    # English street syntax would pass a German postal address through unflagged, which is the
    # opposite of what the pre-model privacy screen is for.
    "sentinel_fleet/core/privacy_screen.py": (
        "stra(?:ß|ss)e",
    ),
    # Field labels printed on German invoices. The local reader has to match the words that are
    # actually on the paper; translating them would make it read nothing at all on the very
    # documents this § 14 UStG domain exists for.
    "sentinel_fleet/domains/omniledger/local_text.py": (
        "rechnungs?[-\\s]*",
        "rechnungsdatum",
        "rechnungsbetrag",
        "^(?:invoice|rechnung|bill",
    ),
    # "RechnungsSteller" is the proper name of the upstream module this engine derives from,
    # listed like the other component names (coma, clutch, law-checker).
    "sentinel_fleet/domains/omniledger/reconciliation.py": (
        "based on RechnungsSteller",
    ),
    "sentinel_fleet/web/templates/blueprint.html": (
        "chip-item\">RechnungsSteller<",
    ),
    # The legacy route is deliberately preserved so old links keep working.
    "sentinel_fleet/web/server.py": (
        "schaltplan",
    ),
}


def _iter_source_files():
    for path in sorted(SRC_ROOT.rglob("*")):
        if path.suffix not in SCANNED_SUFFIXES or "__pycache__" in path.parts:
            continue
        # Vendored third-party code (web/static/vendor/, e.g. xterm.js) is not this project's
        # authorship and is exempt on principle, not by a per-line whitelist entry: xterm.js's
        # own DEC national character set tables legitimately contain special Latin letters as
        # terminal emulation data (the VT100 German replacement charset), unrelated to any
        # language policy this project's own code and UI strings are held to.
        if "vendor" in path.parts:
            continue
        yield path


def _german_lines(path):
    rel = path.relative_to(SRC_ROOT).as_posix()
    allowed = ALLOWED_GERMAN.get(rel, ())
    hits = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not (GERMAN_CHARS.search(line) or GERMAN_STEMS.search(line)):
            continue
        if any(marker in line for marker in allowed):
            continue
        hits.append(f"{rel}:{lineno}: {line.strip()[:110]}")
    return hits


def test_sources_contain_no_german_outside_whitelist():
    offenders = []
    for path in _iter_source_files():
        offenders.extend(_german_lines(path))

    assert not offenders, "German text outside the whitelist:\n" + "\n".join(offenders)


def test_whitelist_has_no_stale_entries():
    """A whitelist entry that no longer matches anything would silently widen the exception."""
    unused = []
    for rel, markers in ALLOWED_GERMAN.items():
        path = SRC_ROOT / rel
        assert path.exists(), f"Whitelisted file no longer exists: {rel}"
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            covers_german = any(
                marker in line and (GERMAN_CHARS.search(line) or GERMAN_STEMS.search(line))
                for line in text.splitlines()
            )
            if not covers_german:
                unused.append(f"{rel} -> {marker}")

    assert not unused, "Stale i18n whitelist entries (remove them):\n" + "\n".join(unused)


def test_templates_declare_english_language():
    for name in ("index.html", "blueprint.html"):
        html = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
        assert '<html lang="en"' in html, f"{name} does not declare lang=\"en\""
