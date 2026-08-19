"""Text preparation for the bundled PDF core fonts.

fpdf2's built-in fonts are Latin-1 and cannot break inside a word. Both constraints bite any
document this fleet renders - the chat transcript export and the vendor correction letter - so
the knowledge of them lives in one place rather than in each renderer.
"""

# Longest run of characters a renderer may ask the PDF engine to fit on one line. fpdf2 cannot
# break inside a word, and a document can contain an unbroken identifier, IBAN or URL wider than
# the text column; without soft-wrapping, fpdf2 refuses to draw the whole cell.
PDF_MAX_TOKEN = 88

# Characters that have no Latin-1 code point but a faithful ASCII rendering. Without this the
# encoder would replace them with "?" - and a correction letter that demands "1.761,20 ?" instead
# of euro reads like a rendering bug in a document that goes to a vendor.
LATIN1_SUBSTITUTIONS = {
    "€": "EUR",
    "—": "-",
    "–": "-",
    "„": '"',
    "“": '"',
    "”": '"',
    "‚": "'",
    "‘": "'",
    "’": "'",
    "…": "...",
    " ": " ",
}


def to_latin1(text: str) -> str:
    """Drop what the core fonts cannot draw, after substituting what has a faithful equivalent.

    Substituting beats raising: whoever asked for a PDF wants the document, and the characters
    that survive this pass are typographic rather than semantic.
    """
    for source, replacement in LATIN1_SUBSTITUTIONS.items():
        text = text.replace(source, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def pdf_safe(text: str) -> str:
    """Latin-1 plus soft-wrapping, so no single token is wider than the text column."""
    lines = []
    for line in to_latin1(text).splitlines() or [""]:
        pieces = []
        for token in line.split(" "):
            while len(token) > PDF_MAX_TOKEN:
                pieces.append(token[:PDF_MAX_TOKEN])
                token = token[PDF_MAX_TOKEN:]
            pieces.append(token)
        lines.append(" ".join(pieces))
    return "\n".join(lines)
