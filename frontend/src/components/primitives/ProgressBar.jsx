import clsx from 'clsx'

// The one primitive the design system was missing. Enrichment runs one model
// call per batch of products, so it is the first operation in this app slow
// enough that a spinner alone reads as "hung" — the seller needs to see it
// moving and know which stage it is on.
//
// Follows the sidebar promo card's thin pink bar, the only bar precedent in
// the reference design: 6px track, pastel fill, fully rounded.
export default function ProgressBar({
  value = 0,
  max = 100,
  tone = 'purple',
  indeterminate = false,
  className,
  label,
}) {
  const safeMax = max > 0 ? max : 100
  const pct = Math.max(0, Math.min(100, (value / safeMax) * 100))

  const FILL = {
    purple: 'bg-pastel-purple-ink',
    pink: 'bg-pastel-pink-ink',
    blue: 'bg-pastel-blue-ink',
    yellow: 'bg-pastel-yellow-ink',
  }

  return (
    <div className={clsx('flex w-full flex-col gap-1.5', className)}>
      {label && (
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-ink">{label}</span>
          {!indeterminate && max > 0 && (
            // tabular-nums so the count does not jitter as digits change.
            <span className="text-muted tabular-nums">
              {value} / {max}
            </span>
          )}
        </div>
      )}
      <div
        className="h-1.5 w-full overflow-hidden rounded-pill bg-black/5"
        role="progressbar"
        aria-valuenow={indeterminate ? undefined : Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label || 'Progress'}
      >
        <div
          className={clsx(
            'h-full rounded-pill transition-all duration-500 ease-out',
            FILL[tone] ?? FILL.purple,
            // An indeterminate bar still has to show life while a stage runs
            // without a countable unit of work (profiling is one long call).
            indeterminate && 'animate-pulse',
          )}
          style={{ width: indeterminate ? '100%' : `${pct}%` }}
        />
      </div>
    </div>
  )
}
