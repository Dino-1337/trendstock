"""Onboarding pipeline: catalog -> store profile -> enriched products.

Ordered deliberately. The profile is built first because it is the grounding
context enrichment reads: "is this festive?" is a different question for a
bridal-wear store than for a streetwear store, and the profile is what tells
the model which one it is looking at.

Stages are reported through a progress callback so the UI can say what is
happening. Enrichment is the slow part - one model call per batch of ten - and
a seller watching an unexplained spinner assumes it has hung.
"""

from app.enrichment import product_enricher as pe
from app.logging_setup import get_logger
from app.profile import builder
from app.signals.pipeline import run_signal_pass

log = get_logger("pipeline")

# Human-facing stage labels. The UI shows these verbatim, so they are written
# from the seller's side: what is happening to THEIR catalog, not which module
# is executing.
STAGES = {
    "reading": "Reading your catalog",
    "profiling": "Understanding your store",
    "enriching": "Tagging products by occasion",
    "signals": "Finding upcoming events",
    "complete": "Done",
}


def _noop(**_fields):
    pass


def run_onboarding(conn, products, progress=None, use_llm=True, models=None):
    """Build (or reuse) the profile and enrichment for a catalog.

    Returns a summary dict. Both halves are cached on the catalog fingerprint,
    so re-running while the catalog is unchanged is nearly free and the UI
    still gets a coherent sequence of stages.
    """
    progress = progress or _noop
    products = products or []

    progress(stage="reading", message=STAGES["reading"], progress=0, total=len(products))

    if not products:
        progress(stage="complete", message="No products to process", progress=0, total=0)
        return {
            "products": 0, "profile_built": False, "enriched": 0,
            "enrichment_built": False, "catalog_fingerprint": None,
        }

    progress(stage="profiling", message=STAGES["profiling"])
    profile, profile_built = builder.get_or_build(
        conn, products, use_llm=use_llm, models=models
    )
    fingerprint = profile.facts.catalog_fingerprint

    progress(stage="enriching", message=STAGES["enriching"], progress=0, total=len(products))
    records, enrichment_built = pe.get_or_enrich(
        conn, products, fingerprint,
        store_context=profile.as_prompt_context(),
        use_llm=use_llm, models=models,
    )
    progress(progress=len(records))
    with_occasions = sum(1 for r in records if r.has_occasions)

    # Signals last: interpretation is grounded in the profile, and matching is
    # pointless until products carry occasions. A failure here still leaves a
    # usable catalog, so it degrades rather than failing onboarding.
    progress(stage="signals", message=STAGES["signals"])
    signal_summary = {}
    try:
        signal_summary = run_signal_pass(
            conn, profile.as_prompt_context(), progress=progress, models=models
        )
    except Exception as exc:
        log.warning("signal pass failed, catalog is still usable: %s", exc)

    progress(stage="complete", message=STAGES["complete"], progress=len(records))

    log.info(
        "onboarding complete: %d products, %d with occasions (profile_built=%s, enrichment_built=%s)",
        len(records), with_occasions, profile_built, enrichment_built,
    )

    return {
        "products": len(products),
        "profile_built": profile_built,
        "enriched": len(records),
        "enrichment_built": enrichment_built,
        "with_occasions": with_occasions,
        "catalog_fingerprint": fingerprint,
        "store_type": profile.inferred.store_type if profile.inferred else None,
        "signals": signal_summary,
    }
