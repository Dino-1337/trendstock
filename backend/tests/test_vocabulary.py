"""Vocabulary loading + matching (app/tagging/vocabulary.py). Pure, in-memory
(reads the vendored JSON files, no network) - safe to run every time."""

from app.tagging.vocabulary import Vocabulary, get_vocabulary


def test_vocabulary_loads_real_vendored_files():
    v = get_vocabulary()
    assert v.version
    assert v.source
    assert len(v.category_names) > 100
    assert "Sneakers" in v.category_names
    assert "Sandals" in v.category_names
    assert "T-Shirts" in v.category_names


def test_llm_candidate_tags_excludes_grouping_nodes():
    """'Shoes' is a grouping node with children (Sneakers, Sandals, ...) - it
    should never be offered to the LLM as a taggable leaf."""
    v = get_vocabulary()
    assert "Shoes" not in v.llm_candidate_tags
    assert "Sneakers" in v.llm_candidate_tags
    assert len(v.llm_candidate_tags) < len(v.category_names)


def test_match_handles_fused_csv_style_values():
    """The catalog's CSV Type column is one fused word ('tshirts', 'sneakers',
    'slides'), not natural English - matching must handle both forms."""
    v = get_vocabulary()
    assert ("Sneakers", "Sneakers", "category") in v.match("sneakers")
    assert ("T-Shirts", "T-Shirts", "category") in v.match("tshirts")
    assert ("T-Shirts", "T-Shirts", "category") in v.match("tshirt")  # singular


def test_match_resolves_attribute_value_to_parent_category():
    """'Slide' [Sandal style] is not itself a category - Shopify's taxonomy
    has no 'Slides' category at all - it must resolve to 'Sandals'."""
    v = get_vocabulary()
    hits = v.match("slides")
    assert ("Sandals", "Slide", "attribute_value") in hits
    assert not any(tag == "Slides" for tag, _, _ in hits)


def test_match_is_case_and_word_boundary_safe():
    v = get_vocabulary()
    # "Sweatshirts" must not spuriously trigger "Shirts" as a separate match.
    hits = v.match("sweatshirts")
    tags = {tag for tag, _, _ in hits}
    assert "Sweatshirts" in tags
    assert "Shirts" not in tags


def test_match_returns_empty_for_irrelevant_text():
    v = get_vocabulary()
    assert v.match("state election results and cricket scores") == []
    assert v.match("") == []
    assert v.match(None) == []


def test_is_valid_tag_and_canonicalize_are_case_insensitive_on_lookup():
    v = get_vocabulary()
    assert v.is_valid_tag("Sneakers") is True
    assert v.is_valid_tag("sneakers") is False  # exact-case membership check
    assert v.is_valid_tag("Not A Real Tag") is False

    assert v.canonicalize_tag("sneakers") == "Sneakers"
    assert v.canonicalize_tag("SNEAKERS") == "Sneakers"
    assert v.canonicalize_tag("  Sneakers  ") == "Sneakers"
    assert v.canonicalize_tag("Not A Real Tag") is None
    assert v.canonicalize_tag("") is None
    assert v.canonicalize_tag(None) is None


def test_vocabulary_files_are_vendored_locally_not_fetched():
    """No network dependency: constructing a Vocabulary must only touch the
    local filesystem paths under data/vocabulary/."""
    v = Vocabulary()  # would raise FileNotFoundError if the vendored files were missing
    assert len(v.terms) > 0
