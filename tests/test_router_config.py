"""Unit tests for the model router and the settings resolution.

Guards competition rule 1: the platform must run on Gemini 3.5 or newer. A silent
fallback to the 2.5 generation would be disqualifying, so the model ids are asserted.
"""

import re

import pytest

from sentinel_fleet.chat.backends import SUPPORTED_MODELS
from sentinel_fleet.conductor.router import ModelRouter, ModelTier, RoutingStrategy
from sentinel_fleet.core.config import Settings

GEMINI_GENERATION = re.compile(r"^gemini-(\d+\.\d+)-")


def _generation(model_id):
    match = GEMINI_GENERATION.match(model_id)
    assert match, f"{model_id} is not a recognisable Gemini id"
    return float(match.group(1))


def test_model_tiers_are_gemini_35_or_newer():
    assert _generation(ModelTier.FAST.value) >= 3.5
    assert _generation(ModelTier.STANDARD.value) >= 3.5
    assert _generation(ModelTier.STRONG.value) >= 3.5
    # The local fallback is deliberately not a Gemini model
    assert ModelTier.LOCAL_FALLBACK.value == "gemma-2-9b"


def test_every_router_tier_is_a_model_the_console_supports():
    """A tier naming a model the provider does not serve is how "gemini-3.5-pro" survived for
    weeks: nothing tied the router's roster to the one the API actually lists."""
    for tier in (ModelTier.FAST, ModelTier.STANDARD, ModelTier.STRONG):
        assert tier.value in SUPPORTED_MODELS, f"{tier.value} is not a supported model"


def test_router_selects_the_standard_tier_by_default():
    router = ModelRouter()
    assert router.select_model() == ModelTier.STANDARD.value
    assert router.select_model("normal") == ModelTier.STANDARD.value


def test_router_escalates_on_high_complexity():
    router = ModelRouter()
    assert router.select_model("high") == ModelTier.STRONG.value


def test_router_honours_a_custom_strategy():
    router = ModelRouter(RoutingStrategy(preferred_tier=ModelTier.FAST, escalation_tier=ModelTier.FAST))
    assert router.select_model() == ModelTier.FAST.value
    assert router.select_model("high") == ModelTier.FAST.value


def test_default_model_setting_is_gemini_35(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert Settings().gemini_default_model.startswith("gemini-3.5")


@pytest.mark.parametrize(
    "env_name, attribute, raw_value, expected",
    [
        ("GEMINI_MODEL", "gemini_default_model", "gemini-3.7-flash", "gemini-3.7-flash"),
        ("GEMINI_API_KEY", "gemini_api_key", "test-key-123", "test-key-123"),
        ("GOOGLE_CLOUD_PROJECT", "google_cloud_project", "my-project", "my-project"),
        ("ENVIRONMENT", "environment", "production", "production"),
        ("PORT", "port", "9090", 9090),
        ("ENABLE_CLOUD_TRACE", "enable_cloud_trace", "true", True),
        ("MAX_CONSECUTIVE_LOOPS", "circuit_breaker_max_loops", "9", 9),
    ],
)
def test_settings_read_environment_overrides(monkeypatch, env_name, attribute, raw_value, expected):
    monkeypatch.setenv(env_name, raw_value)
    assert getattr(Settings(), attribute) == expected


def test_cloud_trace_flag_defaults_to_false(monkeypatch):
    monkeypatch.delenv("ENABLE_CLOUD_TRACE", raising=False)
    assert Settings().enable_cloud_trace is False
