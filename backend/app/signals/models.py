"""Signal schemas - one shape for both Type A (calendar) and Type B (trends).

The convergence is the point. A festival and a viral aesthetic differ in where
they come from and how confidently they can be dated, but not in what the
seller needs from them: which occasions they lift, by how much, and how long
there is to react. Keeping one shape means the matcher, the storage and the
dashboard are written once rather than twice, and a new signal source is a new
fetcher rather than a new pipeline.

This replaces the relevance gate. The old gate asked "does this text contain an
apparel category word?" and so discarded "Diwali". The interpreter asks "would
this matter to THIS store, and which occasions does it lift?" - a judgement,
not a lookup, and one that reads Devanagari natively where the regex could not.
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enrichment.occasions import canonicalize_all
from app.events.models import Evidence, Level


class SignalType(str, Enum):
    EVENT = "event"   # dated, from the calendar - Type A
    TREND = "trend"   # organic/viral, usually undated - Type B


class Phase(str, Enum):
    """How thoroughly a signal was interpreted.

    BULK is the cheap pass (profile + reasoning, no live search). REFRESH is
    the deep, search-backed pass run when an event enters its lead window.
    Stored so the dashboard can show whether a conclusion was researched or
    merely inferred.
    """

    BULK = "bulk"
    REFRESH = "refresh"


class SignalInterpretationLLM(BaseModel):
    """What the model returns for one signal. Strict, so an invented field
    fails loudly instead of being silently dropped.

    Note there is no date field: for events the calendar already resolved it,
    and letting the model restate it invites contradiction. For trends there
    usually is no meaningful date at all.
    """

    model_config = ConfigDict(extra="forbid")

    relevant: bool = Field(
        description="Whether this signal could plausibly affect what this store sells."
    )
    affected_occasions: list[str] = Field(
        default_factory=list,
        description="From the fixed occasion list only. THE JOIN KEY.",
    )
    affected_categories: list[str] = Field(
        default_factory=list,
        description="Free-text product categories; validated against the vocabulary later.",
        max_length=12,
    )
    audience: str | None = None
    demand_lift: Level | None = None
    confidence: Level | None = None
    lead_time_days: int | None = Field(
        default=None, ge=0, le=365,
        description="How many days before the event demand starts rising.",
    )
    reasoning: str | None = Field(default=None, max_length=1500)

    @field_validator("affected_occasions")
    @classmethod
    def _canonical(cls, v):
        # Canonicalized at the boundary so nothing downstream sees a raw model
        # string. An unmappable value is dropped rather than guessed - a wrong
        # occasion silently corrupts the join.
        return canonicalize_all(v)

    @field_validator("reasoning")
    @classmethod
    def _strip(cls, v):
        # Optional, and deliberately so. Models reliably answer a rejection
        # with a bare {"relevant": false} and omit the explanation. Requiring
        # it meant a batch of ten events failed validation, burned its repair
        # attempts and was dropped entirely - losing nine useful judgements to
        # enforce a sentence nobody reads about an event we are discarding.
        stripped = (v or "").strip()
        return stripped or None

    @property
    def is_actionable(self) -> bool:
        """Relevant AND able to reach a product.

        A signal judged relevant but carrying no occasions cannot match
        anything, which is worse than being dropped: it would show on the
        dashboard as a live signal that silently affects zero products.
        """
        return self.relevant and bool(self.affected_occasions)


class SignalInterpretationBatchLLM(BaseModel):
    """Interpretations for a batch of signals, keyed by request index.

    Batching exists for rate limits, not speed. Interpreting a year of Indian
    holidays one call at a time is ~70 sequential requests, which exhausts
    Groq's free tier and spends most of its time in backoff. Ten per call turns
    that into seven.
    """

    model_config = ConfigDict(extra="forbid")

    signals: dict[str, SignalInterpretationLLM] = Field(default_factory=dict)

    @property
    def is_vacuous(self) -> bool:
        return not self.signals


class Signal(BaseModel):
    """An interpreted signal as stored and served."""

    id: int | None = None
    signal_type: SignalType
    name: str
    source: str | None = None
    event_id: int | None = None
    event_date: date | None = None
    affected_occasions: list[str] = Field(default_factory=list)
    affected_categories: list[str] = Field(default_factory=list)
    audience: str | None = None
    demand_lift: Level | None = None
    confidence: Level | None = None
    lead_time_days: int | None = None
    reasoning: str | None = None
    phase: Phase = Phase.BULK
    relevant: bool = True
    evidence: list[Evidence] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def days_until(self, today: date | None = None) -> int | None:
        if self.event_date is None:
            return None
        return (self.event_date - (today or date.today())).days

    def is_in_lead_window(self, today: date | None = None) -> bool:
        """Whether this signal is close enough to act on.

        Undated trends are always in window - there is no lead time to wait
        for, they are happening now. Dated events are in window once they
        cross the lead time the interpreter estimated, and drop out once past.
        """
        days = self.days_until(today)
        if days is None:
            return True
        if days < 0:
            return False
        return days <= (self.lead_time_days if self.lead_time_days is not None else 0)

    @property
    def can_match(self) -> bool:
        return self.relevant and bool(self.affected_occasions)
