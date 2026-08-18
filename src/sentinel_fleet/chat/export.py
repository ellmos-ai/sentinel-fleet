"""Transcript export.

Markdown, text and HTML are rendered here; PDF needs fpdf2 and reports a clear 501 when the
optional dependency is absent rather than failing at import time. Every exported turn carries
the mode it ran in, so a transcript produced in demo mode cannot be mistaken for a model
conversation once it has left the console.
"""

import html
import time
from typing import Optional, Tuple

from sentinel_fleet.chat.models import ChatMessage, ChatMode, ChatSession, RaceRecord

EXPORT_FORMATS = ("md", "txt", "html", "pdf")

MODE_LABELS = {
    ChatMode.GEMINI_LIVE: "live model call",
    ChatMode.DETERMINISTIC_DEMO: "demo mode, no model call",
    ChatMode.BLOCKED: "blocked by Model Armor, no model call",
}


class PdfExportUnavailable(RuntimeError):
    """fpdf2 is not installed in this deployment."""


def _stamp(message: ChatMessage) -> str:
    if message.role.value == "user":
        return "operator"
    parts = [message.model or "unknown model", MODE_LABELS.get(message.mode, message.mode.value)]
    if message.latency_s:
        suffix = "simulated" if message.latency_simulated else "measured"
        parts.append(f"{message.latency_s:.3f}s {suffix}")
    return " / ".join(parts)


def _timestamp(value: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def _race_lines(race: RaceRecord) -> list:
    lines = [f"Race {race.race_id} - {len(race.lanes)} lanes", f"Prompt: {race.prompt}", ""]
    for lane in race.lanes:
        suffix = "simulated" if lane.latency_simulated else "measured"
        lines.append(
            f"[{lane.model}] {MODE_LABELS.get(lane.mode, lane.mode.value)}, "
            f"{lane.latency_s:.3f}s {suffix}"
        )
        if lane.error:
            lines.append(f"error: {lane.error}")
        lines.extend([lane.content, ""])
    if race.verdict:
        header = (
            f"Rubric, judged by {race.verdict.judge_model}"
            if race.verdict.evaluated else "Rubric: not scored"
        )
        lines.extend([header, ", ".join(race.verdict.dimensions), race.verdict.summary, ""])
    return lines


def render_markdown(session: ChatSession) -> str:
    out = [
        f"# {session.title}",
        "",
        f"- Session: `{session.session_id}`",
        f"- Started: {_timestamp(session.created_at)}",
        f"- Turns: {len(session.messages)}",
        f"- Races: {len(session.races)}",
        "",
        "Every assistant turn below records how it was produced. Turns marked as demo mode "
        "were not answered by a model.",
        "",
        "---",
        "",
    ]
    for message in session.messages:
        who = "Operator" if message.role.value == "user" else "Assistant"
        out.append(f"## {who}")
        out.append(f"*{_stamp(message)} - {_timestamp(message.timestamp)}*")
        out.append("")
        out.append(message.content)
        out.append("")
    for race in session.races:
        out.append("## Race")
        out.append("")
        out.append("```")
        out.extend(_race_lines(race))
        out.append("```")
        out.append("")
    return "\n".join(out)


def render_text(session: ChatSession) -> str:
    rule = "=" * 72
    out = [
        session.title,
        rule,
        f"Session {session.session_id}   started {_timestamp(session.created_at)}",
        f"{len(session.messages)} turns, {len(session.races)} races",
        "Turns marked as demo mode were not answered by a model.",
        rule,
        "",
    ]
    for message in session.messages:
        who = "OPERATOR" if message.role.value == "user" else "ASSISTANT"
        out.append(f"{who}  [{_stamp(message)}]  {_timestamp(message.timestamp)}")
        out.append("-" * 72)
        out.append(message.content)
        out.append("")
    for race in session.races:
        out.append(rule)
        out.extend(_race_lines(race))
    return "\n".join(out)


def render_html(session: ChatSession) -> str:
    """A self-contained page that keeps the console's typography and verdict stamps."""
    def stamp_class(mode: ChatMode) -> str:
        return {
            ChatMode.GEMINI_LIVE: "ok",
            ChatMode.DETERMINISTIC_DEMO: "warn",
            ChatMode.BLOCKED: "danger",
        }.get(mode, "warn")

    blocks = []
    for message in session.messages:
        who = "Operator" if message.role.value == "user" else "Assistant"
        cls = "user" if message.role.value == "user" else "assistant"
        blocks.append(
            f'<article class="turn {cls}">'
            f'<header><span class="who">{html.escape(who)}</span>'
            f'<span class="stamp {stamp_class(message.mode)}">{html.escape(_stamp(message))}</span>'
            f'<span class="time">{_timestamp(message.timestamp)}</span></header>'
            f'<pre>{html.escape(message.content)}</pre></article>'
        )

    for race in session.races:
        lanes = "".join(
            f'<div class="lane"><header><span class="who">{html.escape(lane.model)}</span>'
            f'<span class="stamp {stamp_class(lane.mode)}">'
            f'{html.escape(MODE_LABELS.get(lane.mode, lane.mode.value))}</span></header>'
            f'<p class="latency">{lane.latency_s:.3f}s '
            f'{"simulated" if lane.latency_simulated else "measured"}</p>'
            f'<pre>{html.escape(lane.content)}</pre></div>'
            for lane in race.lanes
        )
        verdict = ""
        if race.verdict:
            title = (
                f"Rubric, judged by {race.verdict.judge_model}"
                if race.verdict.evaluated else "Rubric: not scored"
            )
            verdict = (
                f'<div class="verdict"><h3>{html.escape(title)}</h3>'
                f'<p class="dims">{html.escape(", ".join(race.verdict.dimensions))}</p>'
                f'<pre>{html.escape(race.verdict.summary)}</pre></div>'
            )
        blocks.append(
            f'<section class="race"><h2>Race</h2>'
            f'<p class="prompt">{html.escape(race.prompt)}</p>'
            f'<div class="lanes">{lanes}</div>{verdict}</section>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(session.title)} — SentinelFleet transcript</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600&family=IBM+Plex+Mono:wght@400;600&family=Public+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink: #0e1419; --ink-2: #4a5661; --ink-3: #78838e;
    --rule: #cdd3da; --surface: #fff; --sunk: #f4f6f8; --ground: #e4e7eb;
    --accent: #2b3a8f; --ok: #0f6b45; --warn: #8a5300; --danger: #a32218;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--ground); color: var(--ink); font-family: "Public Sans", -apple-system, "Segoe UI", sans-serif; font-size: 14px; line-height: 1.55; padding: 32px 16px; }}
  main {{ max-width: 860px; margin: 0 auto; background: var(--surface); border: 1px solid var(--rule); border-radius: 5px; padding: 32px; }}
  h1 {{ font-family: "Archivo", Arial, sans-serif; font-size: 24px; letter-spacing: -0.02em; }}
  h2 {{ font-family: "Archivo", Arial, sans-serif; font-size: 17px; margin-bottom: 8px; }}
  h3 {{ font-family: "Archivo", Arial, sans-serif; font-size: 14px; margin-bottom: 4px; }}
  .meta {{ font-family: "IBM Plex Mono", Consolas, monospace; font-size: 11px; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.1em; margin: 6px 0 4px; }}
  .notice {{ font-size: 12.5px; color: var(--ink-2); border-left: 2px solid var(--accent); padding-left: 12px; margin: 20px 0 28px; }}
  .turn {{ border: 1px solid var(--rule); border-left: 2px solid var(--rule); border-radius: 3px; padding: 12px; margin-bottom: 12px; background: var(--sunk); }}
  .turn.user {{ background: var(--surface); border-left-color: var(--accent); }}
  .turn header, .lane header {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; }}
  .who {{ font-family: "IBM Plex Mono", Consolas, monospace; font-size: 10.5px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); }}
  .time {{ font-family: "IBM Plex Mono", Consolas, monospace; font-size: 10.5px; color: var(--ink-3); }}
  .stamp {{ font-family: "IBM Plex Mono", Consolas, monospace; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; border: 1px solid var(--rule); border-left-width: 2px; border-radius: 3px; padding: 1px 6px; }}
  .stamp.ok {{ color: var(--ok); border-left-color: var(--ok); }}
  .stamp.warn {{ color: var(--warn); border-left-color: var(--warn); }}
  .stamp.danger {{ color: var(--danger); border-left-color: var(--danger); }}
  pre {{ font-family: "IBM Plex Mono", Consolas, monospace; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }}
  .race {{ border: 1px solid var(--rule); border-radius: 3px; padding: 12px; margin-bottom: 12px; }}
  .prompt {{ font-size: 12.5px; color: var(--ink-2); margin-bottom: 12px; }}
  .lanes {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
  .lane {{ border: 1px solid var(--rule); border-radius: 3px; padding: 10px; background: var(--sunk); }}
  .latency {{ font-family: "IBM Plex Mono", Consolas, monospace; font-size: 18px; margin-bottom: 8px; }}
  .verdict {{ border-top: 1px solid var(--rule); margin-top: 12px; padding-top: 12px; }}
  .dims {{ font-family: "IBM Plex Mono", Consolas, monospace; font-size: 11px; color: var(--ink-3); margin-bottom: 6px; }}
  footer {{ max-width: 860px; margin: 16px auto 0; font-size: 11.5px; color: var(--ink-3); }}
</style>
</head>
<body>
<main>
  <h1>{html.escape(session.title)}</h1>
  <p class="meta">SentinelFleet transcript / {html.escape(session.session_id)} / {_timestamp(session.created_at)}</p>
  <p class="notice">Every turn records how it was produced. Turns stamped as demo mode were answered without calling a model.</p>
  {''.join(blocks)}
</main>
<footer>Exported from the SentinelFleet operator console.</footer>
</body>
</html>
"""


# Longest run of characters the PDF renderer is asked to fit on one line. fpdf2 cannot break
# inside a word, and a transcript can contain an unbroken identifier or URL wider than the page.
PDF_MAX_TOKEN = 88


def _latin1(text: str) -> str:
    """The bundled PDF core fonts are Latin-1 only; drop what they cannot draw.

    Substituting is better than raising: an operator asking for a PDF wants the transcript,
    and the unsupported characters are typographic rather than semantic.
    """
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _pdf_safe(text: str) -> str:
    """Latin-1 plus soft-wrapping, so no single token is wider than the text column."""
    lines = []
    for line in _latin1(text).splitlines() or [""]:
        pieces = []
        for token in line.split(" "):
            while len(token) > PDF_MAX_TOKEN:
                pieces.append(token[:PDF_MAX_TOKEN])
                token = token[PDF_MAX_TOKEN:]
            pieces.append(token)
        lines.append(" ".join(pieces))
    return "\n".join(lines)


def render_pdf(session: ChatSession) -> bytes:
    try:
        from fpdf import FPDF
    except ImportError as exc:  # pragma: no cover - covered by monkeypatching the import
        raise PdfExportUnavailable(
            "PDF export needs the optional fpdf2 dependency. Install it with "
            "`pip install fpdf2`, or export the transcript as md, txt or html."
        ) from exc

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    def block(text: str, height: float = 4.6):
        # multi_cell leaves the cursor where the last line ended; without resetting to the left
        # margin the next call computes a zero-width column and fpdf2 refuses to draw.
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(w=0, h=height, text=_pdf_safe(text), align="L")

    pdf.set_font("Helvetica", "B", 16)
    block(session.title, 8)

    pdf.set_font("Courier", "", 8)
    pdf.set_text_color(120, 131, 142)
    block(f"SentinelFleet transcript / {session.session_id} / {_timestamp(session.created_at)}", 5)

    pdf.set_font("Helvetica", "", 9)
    block(
        "Every turn records how it was produced. Turns stamped as demo mode were answered "
        "without calling a model.",
        5
    )
    pdf.ln(3)

    for message in session.messages:
        who = "OPERATOR" if message.role.value == "user" else "ASSISTANT"
        pdf.set_text_color(43, 58, 143)
        pdf.set_font("Courier", "B", 8)
        block(f"{who}  [{_stamp(message)}]", 5)
        pdf.set_text_color(14, 20, 25)
        pdf.set_font("Courier", "", 9)
        block(message.content)
        pdf.ln(2)

    for race in session.races:
        pdf.set_text_color(43, 58, 143)
        pdf.set_font("Courier", "B", 8)
        block(f"RACE  [{len(race.lanes)} lanes]", 5)
        pdf.set_text_color(14, 20, 25)
        pdf.set_font("Courier", "", 9)
        block("\n".join(_race_lines(race)))
        pdf.ln(2)

    return bytes(pdf.output())


def render(session: ChatSession, fmt: str) -> Tuple[bytes, str, str]:
    """Return (body, media type, filename) for one export format."""
    stem = f"sentinelfleet-{session.session_id}"
    if fmt == "md":
        return render_markdown(session).encode("utf-8"), "text/markdown; charset=utf-8", f"{stem}.md"
    if fmt == "txt":
        return render_text(session).encode("utf-8"), "text/plain; charset=utf-8", f"{stem}.txt"
    if fmt == "html":
        return render_html(session).encode("utf-8"), "text/html; charset=utf-8", f"{stem}.html"
    if fmt == "pdf":
        return render_pdf(session), "application/pdf", f"{stem}.pdf"
    raise ValueError(f"Unsupported export format '{fmt}'. Choose one of: {', '.join(EXPORT_FORMATS)}")
