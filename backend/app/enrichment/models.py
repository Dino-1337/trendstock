"""Product enrichment schemas.

Division of labour, and it is deliberate:

- CATEGORIES come from the rule-based tagger against the Shopify vocabulary.
  Deterministic, free, and now that the coordination/synonym/script bugs are
  fixed, good on Indian wear. Crucially it keeps the 465-term tag list OUT of
  the prompt - inlining it is what blew Groq's TPM budget in llm_groq.py.
- OCCASIONS, MATERIALS, AUDIENCE, STYLE come from the model, because they are
  judgements about how a product is used rather than lookups of what it is.
  The occasion set is small and closed, so it costs almost nothing to state.

Same principle as everywhere else in this codebase: compute what is
computable, infer only what needs inference.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enrichment.occasions import canonicalize_all


class Audience(str, Enum):
    WOMEN = "women"
    MEN = "men"
    UNISEX = "unisex"
    KIDS = "kids"


class PriceTier(str, Enum):
    BUDGET = "budget"
    MID = "mid"
    PREMIUM = "premium"


class ProductEnrichmentLLM(BaseModel):
    """What the model returns for ONE product. Strict, so an invented field
    fails loudly rather than being silently dropped."""

    model_config = ConfigDict(extra="forbid")

    occasions: list[str] = Field(
        default_factory=list,
        description="From the fixed occasion list only.",
    )
    materials: list[str] = Field(default_factory=list, max_length=8)
    audience: Audience | None = None
    style_descriptors: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("occasions")
    @classmethod
    def _canonical_occasions(cls, v):
        # Canonicalized at the validation boundary so nothing downstream ever
        # sees a raw model string. An unmappable value is dropped rather than
        # guessed - a wrong occasion silently corrupts the join.
        return canonicalize_all(v)

    @field_validator("materials", "style_descriptors")
    @classmethod
    def _clean(cls, v):
        return [s.strip().lower() for s in v if s and s.strip()]


class ProductEnrichmentBatchLLM(BaseModel):
    """One response covering a batch of products, keyed by their index in the
    request - the same numbering scheme llm_groq.py uses."""

    model_config = ConfigDict(extra="forbid")

    products: dict[str, ProductEnrichmentLLM] = Field(default_factory=dict)

    @property
    def is_vacuous(self) -> bool:
        """Schema-valid but empty. The documented Groq failure mode in this
        codebase, and the reason enrichment unions with the rule-based floor
        instead of trusting the model outright."""
        return not self.products


class EnrichedProduct(BaseModel):
    """A product as stored and served."""

    product_id: str
    title: str | None = None
    categories: list[str] = Field(default_factory=list)
    occasions: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    audience: Audience | None = None
    style_descriptors: list[str] = Field(default_factory=list)
    price_tier: PriceTier | None = None
    source: str = "rule_based"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def has_occasions(self) -> bool:
        """Whether this product can participate in the occasion join at all.

        A product with no occasions is invisible to every event signal, so
        this is worth surfacing rather than letting it fail silently.
        """
        return bool(self.occasions)
