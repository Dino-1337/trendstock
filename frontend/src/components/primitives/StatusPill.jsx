import clsx from 'clsx'

// Maps every classification / stock-status keyword the API can produce to a
// pastel pill style. Anything unrecognised (defensive — the API contract is
// the source of truth) falls back to the neutral gray style rather than
// throwing, so a new backend value never breaks the page.
const STYLES = {
  // trend classification
  spiking: 'bg-pastel-pink text-pastel-pink-ink',
  rising: 'bg-pastel-purple text-pastel-purple-ink',
  steady: 'bg-pastel-blue text-pastel-blue-ink',
  falling: 'bg-pastel-yellow text-pastel-yellow-ink',
  new: 'bg-black/5 text-muted',
  // stock status
  ok: 'bg-pastel-blue text-pastel-blue-ink',
  low: 'bg-pastel-yellow text-pastel-yellow-ink',
  critical: 'bg-negative-bg text-negative',
}

const LABELS = {
  spiking: 'Spiking',
  rising: 'Rising',
  steady: 'Steady',
  falling: 'Falling',
  new: 'New',
  ok: 'In stock',
  low: 'Low stock',
  critical: 'Critical',
}

// Same pastel-pill visual language, keyed by an explicit color name instead
// of a known classification/status value. Lets callers (e.g. TagChips) pill
// arbitrary controlled-vocabulary text — like category_tags — without a
// second pill component existing in the app.
const TONE_STYLES = {
  pink: 'bg-pastel-pink text-pastel-pink-ink',
  purple: 'bg-pastel-purple text-pastel-purple-ink',
  yellow: 'bg-pastel-yellow text-pastel-yellow-ink',
  blue: 'bg-pastel-blue text-pastel-blue-ink',
  // A deliberately non-signalling chip — used for category tags, which sit
  // in the same row as stock-status and trend-classification pills. Those
  // already claim pink/purple/yellow/blue as meaningful; reusing any of
  // them for a plain category label would make it look like a status.
  neutral: 'bg-black/5 text-ink',
}

export default function StatusPill({ value, tone, label, className }) {
  const text = label ?? (value ? (LABELS[value] ?? value) : null)

  if (!text) {
    return (
      <span className={clsx('inline-flex items-center rounded-full bg-black/5 px-2.5 py-1 text-xs font-medium text-muted', className)}>
        —
      </span>
    )
  }
  const style = tone ? (TONE_STYLES[tone] ?? 'bg-black/5 text-muted') : (STYLES[value] ?? 'bg-black/5 text-muted')
  return (
    <span
      className={clsx(
        'inline-flex w-fit items-center whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium',
        style,
        className,
      )}
    >
      {text}
    </span>
  )
}
