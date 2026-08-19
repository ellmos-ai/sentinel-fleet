"""Token metering of live model calls.

The provider reports token counts on its response; nothing in this app used to read them, so
"what did this fleet spend" had no answer at all. These tests pin the two properties that make
the answer trustworthy: a real usage block is read defensively and lands on the gate-ledger row
the call ran under, and a response without one produces no numbers rather than invented ones.
"""

import asyncio

from sentinel_fleet.chat.models import ChatMode
from sentinel_fleet.chat.backends import (
    MODEL_USAGE_EVENT,
    BackendReply,
    DeterministicDemoBackend,
    read_usage,
    record_usage,
)
from sentinel_fleet.core.telemetry import telemetry


class _Usage:
    def __init__(self, prompt=None, candidates=None, total=None):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        self.total_token_count = total


class _Response:
    def __init__(self, usage=None):
        self.text = "an answer"
        if usage is not None:
            self.usage_metadata = usage


def test_read_usage_extracts_the_provider_counts():
    usage = read_usage(_Response(_Usage(prompt=120, candidates=40, total=160)))
    assert usage == {"prompt_tokens": 120, "output_tokens": 40, "total_tokens": 160}


def test_read_usage_survives_a_response_without_a_usage_block():
    """Some responses carry no usage_metadata at all - that must not break the model call."""
    assert read_usage(_Response()) == {
        "prompt_tokens": None, "output_tokens": None, "total_tokens": None
    }


def test_read_usage_survives_none_fields_inside_the_usage_block():
    """A present block with empty fields reports empty, not zero: "not reported" and "zero
    tokens" are different facts, and only one of them is true here."""
    usage = read_usage(_Response(_Usage(prompt=None, candidates=None, total=90)))
    assert usage == {"prompt_tokens": None, "output_tokens": None, "total_tokens": 90}


def test_recorded_usage_lands_on_the_active_gate_ledger_row():
    span = telemetry.start_span("tool_call:chat_completion", "agent:chat-operator", {"tool": "chat_completion"})
    token = telemetry.bind_active_span(span)
    try:
        landed = record_usage("gemini-3.5-flash", {"prompt_tokens": 10, "output_tokens": 4, "total_tokens": 14})
    finally:
        telemetry.release_active_span(token)
    telemetry.end_span(span, status="OK")

    assert landed is True
    events = [e for e in span.events if e["name"] == MODEL_USAGE_EVENT]
    assert len(events) == 1
    assert events[0]["payload"] == {
        "model": "gemini-3.5-flash", "prompt_tokens": 10, "output_tokens": 4, "total_tokens": 14
    }


def test_nothing_is_recorded_when_the_provider_reported_no_counts():
    span = telemetry.start_span("tool_call:chat_completion", "agent:chat-operator", {"tool": "chat_completion"})
    token = telemetry.bind_active_span(span)
    try:
        landed = record_usage("gemini-3.5-flash", {
            "prompt_tokens": None, "output_tokens": None, "total_tokens": None
        })
    finally:
        telemetry.release_active_span(token)
    telemetry.end_span(span, status="OK")

    assert landed is False
    assert [e for e in span.events if e["name"] == MODEL_USAGE_EVENT] == []


def test_recording_outside_the_gateway_is_a_no_op_not_a_failure():
    """Backends are also exercised directly by tests; metering must never require a span."""
    assert record_usage("gemini-3.5-flash", {"prompt_tokens": 5, "output_tokens": 5, "total_tokens": 10}) is False


def test_demo_backend_reports_no_token_counts():
    """The demo backend calls no model, so it has nothing to meter - and must not pretend to."""
    reply = asyncio.run(DeterministicDemoBackend().complete("system", "hello", "gemini-3.5-flash"))
    assert (reply.prompt_tokens, reply.output_tokens, reply.total_tokens) == (None, None, None)


def test_backend_reply_defaults_keep_existing_callers_working():
    reply = BackendReply(content="x", model="gemini-3.5-flash", mode=ChatMode.GEMINI_LIVE)
    assert reply.total_tokens is None
