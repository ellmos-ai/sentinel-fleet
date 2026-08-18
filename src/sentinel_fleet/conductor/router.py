"""Model Router & Strategy based on clutch."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class ModelTier(str, Enum):
    FAST = "gemini-3.5-flash"
    PRO = "gemini-3.5-pro"
    LOCAL_FALLBACK = "gemma-2-9b"


class RoutingStrategy(BaseModel):
    preferred_tier: ModelTier = ModelTier.FAST
    escalation_tier: ModelTier = ModelTier.PRO
    max_retries: int = 3
    cost_budget_usd: float = 10.0


class ModelRouter:
    def __init__(self, strategy: Optional[RoutingStrategy] = None):
        self.strategy = strategy or RoutingStrategy()

    def select_model(self, task_complexity: str = "normal") -> str:
        """Route to appropriate model tier based on task complexity."""
        if task_complexity == "high":
            return self.strategy.escalation_tier.value
        return self.strategy.preferred_tier.value


model_router = ModelRouter()
