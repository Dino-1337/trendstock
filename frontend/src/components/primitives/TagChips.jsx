import clsx from 'clsx'
import StatusPill from './StatusPill'

// Controlled-vocabulary category_tags, rendered with StatusPill's existing
// pill shape but a single neutral tone — these sit in the same row as
// stock-status and trend-classification pills, which already own
// pink/purple/yellow/blue as *meaningful* colors, so category chips
// deliberately don't compete for any of them. Tag lists vary in length, so
// only `max` chips render and the rest collapse into a "+N" — the row never
// grows to fit a long tag list (fixed-card-size rule).
const TAG_SOURCE_LABEL = {
  rule_based: 'Rule-based',
  llm_groq: 'Groq',
}

const TAG_SOURCE_TITLE = {
  rule_based: 'Tagged by the deterministic rule-based tagger',
  llm_groq: 'Tagged by the Groq LLM tagger (falls back to rule-based on failure)',
}

export default function TagChips({ tags, sourceLabel, max = 2, className }) {
  if (!tags || tags.length === 0) {
    return <span className="text-sm text-muted">—</span>
  }

  const visible = tags.slice(0, max)
  const remaining = tags.length - visible.length

  return (
    <div className={clsx('min-w-0', className)}>
      <div className="flex flex-wrap items-center gap-1" title={tags.join(', ')}>
        {visible.map((tag) => (
          <StatusPill key={tag} tone="neutral" label={tag} />
        ))}
        {remaining > 0 && (
          <span className="shrink-0 text-xs font-medium text-muted">+{remaining}</span>
        )}
      </div>
      {sourceLabel && (
        <p
          className="mt-1 truncate text-[10px] font-medium uppercase tracking-wide text-muted-2"
          title={TAG_SOURCE_TITLE[sourceLabel] ?? sourceLabel}
        >
          {TAG_SOURCE_LABEL[sourceLabel] ?? sourceLabel}
        </p>
      )}
    </div>
  )
}
