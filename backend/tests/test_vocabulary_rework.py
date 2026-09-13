"""Vocabulary rework: coordinated names, synonyms, and non-Latin script.

Each group pins a defect found live against the real vocabulary, so a
regression shows up as a named failure rather than as quietly emptier tags.
"""

import pytest

from app.tagging.rule_based import tag_text
from app.tagging.vocabulary import _split_coordinated, get_vocabulary


@pytest.fixture(scope="module")
def vocabulary():
    return get_vocabulary()


def tags(text, vocabulary):
    return tag_text(text, vocabulary).tags


# --- coordinated names ----------------------------------------------------

def test_plain_name_is_left_alone():
    assert _split_coordinated("T-Shirts") == ["T-Shirts"]


def test_coordinate_nouns_split_into_independent_phrases():
    assert _split_coordinated("Saris & Lehengas") == ["Saris", "Lehengas"]


def test_leading_modifier_distributes_over_a_bare_tail():
    # "Snow Pants & Suits" means snow pants and snow SUITS, not any suit.
    assert _split_coordinated("Snow Pants & Suits") == ["Snow Pants", "Snow Suits"]


def test_modifier_distributes_across_a_comma_list():
    assert _split_coordinated("Dance Dresses, Skirts & Costumes") == [
        "Dance Dresses", "Dance Skirts", "Dance Costumes"
    ]


def test_multiword_tail_keeps_its_own_modifier():
    assert _split_coordinated("Kurtas & Kurta Sets") == ["Kurtas", "Kurta Sets"]


@pytest.mark.parametrize("text,expected", [
    ("kurta set for men", "Kurtas & Kurta Sets"),
    ("salwar kameez", "Salwar Kameez & Suit Sets"),
    ("dupatta chiffon", "Dupattas"),
])
def test_coordinated_categories_now_match_real_text(text, expected, vocabulary):
    # Before the fix these compiled to patterns needing the literal text
    # "kurtas kurta sets", so all 110 '&' names were unmatchable.
    assert expected in tags(text, vocabulary)


def test_bare_head_noun_does_not_leak_from_an_elliptical_name(vocabulary):
    # Regression guard: naive '&' splitting made "anarkali suit" match
    # "Snow Pants & Suits".
    assert "Snow Pants & Suits" not in tags("anarkali suit", vocabulary)


def test_elliptical_category_still_matches_its_own_text(vocabulary):
    assert any("Snow" in t for t in tags("snow suit for kids", vocabulary))


# --- synonyms -------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("silk saree for diwali", "Saris"),
    ("designer sherwani", "Kurtas & Kurta Sets"),
    ("cotton kurti women", "Kurtas & Kurta Sets"),
    ("anarkali suit", "Salwar Kameez & Suit Sets"),
    ("jhumka earrings gold", "Earrings"),
    ("bangles set", "Bracelets"),
    ("kolhapuri chappal", "Sandals"),
    ("pashmina stole", "Scarves & Shawls"),
])
def test_indian_vocabulary_resolves_to_taxonomy_categories(text, expected, vocabulary):
    assert expected in tags(text, vocabulary)


def test_every_synonym_maps_to_a_real_category(vocabulary):
    # A synonym may add a way to FIND a category, never a new tag.
    assert vocabulary.dropped_synonyms == []


def test_synonym_tags_stay_inside_the_controlled_vocabulary(vocabulary):
    synonym_tags = {t.tag for t in vocabulary.terms if t.kind == "synonym"}
    assert synonym_tags <= vocabulary.valid_tags


def test_synonyms_are_versioned(vocabulary):
    assert vocabulary.synonyms_version


# --- non-Latin script -----------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("साड़ी ऑनलाइन", "Saris"),
    ("कुर्ता सेट", "Kurtas & Kurta Sets"),
    ("लहंगा डिजाइन", "Lehengas"),
    ("শাড়ি", "Saris"),  # Bengali, not Devanagari - a different script entirely
])
def test_devanagari_and_bengali_terms_match(text, expected, vocabulary):
    # \b is defined by \w: "साड़ी" ends in a combining vowel sign whose
    # isalnum() is False, so a trailing \b made every non-Latin term
    # unmatchable. The IN feed is predominantly non-Latin, so this was the
    # difference between reading the feed and discarding it wholesale.
    assert expected in tags(text, vocabulary)


def test_non_commerce_devanagari_still_tags_nothing(vocabulary):
    # The gate must distinguish a Hindi saree trend from a Hindi news trend;
    # previously both tagged to [] and were indistinguishable.
    assert tags("गंगा एक्सप्रेस वे", vocabulary) == []


def test_non_commerce_english_still_tags_nothing(vocabulary):
    assert tags("india vs australia cricket", vocabulary) == []


# --- documented remaining weakness ---------------------------------------

@pytest.mark.parametrize("text,leaked", [
    ("boot camp startups", "Boots"),
    ("ring of fire volcano", "Rings"),
])
def test_context_free_false_positives_remain(text, leaked, vocabulary):
    """Documents a known limitation rather than asserting correct behaviour.

    Substring matching cannot tell "boot camp" from footwear; that needs
    context, which is the LLM tier's job. Pinned so the behaviour is a known
    quantity - if a later change fixes it, this test should be updated, not
    silently left passing for the wrong reason.
    """
    assert leaked in tags(text, vocabulary)
