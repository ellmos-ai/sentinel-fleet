"""Unit tests for the model router and the settings resolution.

Guards competition rule 1: the platform must run on Gemini 3.5 or newer. A silent
fallback to the 2.5 generation would be disqualifying, so the model ids are asserted.
"""

import pytest

from sentinel_fleet.conductor.router import ModelRouter, ModelTier, RoutingStrategy
from sentinel_fleet.core.config import Settings


def test_model_tiers_are_gemini_35_or_newer():
    assert ModelTier.FAST.value.startswith("gemini-3.5")
    assert ModelTier.PRO.value.startswith("gemini-3.5")
    # The local fallback is deliberately not a Gemini model
    assert ModelTier.LOCAL_FALLBACK.value == "gemma-2-9b"


def test_router_selects_fast_tier_by_default():
    router = ModelRouter()
    assert router.select_model() == ModelTier.FAST.value
    assert router.select_model("normal") == ModelTier.FAST.value


def test_router_escalates_on_high_complexity():
    router = ModelRouter()
    assert router.select_model("high") == ModelTier.PRO.value


def test_router_honours_a_custom_strategy():
    router = ModelRouter(RoutingStrategy(preferred_tier=ModelTier.PRO, escalation_tier=ModelTier.PRO))
    assert router.select_model() == ModelTier.PRO.value
    assert router.select_model("high") == ModelTier.PRO.value


def test_default_model_setting_is_gemini_35(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert Settings().gemini_default_model.startswith("gemini-3.5")


@pytest.mark.parametrize(
    "env_name, attribute, raw_value, expected",
    [
        ("GEMINI_MODEL", "gemini_default_model", "gemini-3.5-pro", "gemini-3.5-pro"),
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
