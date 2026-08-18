"""Tests for backend selection and the live Gemini path.

The live path cannot be exercised against the real API in CI, so the SDK is stubbed. What is
worth guarding is not the SDK call itself but the promises around it: that a key selects the
live backend, that a live answer is stamped live, and that a failed call degrades into a
labelled demo answer carrying the reason rather than passing silently as a model reply.
"""

import sys
import types

import pytest

from sentinel_fleet.chat import backends
from sentinel_fleet.chat.backends import (
    DeterministicDemoBackend,
    GeminiBackend,
    create_backend,
)
from sentinel_fleet.chat.models import ChatMode
from sentinel_fleet.core.config import settings


class _StubResponse:
    def __init__(self, text):
        self.text = text


def _install_stub_sdk(monkeypatch, *, response_text="", raises=None):
    """Stand in for google.genai, recording the arguments the backend passes."""
    captured = {}

    class _Models:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            if raises:
                raise raises
            return _StubResponse(response_text)

    class _Client:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.models = _Models()

    genai = types.ModuleType("google.genai")
    genai.Client = _Client

    genai_types = types.ModuleType("google.genai.types")

    class _Config:
        def __init__(self, system_instruction=None):
            self.system_instruction = system_instruction

    genai_types.GenerateContentConfig = _Config
    genai.types = genai_types

    google = types.ModuleType("google")
    google.genai = genai

    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)
    return captured


def test_backend_selection_follows_the_api_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "", raising=False)
    assert isinstance(create_backend(), DeterministicDemoBackend)

    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    assert isinstance(create_backend(), GeminiBackend)


@pytest.mark.asyncio
async def test_a_live_answer_is_stamped_live_and_timed(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    captured = _install_stub_sdk(monkeypatch, response_text="Ten years under section 147 AO.")

    reply = await GeminiBackend().complete(
        system_prompt="You are the fleet console.",
        user_message="How long do we keep invoices?",
        model="gemini-3.5-pro"
    )

    assert reply.mode is ChatMode.GEMINI_LIVE
    assert reply.content == "Ten years under section 147 AO."
    assert reply.latency_simulated is False, "a real call must not be flagged as simulated"
    assert reply.error == ""
    # The system prompt travels as a system instruction, not smuggled into the user turn.
    assert captured["model"] == "gemini-3.5-pro"
    assert captured["config"].system_instruction == "You are the fleet console."
    assert captured["contents"] == ["How long do we keep invoices?"]
    assert captured["api_key"] == "test-key"


@pytest.mark.asyncio
async def test_a_failed_call_degrades_to_a_labelled_demo_answer(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    _install_stub_sdk(monkeypatch, raises=RuntimeError("quota exhausted"))

    reply = await GeminiBackend().complete(
        system_prompt="system",
        user_message="anything",
        model="gemini-3.5-flash"
    )

    assert reply.mode is ChatMode.DETERMINISTIC_DEMO, "a failed call must not read as a live one"
    assert "quota exhausted" in reply.error
    # The reason has to reach the operator, not just the log.
    assert "quota exhausted" in reply.content
    assert "not model output" in reply.content


@pytest.mark.asyncio
async def test_an_empty_model_response_counts_as_a_failure(monkeypatch):
    """A blank answer stamped `live` would be the most misleading outcome available."""
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    _install_stub_sdk(monkeypatch, response_text="   ")

    reply = await GeminiBackend().complete(system_prompt="s", user_message="u", model="gemini-3.5-flash")

    assert reply.mode is ChatMode.DETERMINISTIC_DEMO
    assert "empty response" in reply.error


@pytest.mark.asyncio
async def test_the_demo_backend_never_invents_subject_matter():
    reply = await DeterministicDemoBackend().complete(
        system_prompt="s" * 120,
        user_message="What is the VAT rate on consulting in Germany?",
        model="gemini-3.5-flash",
        config_digest="skills loaded        2 (skill:tax-compliance-v1 v1.4.0)"
    )

    assert "no model was called" in reply.content
    assert "skill:tax-compliance-v1" in reply.content, "the digest must show what was assembled"
    assert "120 characters" in reply.content
    # It reports the request rather than answering it.
    assert "19" not in reply.content.replace("120 characters", "")


def test_supported_models_are_the_only_offer():
    assert backends.available_models() == ["gemini-3.5-flash", "gemini-3.5-pro"]
    assert backends.available_models() is not backends.SUPPORTED_MODELS, "callers must not mutate the roster"
