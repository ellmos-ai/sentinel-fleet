"""Model backends for the chat console.

Adapted from the backend abstraction in ellmos-chat: one abstract base, one concrete class
per provider, and a single factory that picks the provider from configuration. The demo
backend is a first-class provider here rather than an error path, because a deployment
without GEMINI_API_KEY must stay fully operable and must never present invented model output
as a model answer.
"""

import abc
import asyncio
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from sentinel_fleet.chat.models import ChatMode
from sentinel_fleet.core.config import settings
from sentinel_fleet.core.telemetry import telemetry

logger = logging.getLogger(__name__)

# Span event a live model call leaves behind so the governance board can meter token spend.
# Only a real provider response ever emits it: the demo backend has no token counts, and a
# plausible-looking number invented next to a cost figure is worse than an empty column.
MODEL_USAGE_EVENT = "model_usage"

# Models the operator may pick in the console. Anything else is rejected before the gateway,
# so an unknown identifier can never reach a provider SDK.
SUPPORTED_MODELS = ["gemini-3.5-flash", "gemini-3.5-pro"]

# Simulated demo latencies land in this window. Real model calls report measured time.
_DEMO_LATENCY_MIN_S = 0.35
_DEMO_LATENCY_SPAN_S = 1.30


class BackendReply(BaseModel):
    content: str
    model: str
    mode: ChatMode
    latency_s: float = 0.0
    latency_simulated: bool = False
    error: str = ""
    # Token counts as the provider reported them, or None when nothing was metered - a demo
    # reply and a live reply whose response carried no usage block are both honestly empty here.
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class ModelBackend(abc.ABC):
    """Contract every provider implements. `name` identifies the provider in telemetry."""

    name: str = "backend"

    @abc.abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        config_digest: str = ""
    ) -> BackendReply:
        raise NotImplementedError


def simulated_latency(model: str) -> float:
    """Stand-in duration for the demo backend, derived from the model name.

    Deterministic on purpose: the same model always reports the same value, so the number is
    reproducible in tests and cannot be mistaken for a measurement that varies per run.
    """
    digest = hashlib.sha256(model.encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return round(_DEMO_LATENCY_MIN_S + fraction * _DEMO_LATENCY_SPAN_S, 3)


class DeterministicDemoBackend(ModelBackend):
    """Answers without calling a model, and says so in the answer itself.

    It reflects the request the console assembled - model, skills, prompt version, guardrail
    verdict - so the pipeline stays demonstrable end to end. It never drafts subject-matter
    content, because content invented by a stub and shown next to a model badge would be
    indistinguishable from a real answer.
    """

    name = "deterministic-demo"

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        config_digest: str = ""
    ) -> BackendReply:
        lines = [
            "Demo mode: no model was called.",
            "",
            "This deployment has no GEMINI_API_KEY, so the console reports what it assembled "
            "for your request instead of presenting an invented answer as a model reply.",
            "",
            "Resolved request",
            f"  requested model      {model}",
        ]
        if config_digest:
            lines.extend(f"  {line}" for line in config_digest.splitlines())
        lines.extend([
            f"  system prompt        {len(system_prompt)} characters",
            f"  your message         {len(user_message)} characters, cleared by Model Armor",
            "",
            "Every step above already ran: the request passed the guardrail scan and the "
            "Sovereign Gateway. Set GEMINI_API_KEY and restart to route this exact request "
            f"to {model}.",
        ])
        return BackendReply(
            content="\n".join(lines),
            model=model,
            mode=ChatMode.DETERMINISTIC_DEMO,
            latency_s=simulated_latency(model),
            latency_simulated=True
        )


def read_usage(response: Any) -> Dict[str, Optional[int]]:
    """Token counts out of a provider response, defensively.

    `usage_metadata` is absent on some responses and carries None fields on others, so every
    hop is a getattr with a default rather than an attribute walk that would turn a metering
    detail into a failed model call.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {"prompt_tokens": None, "output_tokens": None, "total_tokens": None}

    def _count(*names: str) -> Optional[int]:
        for name in names:
            value = getattr(usage, name, None)
            if isinstance(value, int):
                return value
        return None

    return {
        "prompt_tokens": _count("prompt_token_count", "input_token_count"),
        "output_tokens": _count("candidates_token_count", "output_token_count"),
        "total_tokens": _count("total_token_count"),
    }


def record_usage(model: str, usage: Dict[str, Optional[int]]) -> bool:
    """Put a metered call on the gate-ledger row it ran under, if it ran under one.

    Lands on the span the Sovereign Gateway bound around this tool call, so token spend is
    attributed to the very verdict row an operator is already reading, without this module
    knowing which agent made the call. Returns False outside the gateway (direct backend use in
    tests) - the same deliberate no-op `telemetry.record_on_active_span` documents.
    """
    if all(value is None for value in usage.values()):
        return False
    payload: Dict[str, Any] = {"model": model}
    payload.update({key: value for key, value in usage.items() if value is not None})
    return telemetry.record_on_active_span(MODEL_USAGE_EVENT, payload)


class GeminiBackend(ModelBackend):
    """Calls Gemini through the google-genai SDK, off the event loop.

    A failed call falls back to the demo backend and carries the failure reason into the reply,
    so an outage reads as an outage rather than as a quieter model.
    """

    name = "gemini"

    def __init__(self, fallback: Optional[ModelBackend] = None):
        self._fallback = fallback or DeterministicDemoBackend()

    @property
    def api_key(self) -> str:
        """Read on every call so a key added at runtime takes effect without a restart."""
        return settings.gemini_api_key

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        config_digest: str = ""
    ) -> BackendReply:
        started = time.perf_counter()
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=[user_message],
                config=types.GenerateContentConfig(system_instruction=system_prompt)
            )
            text = (getattr(response, "text", "") or "").strip()
            if not text:
                raise ValueError("model returned an empty response")

            usage = read_usage(response)
            record_usage(model, usage)
            return BackendReply(
                content=text,
                model=model,
                mode=ChatMode.GEMINI_LIVE,
                latency_s=round(time.perf_counter() - started, 3),
                **usage
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning("Gemini chat call failed (%s) - answering from the demo backend", reason)
            reply = await self._fallback.complete(system_prompt, user_message, model, config_digest)
            reply.error = reason
            reply.content = (
                f"The call to {model} failed ({reason}). "
                "The console fell back to demo mode; the text below is not model output.\n\n"
                + reply.content
            )
            return reply


def create_backend() -> ModelBackend:
    """Pick the provider from configuration - the single place that decides live versus demo."""
    if settings.gemini_api_key:
        return GeminiBackend()
    return DeterministicDemoBackend()


def available_models() -> List[str]:
    return list(SUPPORTED_MODELS)
