"""Occasion vocabulary - the join key between signals and products.

Both sides of the join canonicalize through this module, so drift here is the
failure mode that silently stops festivals reaching products.
"""

import pytest

from app.enrichment.occasions import (
    ALL_OCCASIONS,
    OCCASION_DESCRIPTIONS,
    Occasion,
    canonicalize,
    canonicalize_all,
    prompt_block,
)


def test_the_set_stays_small():
    # It is the join key: both sides must agree, so a large or open set would
    # produce near-misses that never intersect.
    assert len(ALL_OCCASIONS) <= 15


def test_every_occasion_is_described_for_the_prompt():
    assert set(OCCASION_DESCRIPTIONS) == set(Occasion)


def test_prompt_block_lists_every_occasion():
    block = prompt_block()
    assert all(value in block for value in ALL_OCCASIONS)


def test_values_are_slug_safe():
    assert all(v == v.lower() and " " not in v for v in ALL_OCCASIONS)


# --- canonicalization -----------------------------------------------------

def test_exact_value_passes_through():
    assert canonicalize("festive") == "festive"


def test_canonicalization_is_case_insensitive():
    assert canonicalize("Festive") == "festive"


@pytest.mark.parametrize("raw", ["work formal", "work-formal", "  work_formal  "])
def test_spacing_and_separators_are_normalized(raw):
    assert canonicalize(raw) == "work_formal"


@pytest.mark.parametrize("raw,expected", [
    ("festival", "festive"),
    ("Diwali", "festive"),
    ("ethnic wear", "festive"),
    ("sangeet", "wedding"),
    ("bride", "bridal"),
    ("gifts", "gifting"),
    ("athleisure", "sport_active"),
    ("office", "work_formal"),
    ("cocktail", "party"),
    ("puja", "religious"),
    ("rainy", "monsoon"),
])
def test_common_model_phrasings_are_aliased(raw, expected):
    assert canonicalize(raw) == expected


def test_unknown_values_are_dropped_not_guessed():
    # Silently bucketing an unmappable value would corrupt the join; failing
    # visibly is the safer behaviour.
    assert canonicalize("interstellar travel agency") is None


def test_empty_input_is_handled():
    assert canonicalize("") is None and canonicalize(None) is None


# --- list handling --------------------------------------------------------

def test_list_canonicalizes_each_entry():
    assert canonicalize_all(["Diwali", "Wedding"]) == ["festive", "wedding"]


def test_list_drops_unmappable_entries():
    assert canonicalize_all(["festive", "nonsense"]) == ["festive"]


def test_list_deduplicates_after_aliasing():
    # "festival" and "diwali" both resolve to festive; the join key must not
    # be double-counted.
    assert canonicalize_all(["festival", "diwali", "festive"]) == ["festive"]


def test_list_preserves_model_ordering():
    # The model returns most-relevant-first; sorting would discard that.
    assert canonicalize_all(["wedding", "festive"]) == ["wedding", "festive"]


def test_empty_list_is_handled():
    assert canonicalize_all([]) == [] and canonicalize_all(None) == []
