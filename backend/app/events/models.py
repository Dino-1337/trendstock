"""Schemas for Type A (calendar/event-driven) trend signals.

Two families of model live here and the split is deliberate:

- ``*LLM`` models describe what we ask the model to return. They are strict
  (``extra="forbid"``) so a hallucinated field fails loudly instead of being
  silently dropped, and they carry no ids or timestamps - the model has no
  business inventing those.
- Domain models describe what we store and serve. They add provenance,
  identity and computed fields.

The hard-won lesson from app/tagging/tagger.py applies here too: a response can
be perfectly schema-valid and still useless. Groq once returned a well-formed
empty tag list for "nike air max", which is why tagging unions LLM output with
rule-based output rather than trusting it. ``is_vacuous`` below is the same
guard in this domain - validation proves shape, not substance.
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Level(str, Enum):
    """Qualitative scale for both demand lift and confidence.

    Deliberately not numeric: v1 does no quantitative forecasting, and a
    made-up "73% lift" would imply precision the pipeline cannot support.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EventType(str, Enum):
    NATIONAL = "national"
    REGIONAL = "regional"
    RELIGIOUS = "religious"
    SEASONAL = "seasonal"


class Phase(str, Enum):
    """How a signal was produced.

    BULK is the cheap onboarding pass over the whole catalog (calendar +
    reasoning, no live search). EVENT_REFRESH is the deep, search-backed pass
    for one category as its event approaches. Stored so the dashboard can show
    whether a conclusion has been researched or merely inferred.
    """

    BULK = "bulk"
    EVENT_REFRESH = "event_refresh"


class EvidenceKind(str, Enum):
    SEARCH_RESULT = "search_result"
    CALENDAR_ENTRY = "calendar_entry"
    MODEL_OUTPUT = "model_output"


# --- calendar -------------------------------------------------------------

class CalendarEvent(BaseModel):
    """A resolved event. Dates come from a calendar provider, never from model
    recall: Diwali, Eid and Navratri are lunar/lunisolar and move every year,
    which is exactly the sort of fact an LLM asserts confidently and wrongly.
    """

    model_config = ConfigDict(use_enum_values=False)

    name: str = Field(min_length=1)
    event_type: EventType | None = None
    regions: list[str] = Field(
        default_factory=list,
        description="Indian states/regions. Empty means pan-India.",
    )
    event_date: date
    date_is_estimated: bool = Field(
        default=False,
        description="Set when the provider's date for a lunar festival may shift.",
    )
    source: str | None = None

    @property
    def is_regional(self) -> bool:
        return bool(self.regions)

    def days_until(self, today: date | None = None) -> int:
        """Negative once the event has passed, so callers can filter on it."""
        return (self.event_date - (today or date.today())).days


# --- what the agent returns ----------------------------------------------

class CategorySignalLLM(BaseModel):
    """One (category, event) judgement as returned by the model.

    No event date here on purpose - the model judges *relevance and magnitude*
    for an event whose date we already resolved. Letting it restate the date
    would invite it to contradict the calendar.
    """

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1)
    event_name: str = Field(min_length=1)
    demand_lift: Level
    confidence: Level
    lead_time_days: int = Field(
        ge=0,
        le=365,
        description="How many days before the event demand starts rising.",
    )
    reasoning_summary: str = Field(min_length=1, max_length=2000)

    @field_validator("category", "event_name", "reasoning_summary")
    @classmethod
    def _strip(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("must not be blank or whitespace only")
        return stripped


class CategorySignalBatchLLM(BaseModel):
    """The full response for one agent call.

    Batched because the bulk pass judges a whole catalog at once - the same
    reason llm_groq.py sends all items in a single request.
    """

    model_config = ConfigDict(extra="forbid")

    signals: list[CategorySignalLLM] = Field(default_factory=list)

    @property
    def is_vacuous(self) -> bool:
        """True when the call succeeded but said nothing.

        Schema-valid emptiness is the documented failure mode in this codebase
        (see module docstring), and for events it is worse than for tags: an
        empty batch silently drops a genuinely relevant festival off the
        dashboard. Callers must treat this as a failure and fall back, not as
        "no events are relevant".
        """
        return not self.signals


# --- what we store and serve ---------------------------------------------

class Evidence(BaseModel):
    """Provenance for one conclusion.

    Recorded so a future chatbot can cite what it actually read instead of
    reconstructing a plausible-sounding rationale. Cheap now, unrecoverable
    later.
    """

    kind: EvidenceKind
    url: str | None = None
    title: str | None = None
    snippet: str | None = None
    retrieved_at: datetime
    cache_key: str | None = Field(
        default=None, description="Links back to api_cache for the full response."
    )


class CategoryEventSignal(BaseModel):
    """A stored signal: the model's judgement plus identity and provenance."""

    id: int | None = None
    category: str
    event: CalendarEvent
    demand_lift: Level | None = None
    confidence: Level | None = None
    lead_time_days: int | None = None
    reasoning_summary: str | None = None
    phase: Phase
    evidence: list[Evidence] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def days_until_event(self, today: date | None = None) -> int:
        return self.event.days_until(today)

    def is_in_lead_window(self, today: date | None = None) -> bool:
        """Whether the event is close enough to act on.

        This is the Phase 2 trigger: a category enters deep research when its
        event crosses into the lead time the Phase 1 pass estimated for it.
        Events already past are excluded.
        """
        if self.lead_time_days is None:
            return False
        days = self.days_until_event(today)
        return 0 <= days <= self.lead_time_days
