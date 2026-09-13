"""The occasion vocabulary - the join key between signals and products.

This is the piece the old design was missing, and the reason a festival could
never reach a product. A product taxonomy answers "what IS this thing", so
"Diwali" and "Banarasi Silk Saree" share nothing and category overlap can never
fire. They do share an OCCASION. Once occasion is a first-class attribute on
both sides, the causal relation (an event drives demand for a product) becomes
an ordinary join:

    Diwali          -> festive, gifting
    Banarasi Saree  -> festive, wedding      => overlap on `festive`
    Nike Air Max    -> casual, sport_active  => no overlap

Design constraint, and it is the opposite of the product vocabulary: this set
must stay SMALL and CLOSED. The product taxonomy can afford 465 terms because
only one side uses it. Occasion is the join key, so both the product enricher
and the signal interpreter must choose from the exact same list - a large or
open set would produce near-misses that never intersect ("diwali" vs
"festive" vs "festival season" naming the same thing three ways).

Shopify's taxonomy has no Occasion attribute (the closest, "Occasion style"
id 1203, offers only "casual" and "dress"), so this is defined here rather
than vendored. Indian marketplaces treat occasion as a first-class browse
dimension (Myntra /wedding-wear, /ethnic-wear), so it is a real merchandising
axis - just not a standardised one.
"""

from enum import Enum


class Occasion(str, Enum):
    FESTIVE = "festive"
    WEDDING = "wedding"
    BRIDAL = "bridal"
    GIFTING = "gifting"
    CASUAL = "casual"
    PARTY = "party"
    WORK_FORMAL = "work_formal"
    SPORT_ACTIVE = "sport_active"
    TRAVEL = "travel"
    RELIGIOUS = "religious"
    SUMMER = "summer"
    WINTER = "winter"
    MONSOON = "monsoon"


# Shown to the model so it chooses on meaning rather than guessing from the
# bare slug. Kept terse - this goes into every enrichment and interpretation
# prompt, so wordiness here is paid for on every call.
OCCASION_DESCRIPTIONS = {
    Occasion.FESTIVE: "festival season wear and goods (Diwali, Navratri, Eid, Onam, Pongal, Christmas)",
    Occasion.WEDDING: "wedding guest and wedding-function wear, trousseau, sangeet, mehndi",
    Occasion.BRIDAL: "worn by the bride or groom specifically, not guests",
    Occasion.GIFTING: "commonly bought as a gift for someone else rather than for oneself",
    Occasion.CASUAL: "everyday and loungewear",
    Occasion.PARTY: "evening, clubbing, cocktail, new year",
    Occasion.WORK_FORMAL: "office, formal, business, interview",
    Occasion.SPORT_ACTIVE: "sports, gym, running, athleisure, yoga",
    Occasion.TRAVEL: "travel, vacation, resort, beach",
    Occasion.RELIGIOUS: "puja, temple, prayer and ceremony wear, religious articles",
    Occasion.SUMMER: "hot-weather specific (linen, cottons, sun protection)",
    Occasion.WINTER: "cold-weather specific (woollens, jackets, shawls)",
    Occasion.MONSOON: "rain-season specific (quick-dry, waterproof, umbrellas)",
}

ALL_OCCASIONS = [o.value for o in Occasion]


def prompt_block():
    """The occasion list as it appears in prompts.

    Both sides of the join call this, so neither can drift from the other -
    the failure mode this vocabulary exists to prevent.
    """
    return "\n".join(f"- {o.value}: {OCCASION_DESCRIPTIONS[o]}" for o in Occasion)


def canonicalize(value):
    """Map a model-supplied string onto the closed set, or None.

    Models return "Festive", "festivals", "festive_wear" for the same concept;
    the same case-insensitive discipline the tag vocabulary needed applies
    here, plus a small alias table for the near-misses seen most often.
    """
    if not value:
        return None
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if key in _BY_VALUE:
        return _BY_VALUE[key]
    return _ALIASES.get(key)


def canonicalize_all(values):
    """Canonicalize a list, dropping unmappable entries and duplicates.

    Order is preserved rather than sorted so the model's own ordering (most
    relevant first) survives into storage.
    """
    seen = []
    for value in values or []:
        canonical = canonicalize(value)
        if canonical and canonical not in seen:
            seen.append(canonical)
    return seen


_BY_VALUE = {o.value: o.value for o in Occasion}

# Deliberately narrow: aliases for phrasings a model plausibly returns, not a
# general synonym dictionary. Anything not here is dropped rather than guessed,
# so an unmappable value fails visibly instead of landing in the wrong bucket.
_ALIASES = {
    "festival": Occasion.FESTIVE.value,
    "festivals": Occasion.FESTIVE.value,
    "festive_wear": Occasion.FESTIVE.value,
    "festival_season": Occasion.FESTIVE.value,
    "diwali": Occasion.FESTIVE.value,
    "navratri": Occasion.FESTIVE.value,
    "eid": Occasion.FESTIVE.value,
    "christmas": Occasion.FESTIVE.value,
    "ethnic": Occasion.FESTIVE.value,
    "ethnic_wear": Occasion.FESTIVE.value,
    "weddings": Occasion.WEDDING.value,
    "wedding_wear": Occasion.WEDDING.value,
    "wedding_guest": Occasion.WEDDING.value,
    "sangeet": Occasion.WEDDING.value,
    "mehndi": Occasion.WEDDING.value,
    "bride": Occasion.BRIDAL.value,
    "groom": Occasion.BRIDAL.value,
    "gift": Occasion.GIFTING.value,
    "gifts": Occasion.GIFTING.value,
    "everyday": Occasion.CASUAL.value,
    "daily": Occasion.CASUAL.value,
    "loungewear": Occasion.CASUAL.value,
    "evening": Occasion.PARTY.value,
    "cocktail": Occasion.PARTY.value,
    "nightout": Occasion.PARTY.value,
    "night_out": Occasion.PARTY.value,
    "formal": Occasion.WORK_FORMAL.value,
    "office": Occasion.WORK_FORMAL.value,
    "work": Occasion.WORK_FORMAL.value,
    "business": Occasion.WORK_FORMAL.value,
    "sport": Occasion.SPORT_ACTIVE.value,
    "sports": Occasion.SPORT_ACTIVE.value,
    "active": Occasion.SPORT_ACTIVE.value,
    "activewear": Occasion.SPORT_ACTIVE.value,
    "athleisure": Occasion.SPORT_ACTIVE.value,
    "gym": Occasion.SPORT_ACTIVE.value,
    "vacation": Occasion.TRAVEL.value,
    "holiday": Occasion.TRAVEL.value,
    "resort": Occasion.TRAVEL.value,
    "beach": Occasion.TRAVEL.value,
    "puja": Occasion.RELIGIOUS.value,
    "pooja": Occasion.RELIGIOUS.value,
    "temple": Occasion.RELIGIOUS.value,
    "prayer": Occasion.RELIGIOUS.value,
    "hot_weather": Occasion.SUMMER.value,
    "cold_weather": Occasion.WINTER.value,
    "rain": Occasion.MONSOON.value,
    "rainy": Occasion.MONSOON.value,
    "monsoons": Occasion.MONSOON.value,
}
