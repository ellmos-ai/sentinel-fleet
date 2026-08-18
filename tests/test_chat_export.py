"""Tests for transcript export in markdown, text, HTML and PDF."""

import builtins

import pytest
from httpx import AsyncClient, ASGITransport

from sentinel_fleet.chat import export as chat_export
from sentinel_fleet.chat.models import (
    ChatMessage,
    ChatMode,
    ChatRole,
    ChatSession,
    RaceLane,
    RaceRecord,
    RaceVerdict,
)
from sentinel_fleet.web.server import app


def sample_session() -> ChatSession:
    session = ChatSession(session_id="chat-EXPORT01", title="Retention rules for vendor invoices")
    session.messages = [
        ChatMessage(message_id="m1", role=ChatRole.USER, content="How long must we keep invoices?"),
        ChatMessage(
            message_id="m2",
            role=ChatRole.ASSISTANT,
            content="Ten years under § 147 AO.",
            model="gemini-3.5-flash",
            mode=ChatMode.DETERMINISTIC_DEMO,
            latency_s=0.812,
            latency_simulated=True
        )
    ]
    session.races = [RaceRecord(
        race_id="race-EXPORT01",
        prompt="Summarise the retention rule",
        lanes=[
            RaceLane(model="gemini-3.5-flash", agent_id="agent:race-lane-1",
                     content="Lane one answer", latency_s=0.4, latency_simulated=True),
            RaceLane(model="gemini-3.5-pro", agent_id="agent:race-lane-2",
                     content="Lane two answer", latency_s=1.1, latency_simulated=True)
        ],
        verdict=RaceVerdict(
            judge_model="gemini-3.5-flash",
            dimensions=["quality", "latency"],
            evaluated=False,
            summary="Not judged. The lanes ran in demo mode."
        )
    )]
    return session


def test_markdown_carries_the_mode_of_every_assistant_turn():
    out = chat_export.render_markdown(sample_session())
    assert "# Retention rules for vendor invoices" in out
    assert "demo mode, no model call" in out
    assert "0.812s simulated" in out, "a simulated latency must stay labelled outside the console"
    assert "Lane two answer" in out


def test_text_export_is_plain_and_complete():
    out = chat_export.render_text(sample_session())
    assert "OPERATOR" in out and "ASSISTANT" in out
    assert "Ten years under" in out
    assert "Race race-EXPORT01" in out
    assert "<" not in out, "the text export must not carry markup"


def test_html_export_is_self_contained_and_escapes_content():
    session = sample_session()
    session.messages[0].content = "<script>alert('x')</script>"
    out = chat_export.render_html(session)

    assert out.startswith("<!DOCTYPE html>")
    assert "<style>" in out, "the export must carry its own styling"
    assert "&lt;script&gt;" in out
    assert "<script>alert" not in out, "message content was not escaped"
    assert "Not judged" in out


def test_pdf_export_produces_a_pdf_document():
    body = chat_export.render_pdf(sample_session())
    assert body.startswith(b"%PDF-"), "output is not a PDF"
    assert len(body) > 800


def test_pdf_export_replaces_characters_the_core_fonts_cannot_draw():
    session = sample_session()
    session.messages[1].content = "Latin-1 keeps §, but an em dash — and 你好 must not crash it."
    body = chat_export.render_pdf(session)
    assert body.startswith(b"%PDF-")


def test_unknown_format_is_rejected():
    with pytest.raises(ValueError):
        chat_export.render(sample_session(), "docx")


@pytest.mark.asyncio
async def test_export_endpoint_serves_every_format_as_a_download():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/chat/send", json={"message": "Export smoke test"})
        session_id = created.json()["session_id"]

        expected = {
            "md": "text/markdown",
            "txt": "text/plain",
            "html": "text/html",
            "pdf": "application/pdf"
        }
        for fmt, media in expected.items():
            response = await client.get(f"/api/chat/sessions/{session_id}/export?format={fmt}")
            assert response.status_code == 200, f"{fmt} export failed"
            assert media in response.headers["content-type"]
            assert f'filename="sentinelfleet-{session_id}.{fmt}"' in response.headers["content-disposition"]
            assert response.content


@pytest.mark.asyncio
async def test_export_rejects_an_unknown_format_and_an_unknown_session():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/chat/send", json={"message": "Export guard test"})
        session_id = created.json()["session_id"]

        bad_format = await client.get(f"/api/chat/sessions/{session_id}/export?format=docx")
        assert bad_format.status_code == 400

        missing = await client.get("/api/chat/sessions/chat-NOPE/export?format=md")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_missing_fpdf2_reports_501_instead_of_crashing(monkeypatch):
    """fpdf2 is a declared dependency now, so the absence is simulated rather than assumed."""
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "fpdf":
            raise ImportError("No module named 'fpdf'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/chat/send", json={"message": "PDF fallback test"})
        session_id = created.json()["session_id"]

        response = await client.get(f"/api/chat/sessions/{session_id}/export?format=pdf")
        assert response.status_code == 501
        detail = response.json()["detail"]
        assert "fpdf2" in detail
        assert "md, txt or html" in detail, "the error must name a route the operator can take"
