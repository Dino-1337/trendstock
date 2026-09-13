"""Interpret a signal into the occasions it lifts.

This is what replaces the relevance gate. The gate asked a lookup question -
"does this text contain an apparel category word?" - and so answered "no" for
Diwali and dropped it. The interpreter asks a judgement question: given what
this store sells, would this signal move demand, and for which occasions?

Two passes, differing only in depth:

- BULK   : profile + model reasoning. No search. Cheap enough to run over a
           whole calendar year at onboarding.
- REFRESH: adds live Exa research for one signal, and records what it read as
           evidence. Run when an event enters its lead window, or on demand.

Grounding rules, consistent with the rest of the pipeline:
- The calendar owns dates. The model is told the date and never asked for one.
- The store profile is always in context, so "is this festive?" is answered for
  THIS store rather than in the abstract.
"""

from datetime import datetime, timezone

from app.enrichment.occasions import prompt_block
from app.events.models import Level
from app.llm import client as llm
from app.logging_setup import get_logger
from app.research import exa_client
from app.signals.models import (
    Phase,
    Signal,
    SignalInterpretationBatchLLM,
    SignalInterpretationLLM,
    SignalType,
)
from app.tagging.vocabulary import get_vocabulary

log = get_logger("signals")

# Evidence rows kept per refresh. Enough to show a seller why, few enough that
# the dashboard cell stays readable and storage stays small.
EVIDENCE_LIMIT = 4
SEARCH_RESULTS = 5

# Events per bulk call. Sized for rate limits rather than throughput: one call
# per event exhausts Groq's free tier on a full calendar year.
BATCH_SIZE = 10


def _search_query(name, signal_type, store_type=None):
    """Research query for the refresh pass.

    Deliberately asks about demand and timing rather than the event itself -
    "what is Diwali" is not useful; "which products sell, and how early" is.
    """
    subject = store_type or "small e-commerce sellers"
    if signal_type is SignalType.EVENT:
        return (
            f"{name} India {datetime.now(timezone.utc).year} demand for {subject} "
            "which product categories sell, how many weeks before"
        )
    return f"{name} trend India shopping demand which products {subject}"


def _build_prompt(name, signal_type, store_context, event_date=None,
                  days_until=None, research=None):
    when = ""
    if event_date:
        when = f"\nDATE: {event_date}"
        if days_until is not None:
            when += f" ({days_until} days from today)"

    research_block = ""
    if research:
        research_block = (
            "\nRESEARCH (recent sources - use these for timing and specifics, "
            "and ignore anything irrelevant):\n" + research + "\n"
        )

    kind = "calendar event or festival" if signal_type is SignalType.EVENT else "trending topic"

    return (
        "You advise a small e-commerce seller on which upcoming events and "
        f"trends will move their sales. Assess this {kind}.\n\n"
        f"SIGNAL: {name}{when}\n"
        f"{research_block}\n"
        f"THE SELLER'S STORE:\n{store_context}\n\n"
        "Decide whether this signal would plausibly change demand for what "
        "THIS store sells. Most signals will not - news, sport, politics and "
        "celebrity stories usually have no retail effect, and a festival that "
        "drives ethnic wear is irrelevant to a store selling running shoes. "
        "Say so rather than inventing a connection.\n\n"
        "If it IS relevant, choose the occasions it lifts, using the exact "
        "slugs from this fixed list:\n"
        f"{prompt_block()}\n\n"
        "Also estimate:\n"
        "- demand_lift: low, medium or high\n"
        "- confidence: low, medium or high\n"
        "- lead_time_days: how many days BEFORE the event demand starts "
        "rising (Diwali apparel is roughly 30-35 days; a small observance "
        "may be 3-7)\n"
        "- affected_categories: product categories in plain words\n"
        "- audience: women, men, unisex or kids, if one clearly dominates\n\n"
        "Respond with ONLY a single JSON object (no prose, no markdown fences):\n"
        '{"relevant": true, "affected_occasions": ["festive"], '
        '"affected_categories": ["sarees"], "audience": "women", '
        '"demand_lift": "high", "confidence": "medium", "lead_time_days": 30, '
        '"reasoning": "one or two sentences"}\n'
        'If it is not relevant, return {"relevant": false, '
        '"affected_occasions": [], "affected_categories": [], '
        '"audience": null, "demand_lift": null, "confidence": null, '
        '"lead_time_days": null, "reasoning": "why not"}'
    )


def _format_research(response):
    """Flatten Exa results into a compact block for the prompt."""
    lines = []
    for result in (response or {}).get("results", [])[:SEARCH_RESULTS]:
        title = (result.get("title") or "").strip()
        highlights = " ".join(h.strip() for h in (result.get("highlights") or []) if h)
        if title or highlights:
            lines.append(f"- {title}: {highlights}"[:600])
    return "\n".join(lines)


def _canonical_categories(raw, vocabulary):
    """Map model-supplied category words onto the controlled vocabulary.

    The model is asked for plain words ("sarees") rather than exact taxonomy
    names, because inlining the 465-term list is what blew Groq's TPM budget.
    Matching them back through the same tagger the products use keeps both
    sides of the join speaking one vocabulary.
    """
    from app.tagging.rule_based import tag_text

    tags = []
    for phrase in raw or []:
        for tag in tag_text(phrase, vocabulary).tags:
            if tag not in tags:
                tags.append(tag)
    return tags


def interpret(name, signal_type, store_context, event_date=None, days_until=None,
              source=None, event_id=None, conn=None, phase=Phase.BULK,
              models=None, vocabulary=None):
    """Interpret one signal. Returns a Signal.

    `phase=REFRESH` adds a live Exa search and attaches what it read as
    evidence. A search failure degrades to the bulk path rather than failing
    the interpretation - a missing citation is much better than no signal.
    """
    vocabulary = vocabulary or get_vocabulary()
    research, evidence = None, []

    if phase is Phase.REFRESH and exa_client.is_available():
        try:
            store_type = (store_context or "").split("Store type:")[-1].split("\n")[0].strip()
            query = _search_query(name, signal_type, store_type or None)
            response, cache_key, _cached = exa_client.search(
                query, conn=conn, num_results=SEARCH_RESULTS
            )
            research = _format_research(response)
            evidence = exa_client.to_evidence(response, cache_key=cache_key,
                                              limit=EVIDENCE_LIMIT)
        except Exception as exc:
            log.warning("research failed for %r, interpreting without it: %s", name, exc)

    messages = [{
        "role": "user",
        "content": _build_prompt(name, signal_type, store_context, event_date,
                                 days_until, research),
    }]
    result = llm.structured(
        messages, SignalInterpretationLLM,
        models=models or llm.REASONING_MODELS, max_tokens=900,
    )

    return Signal(
        signal_type=signal_type,
        name=name,
        source=source,
        event_id=event_id,
        event_date=event_date,
        affected_occasions=result.affected_occasions,
        affected_categories=_canonical_categories(result.affected_categories, vocabulary),
        audience=result.audience,
        demand_lift=result.demand_lift,
        confidence=result.confidence,
        lead_time_days=result.lead_time_days,
        reasoning=result.reasoning,
        phase=phase,
        relevant=result.relevant,
        evidence=evidence,
    )


def _build_batch_prompt(events, store_context, today):
    numbered = []
    for index, event in enumerate(events):
        days = event.days_until(today)
        numbered.append(
            f"{index}: {event.name} - {event.event_date} ({days} days from today)"
        )

    return (
        "You advise a small e-commerce seller on which upcoming events will "
        "move their sales. Assess EACH numbered event below.\n\n"
        f"THE SELLER'S STORE:\n{store_context}\n\n"
        f"EVENTS:\n" + "\n".join(numbered) + "\n\n"
        "For each, decide whether it would plausibly change demand for what "
        "THIS store sells. Many will not - equinoxes, political anniversaries "
        "and imported holidays usually have no retail effect for an Indian "
        "seller, and a festival that drives ethnic wear is irrelevant to a "
        "store selling running shoes. Mark those relevant: false rather than "
        "inventing a connection.\n\n"
        "For relevant events choose occasions using the exact slugs from this "
        "fixed list:\n"
        f"{prompt_block()}\n\n"
        "Also give demand_lift (low/medium/high), confidence, "
        "lead_time_days (how many days BEFORE the event demand starts rising - "
        "Diwali apparel is roughly 30-35 days, a minor observance 3-7), "
        "affected_categories in plain words, and audience "
        "(women/men/unisex/kids) if one clearly dominates.\n\n"
        "Respond with ONLY a single JSON object (no prose, no markdown fences):\n"
        '{"signals": {"0": {"relevant": true, "affected_occasions": ["festive"], '
        '"affected_categories": ["sarees"], "audience": "women", '
        '"demand_lift": "high", "confidence": "medium", "lead_time_days": 30, '
        '"reasoning": "one sentence"}, '
        '"1": {"relevant": false, "reasoning": "no retail effect"}}}\n'
        "Every event number above must appear as a key. For an irrelevant "
        "event the short form above is enough - do not fill in occasions, "
        "categories or estimates for something you are rejecting."
    )


def interpret_events(events, store_context, today, conn=None, phase=Phase.BULK,
                     models=None, vocabulary=None, progress=None,
                     batch_size=BATCH_SIZE):
    """Interpret a list of CalendarEvents.

    Batched to survive rate limits: a year of Indian holidays is ~70 events,
    and one call each exhausts Groq's free tier long before finishing. A failed
    batch is skipped rather than raised - losing ten events is better than
    losing the calendar.

    REFRESH is per-event by necessity (each needs its own search), so it falls
    back to the single path. That is fine: refresh runs for one event entering
    its window, not for the whole year.
    """
    vocabulary = vocabulary or get_vocabulary()

    if phase is Phase.REFRESH:
        return _interpret_events_individually(
            events, store_context, today, conn, phase, models, vocabulary, progress
        )

    signals = []
    for start in range(0, len(events), batch_size):
        batch = events[start:start + batch_size]
        try:
            messages = [{"role": "user",
                         "content": _build_batch_prompt(batch, store_context, today)}]
            result = llm.structured(
                messages, SignalInterpretationBatchLLM,
                models=models or llm.REASONING_MODELS, max_tokens=2400,
            )
        except Exception as exc:
            log.warning("interpretation batch %d failed: %s", start, exc)
            continue

        if result.is_vacuous:
            log.warning("interpretation batch %d returned nothing usable", start)
            continue

        for index_str, item in result.signals.items():
            try:
                event = batch[int(index_str)]
            except (ValueError, IndexError):
                continue  # model invented an index
            signals.append(_to_signal(event, item, phase, vocabulary))

        if progress:
            progress(progress=min(start + batch_size, len(events)))

    return signals


def _interpret_events_individually(events, store_context, today, conn, phase,
                                   models, vocabulary, progress):
    signals = []
    for index, event in enumerate(events):
        try:
            signals.append(interpret(
                event.name, SignalType.EVENT, store_context,
                event_date=event.event_date,
                days_until=event.days_until(today),
                source=event.source, conn=conn, phase=phase,
                models=models, vocabulary=vocabulary,
            ))
        except Exception as exc:
            log.warning("could not interpret %r: %s", event.name, exc)
        if progress:
            progress(progress=index + 1)
    return signals


def _to_signal(event, result, phase, vocabulary):
    return Signal(
        signal_type=SignalType.EVENT,
        name=event.name,
        source=event.source,
        event_date=event.event_date,
        affected_occasions=result.affected_occasions,
        affected_categories=_canonical_categories(result.affected_categories, vocabulary),
        audience=result.audience,
        demand_lift=result.demand_lift,
        confidence=result.confidence,
        lead_time_days=result.lead_time_days,
        reasoning=result.reasoning,
        phase=phase,
        relevant=result.relevant,
    )


# --- persistence ----------------------------------------------------------

def save_signal(conn, signal, now=None):
    """Upsert a signal and replace its evidence.

    Evidence is deleted and rewritten rather than appended: a refresh supersedes
    what the previous pass read, and keeping both would show the seller stale
    citations alongside current ones with no way to tell them apart.
    """
    import json

    stamp = (now or datetime.now(timezone.utc)).isoformat()
    conn.execute(
        """
        INSERT INTO signals (
            signal_type, name, source, event_id, event_date,
            affected_occasions, affected_categories, audience,
            demand_lift, confidence, lead_time_days, reasoning,
            phase, relevant, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (signal_type, name, event_date) DO UPDATE SET
            source              = excluded.source,
            event_id            = excluded.event_id,
            affected_occasions  = excluded.affected_occasions,
            affected_categories = excluded.affected_categories,
            audience            = excluded.audience,
            demand_lift         = excluded.demand_lift,
            confidence          = excluded.confidence,
            lead_time_days      = excluded.lead_time_days,
            reasoning           = excluded.reasoning,
            phase               = excluded.phase,
            relevant            = excluded.relevant,
            updated_at          = excluded.updated_at
        """,
        (
            signal.signal_type.value, signal.name, signal.source, signal.event_id,
            signal.event_date.isoformat() if signal.event_date else None,
            json.dumps(signal.affected_occasions, ensure_ascii=False),
            json.dumps(signal.affected_categories, ensure_ascii=False),
            signal.audience,
            signal.demand_lift.value if signal.demand_lift else None,
            signal.confidence.value if signal.confidence else None,
            signal.lead_time_days, signal.reasoning,
            signal.phase.value, int(signal.relevant), stamp, stamp,
        ),
    )

    row = conn.execute(
        """SELECT id FROM signals
           WHERE signal_type = ? AND name = ? AND event_date IS ?""",
        (signal.signal_type.value, signal.name,
         signal.event_date.isoformat() if signal.event_date else None),
    ).fetchone()
    signal_id = row["id"]

    conn.execute("DELETE FROM evidence WHERE signal_id = ?", (signal_id,))
    for item in signal.evidence:
        conn.execute(
            """INSERT INTO evidence (signal_id, kind, url, title, snippet,
                                     retrieved_at, cache_key)
               VALUES (?,?,?,?,?,?,?)""",
            (signal_id, item.kind.value, item.url, item.title, item.snippet,
             item.retrieved_at.isoformat(), item.cache_key),
        )

    signal.id = signal_id
    return signal_id


def load_signals(conn, only_relevant=True, signal_type=None):
    import json

    from app.events.models import Evidence, EvidenceKind

    clauses, params = [], []
    if only_relevant:
        clauses.append("relevant = 1")
    if signal_type:
        clauses.append("signal_type = ?")
        params.append(signal_type.value if hasattr(signal_type, "value") else signal_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = conn.execute(
        f"SELECT * FROM signals {where} ORDER BY event_date IS NULL, event_date, id",
        params,
    ).fetchall()

    signals = []
    for row in rows:
        evidence = [
            Evidence(
                kind=EvidenceKind(e["kind"]), url=e["url"], title=e["title"],
                snippet=e["snippet"], retrieved_at=e["retrieved_at"],
                cache_key=e["cache_key"],
            )
            for e in conn.execute(
                "SELECT * FROM evidence WHERE signal_id = ? ORDER BY id", (row["id"],)
            ).fetchall()
        ]
        signals.append(Signal(
            id=row["id"],
            signal_type=SignalType(row["signal_type"]),
            name=row["name"], source=row["source"], event_id=row["event_id"],
            event_date=row["event_date"],
            affected_occasions=json.loads(row["affected_occasions"] or "[]"),
            affected_categories=json.loads(row["affected_categories"] or "[]"),
            audience=row["audience"],
            demand_lift=Level(row["demand_lift"]) if row["demand_lift"] else None,
            confidence=Level(row["confidence"]) if row["confidence"] else None,
            lead_time_days=row["lead_time_days"], reasoning=row["reasoning"],
            phase=Phase(row["phase"]), relevant=bool(row["relevant"]),
            evidence=evidence,
            created_at=row["created_at"], updated_at=row["updated_at"],
        ))
    return signals
