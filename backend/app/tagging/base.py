"""The tagger interface. Every backend (rule-based today, Groq LLM when a key
is present) returns the same shape, so callers never need to know which one
ran - though `source` records which one did, for auditability."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class TagResult:
    tags: List[str]              # vocabulary category names only - never free text
    source: str                  # "rule_based" | "llm_groq"
    detail: List[dict] = field(default_factory=list)  # optional audit trail
