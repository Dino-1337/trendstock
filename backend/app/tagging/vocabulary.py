"""The controlled tag vocabulary: Shopify's Standard Product Taxonomy.

Free-form tag generation is the classic failure mode here - you get
"sneaker"/"sneakers"/"trainers"/"athletic shoes" and none of them match each
other. So tags are never invented; they are always one of a fixed set of
terms selected from Shopify's own taxonomy (github.com/Shopify/product-taxonomy),
vendored locally under data/vocabulary/ so the pipeline has no runtime network
dependency on GitHub.

Only the Apparel & Accessories vertical is vendored (categories.json - the
full "aa" branch, 663 categories: clothing, shoes, jewelry, bags, clothing
accessories), plus a small curated set of distinctive sandal/sneaker style
attribute values (attribute_values.json). Generic single-word attribute
values (sport/activity names, "Casual", "Athletic") were deliberately left
out - see that file's own note for why. Both files carry their source
commit/version so provenance is auditable - see categories.json's "version".

Every tag this system ever produces is a Shopify category NAME (e.g.
"Sneakers", "Sandals", "T-Shirts") - never a raw word pulled from trend or
product text. Attribute-value matches (e.g. spotting "slide" in text) resolve
to their PARENT category's name ("Sandals"), not a separate free-floating tag,
so the tag set stays exactly as small and controlled as the category list.
"""

import json
import re

from app.storage.paths import VOCAB_DIR
CATEGORIES_PATH = VOCAB_DIR / "categories.json"
ATTRIBUTE_VALUES_PATH = VOCAB_DIR / "attribute_values.json"
SYNONYMS_PATH = VOCAB_DIR / "synonyms.json"


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _singularize(word):
    """'shirts' -> 'shirt', but 'dress'/'glass' stay put (already end in 'ss')."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _phrase_to_regex(phrase):
    """One phrase -> a regex source string, or None if it has no word chars.

    Non-Latin phrases (Devanagari, Bengali) are escaped literally rather than
    stemmed: `[a-z0-9]+` matches nothing in those scripts, and plural/stem
    rules built for English do not apply. Without this branch every non-Latin
    synonym would silently compile to None.
    """
    if not phrase or not phrase.strip():
        return None

    words = re.findall(r"[a-z0-9]+", phrase.lower())
    if not words:
        # No ASCII word characters - treat the whole phrase as a literal.
        return re.escape(phrase.strip()) if phrase.strip() else None

    parts = [re.escape(_singularize(w)) + "s?" for w in words]
    return r"[\s-]?".join(parts)


def _split_coordinated(name):
    """Split a coordinated category name into the phrases it actually denotes.

    Names coordinate with '&' and ',' in two different ways, and conflating
    them is what broke the old tagger (which stripped '&' and then required
    every word contiguously, so "Kurtas & Kurta Sets" became a pattern needing
    the literal text "kurtas kurta sets" - unmatchable; 110 of 557 names, 20%
    of the vocabulary and most of the Indian-wear entries, were dead weight).

    The two forms:

    1. Coordinate nouns - each part stands alone:
           "Saris & Lehengas"     -> Saris | Lehengas
    2. Elliptical, where a leading modifier distributes across the parts:
           "Snow Pants & Suits"   -> Snow Pants | Snow Suits
           "Bridal Dupattas & Shawls" -> Bridal Dupattas | Bridal Shawls

    Naively splitting form 2 yields a bare head noun ("Suits") that matches far
    too much - live check: "anarkali suit" matched "Snow Pants & Suits".

    Heuristic: if the first part is multi-word, its leading words are a shared
    modifier and are distributed onto later single-word parts. If the first
    part is a single word there is no modifier to share, so parts stand alone.
    Verified against the real vocabulary on "Dance Dresses, Skirts & Costumes"
    (-> Dance Dresses | Dance Skirts | Dance Costumes) and
    "Activewear Sweatshirts & Hoodies".
    """
    parts = [p.strip() for p in re.split(r"[&,]", name) if p.strip()]
    if len(parts) <= 1:
        return [name]

    head_words = parts[0].split()
    modifier = " ".join(head_words[:-1]) if len(head_words) > 1 else ""

    phrases = [parts[0]]
    for part in parts[1:]:
        # Only single-word tails are treated as elliptical; a multi-word tail
        # ("Kurta Sets") already carries its own modifier.
        if modifier and len(part.split()) == 1:
            phrases.append(f"{modifier} {part}")
        else:
            phrases.append(part)
    return phrases


def _name_to_pattern(name):
    """'T-Shirts' -> a regex matching 'tshirts', 't shirts', 't-shirt', 'tshirt', ...
    Every word is reduced to its singular stem then made optionally-plural, and
    inter-word separators (space/hyphen) become optional, so the catalog's
    fused CSV values ('tshirts') and natural English trend text ('T-Shirts',
    't shirts', singular or plural) all match the same pattern.

    Coordinated names ("A & B") become alternatives rather than a required
    sequence - see _split_coordinated for how the two coordination forms are
    told apart.
    """
    phrases = _split_coordinated(name)
    sources = []
    for phrase in phrases:
        source = _phrase_to_regex(phrase)
        if not source:
            continue
        # \b is defined by \w, which is Latin-centric in practice: "साड़ी" ends
        # in a combining vowel sign whose isalnum() is False, so a trailing \b
        # can never match and every Devanagari/Bengali term compiled to a
        # pattern that silently matched nothing. Boundaries are therefore
        # applied only to ASCII phrases; non-Latin terms are matched bare,
        # which is safe because they are specific multi-character words.
        if phrase.isascii():
            sources.append(r"\b" + source + r"\b")
        else:
            sources.append(source)

    if not sources:
        return None

    # Longest first so the more specific alternative wins the match position
    # ("Saris & Lehengas" should report the phrase it actually found).
    sources.sort(key=len, reverse=True)
    pattern = "(?:" + "|".join(sources) + ")"

    # IGNORECASE matters: patterns are built from lowercased vocabulary names,
    # but they are matched against raw product/trend text. A real Shopify
    # export capitalises its Type column ("T-Shirt", "Jeans", "Sneakers"), so
    # without this the tagger silently matches nothing on real data - it only
    # appeared to work because the sample catalog happened to be lowercase.
    return re.compile(pattern, re.IGNORECASE)


class VocabTerm:
    __slots__ = ("tag", "label", "pattern", "kind", "detail")

    def __init__(self, tag, label, pattern, kind, detail=None):
        self.tag = tag          # canonical tag = category name, used for matching/scoring
        self.label = label      # the specific vocabulary term that matched (for audit trails)
        self.pattern = pattern
        self.kind = kind        # "category" | "attribute_value"
        self.detail = detail    # e.g. attribute name, for attribute_value terms


class Vocabulary:
    """Loaded once, reused by both taggers and the relevance gate."""

    def __init__(self, categories_path=CATEGORIES_PATH, attribute_values_path=ATTRIBUTE_VALUES_PATH,
                 synonyms_path=SYNONYMS_PATH):
        categories_doc = _load_json(categories_path)
        attributes_doc = _load_json(attribute_values_path)
        synonyms_doc = _load_json(synonyms_path) if synonyms_path and synonyms_path.exists() else {}

        self.version = categories_doc.get("version")
        self.source = categories_doc.get("source")

        # Category names repeat across different branches of the taxonomy
        # (e.g. "Shorts" exists under both Clothing and Activewear). For
        # tagging purposes we only need the concept, so terms are deduplicated
        # by name - a tag is a category NAME, not a specific taxonomy id.
        seen_names = set()
        self.category_names = []
        terms = []
        all_ids = {cat.get("id") for cat in categories_doc.get("categories", [])}
        leaf_names = set()
        for cat in categories_doc.get("categories", []):
            name = cat.get("name", "").strip()
            key = name.lower()
            cat_id = cat.get("id", "")
            is_leaf = not any(other.startswith(cat_id + "-") for other in all_ids)
            if not name or key in seen_names or len(key) < 3:
                if name and is_leaf:
                    leaf_names.add(name)  # still worth keeping as an LLM candidate even if a dup name
                continue
            seen_names.add(key)
            pattern = _name_to_pattern(name)
            if pattern is None:
                continue
            self.category_names.append(name)
            terms.append(VocabTerm(tag=name, label=name, pattern=pattern, kind="category"))
            if is_leaf:
                leaf_names.add(name)

        # Attribute values resolve to their parent category's name, not a
        # separate tag - "Slide" [Sandal style] found in text means the
        # "Sandals" tag applies, same as if the text had said "sandals".
        for value in attributes_doc.get("values", []):
            label = value.get("name", "").strip()
            category_name = value.get("category_name", "").strip()
            if not label or not category_name:
                continue
            pattern = _name_to_pattern(label)
            if pattern is None:
                continue
            terms.append(VocabTerm(
                tag=category_name, label=label, pattern=pattern,
                kind="attribute_value", detail=value.get("attribute"),
            ))

        # Curated synonyms: extra ways to FIND an existing category, never new
        # tags. A synonym whose tag is not a real category name is dropped
        # rather than silently widening the tag set - the whole point of a
        # controlled vocabulary is that nothing invents a term.
        valid_names = {name.lower(): name for name in self.category_names}
        self.synonyms_version = synonyms_doc.get("version")
        self.dropped_synonyms = []
        for entry in synonyms_doc.get("synonyms", []):
            term = (entry.get("term") or "").strip()
            target = (entry.get("tag") or "").strip()
            canonical = valid_names.get(target.lower())
            if not term or not canonical:
                if term:
                    self.dropped_synonyms.append({"term": term, "tag": target})
                continue
            pattern = _name_to_pattern(term)
            if pattern is None:
                continue
            terms.append(VocabTerm(
                tag=canonical, label=term, pattern=pattern, kind="synonym",
            ))

        self.terms = terms
        self.valid_tags = frozenset(self.category_names)
        # LLMs don't reliably preserve exact case even when told to copy a
        # term verbatim (observed live: "Sneakers" came back as "sneakers").
        # Validation is case-insensitive; the canonical (vendored) casing is
        # always what gets returned/stored, never the model's own casing.
        self._canonical_by_lower = {name.lower(): name for name in self.category_names}
        # Leaf-only, sorted for a deterministic prompt: passing all 557 vendored
        # category names (including grouping nodes like "Shoes" or "Clothing"
        # that you'd never actually want as a final tag when "Sneakers" is
        # available) to an LLM burns tokens for no benefit. ~465 leaf names
        # keeps the free-tier prompt well within Groq's TPM budget.
        self.llm_candidate_tags = sorted(leaf_names)

    def match(self, text):
        """Return a list of (tag, label, kind) for every vocabulary term found
        in `text`, deduplicated to the most specific match per tag (a tag can
        be found via its own category name AND an attribute-value synonym;
        we keep one representative hit, preferring the category-name hit)."""
        if not text:
            return []
        hits = {}
        for term in self.terms:
            if term.pattern.search(text):
                existing = hits.get(term.tag)
                if existing is None or (existing[2] == "attribute_value" and term.kind == "category"):
                    hits[term.tag] = (term.tag, term.label, term.kind)
        return list(hits.values())

    def is_valid_tag(self, tag):
        return tag in self.valid_tags

    def canonicalize_tag(self, tag):
        """Case-insensitive vocabulary lookup. Returns the canonical (vendored)
        tag string, or None if `tag` isn't in the vocabulary under any casing."""
        if not tag:
            return None
        return self._canonical_by_lower.get(tag.strip().lower())


_default_vocabulary = None


def get_vocabulary():
    global _default_vocabulary
    if _default_vocabulary is None:
        _default_vocabulary = Vocabulary()
    return _default_vocabulary
