"""Store-profile schemas.

The profile is split into what can be *computed* and what must be *inferred*,
and the split is the point. Product counts, price bands and category
distribution come out of the CSV deterministically - free, exact, and
impossible to hallucinate. Only positioning, audience and aesthetic need a
model. Keeping them apart means a profile is still useful (and honest) when no
LLM key is configured, and means a wrong inference can never corrupt a fact.

This mirrors the rule used for events: the calendar owns dates, the model owns
judgement.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PricePositioning(str, Enum):
    BUDGET = "budget"
    MID_MARKET = "mid_market"
    PREMIUM = "premium"
    LUXURY = "luxury"
    MIXED = "mixed"


class InferenceSource(str, Enum):
    COMPUTED = "computed"              # no LLM available; facts only
    COMPUTED_AND_LLM = "computed+llm"


class CategoryCount(BaseModel):
    name: str
    count: int


class StoreFacts(BaseModel):
    """Derived arithmetically from the catalog. Never from a model."""

    product_count: int = 0
    variant_count: int = 0
    price_min: float | None = None
    price_median: float | None = None
    price_max: float | None = None
    top_categories: list[CategoryCount] = Field(default_factory=list)
    product_types: list[str] = Field(default_factory=list)
    vendors: list[str] = Field(default_factory=list)
    catalog_fingerprint: str

    @property
    def is_empty(self) -> bool:
        return self.product_count == 0


class StoreProfileLLM(BaseModel):
    """The inferred half - exactly what the model is asked to return.

    Strict, so an invented field fails loudly. No numbers here: everything
    quantitative is already computed, and asking a model to restate figures it
    was given is an invitation to contradict them.
    """

    model_config = ConfigDict(extra="forbid")

    store_type: str = Field(
        min_length=1, max_length=120,
        description="What kind of store this is, e.g. 'women's ethnic wear'.",
    )
    target_audience: str = Field(min_length=1, max_length=300)
    price_positioning: PricePositioning
    style_descriptors: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Aesthetic/style words that characterise the catalog.",
    )
    summary: str = Field(
        min_length=1, max_length=1200,
        description="A short paragraph usable as grounding context in later prompts.",
    )

    @field_validator("store_type", "target_audience", "summary")
    @classmethod
    def _strip(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("must not be blank or whitespace only")
        return stripped

    @field_validator("style_descriptors")
    @classmethod
    def _clean_list(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()]


class StoreProfile(BaseModel):
    """Computed facts plus optional inference, as stored and served."""

    id: int | None = None
    facts: StoreFacts
    inferred: StoreProfileLLM | None = None
    inference_source: InferenceSource = InferenceSource.COMPUTED
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def matches_catalog(self, fingerprint: str) -> bool:
        """Whether this profile still describes the given catalog.

        The trigger for rebuilding: a seller who uploads a new CSV should not
        keep being described by their old one.
        """
        return self.facts.catalog_fingerprint == fingerprint

    def as_prompt_context(self) -> str:
        """Compact grounding block injected into agent prompts.

        Deliberately short. This gets prepended to every event-reasoning call,
        so verbosity here is paid for on every request.
        """
        lines = [f"Products in catalog: {self.facts.product_count}"]

        if self.facts.price_min is not None:
            lines.append(
                f"Price range: {self.facts.price_min:g}-{self.facts.price_max:g} "
                f"(median {self.facts.price_median:g})"
            )
        if self.facts.top_categories:
            top = ", ".join(
                f"{c.name} ({c.count})" for c in self.facts.top_categories[:10]
            )
            lines.append(f"Main categories: {top}")
        if self.facts.product_types:
            lines.append(f"Product types: {', '.join(self.facts.product_types[:10])}")

        if self.inferred:
            lines.append(f"Store type: {self.inferred.store_type}")
            lines.append(f"Target audience: {self.inferred.target_audience}")
            lines.append(f"Price positioning: {self.inferred.price_positioning.value}")
            if self.inferred.style_descriptors:
                lines.append(f"Style: {', '.join(self.inferred.style_descriptors)}")
            lines.append(f"Summary: {self.inferred.summary}")

        return "\n".join(lines)
