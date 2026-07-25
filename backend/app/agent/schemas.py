"""Pydantic structured output schemas for AgriSense agent nodes."""
from __future__ import annotations

from typing import List, Literal
from pydantic import BaseModel, Field


class IntentClassification(BaseModel):
    """Structured output for the classifier node."""

    intent: Literal["intake", "advisor", "recommender", "planner", "finance"] = Field(
        ...,
        description=(
            "The specialist node to route the message to:\n"
            "- recommender: asking WHICH crop to plant / crop suggestions / profitability\n"
            "- planner: crop already selected, requesting dated season plan/calendar\n"
            "- finance: itemized cost, profit, ROI, break-even, or what-if scenario\n"
            "- intake: stating/correcting farm facts (land size, budget, soil, location, season)\n"
            "- advisor: general weather, pest, fertilizer dose, price, or general advice"
        ),
    )
    reasoning: str = Field(
        default="",
        description="Short 1-sentence reasoning for the intent decision",
    )


class ExtractedMemories(BaseModel):
    """Structured output for auto memory extraction."""

    facts: List[str] = Field(
        default_factory=list,
        description=(
            "Durable, personal facts about the farmer (name, family, occupation, "
            "preferences, long-term goals). Excludes current farm profile data, weather, or temporary numbers."
        ),
    )
