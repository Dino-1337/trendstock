import clsx from 'clsx'
import { Check, Loader2, Sparkles } from 'lucide-react'
import ProgressBar from './ProgressBar'

// The stages the backend reports, in order. Kept here (not derived from the
// response) so the seller can see what is coming as well as what is done —
// a list that grows one row at a time reads as stalling.
const STAGES = [
  { key: 'reading', label: 'Reading your catalog' },
  { key: 'profiling', label: 'Understanding your store' },
  { key: 'enriching', label: 'Tagging products by occasion' },
  { key: 'complete', label: 'Ready' },
]

function stageIndex(stage) {
  const i = STAGES.findIndex((s) => s.key === stage)
  return i === -1 ? 0 : i
}

/**
 * Live progress for the enrichment job.
 *
 * Only the `enriching` stage has a countable unit of work; profiling is one
 * long model call, so its bar runs indeterminate rather than faking a
 * percentage that would stall at the same number every time.
 */
export default function AnalysisProgress({ job, className }) {
  const stage = job?.stage || 'reading'
  const current = stageIndex(stage)
  const total = job?.total ?? 0
  const progress = job?.progress ?? 0
  const countable = stage === 'enriching' && total > 0

  return (
    <div className={clsx('flex flex-col gap-4', className)}>
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-pastel-purple text-pastel-purple-ink">
          <Sparkles size={19} strokeWidth={2} className="animate-pulse" />
        </span>
        <div className="min-w-0">
          <p className="text-base font-semibold text-ink">Analysing your catalog</p>
          <p className="truncate text-sm text-muted">
            {job?.message || 'Starting…'}
          </p>
        </div>
      </div>

      <ProgressBar
        value={countable ? progress : 0}
        max={countable ? total : 100}
        indeterminate={!countable}
        label={countable ? 'Products tagged' : null}
      />

      <ol className="flex flex-col gap-1.5">
        {STAGES.map((s, index) => {
          const done = index < current
          const active = index === current
          return (
            <li
              key={s.key}
              className={clsx(
                'flex items-center gap-2.5 rounded-chip px-3 py-2 text-sm transition-colors',
                active && 'bg-pastel-purple/25 font-medium text-ink',
                done && 'text-muted',
                !active && !done && 'text-muted-2',
              )}
            >
              <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                {done ? (
                  <Check size={14} strokeWidth={2.5} className="text-positive" />
                ) : active ? (
                  <Loader2 size={14} className="animate-spin text-pastel-purple-ink" />
                ) : (
                  <span className="h-1.5 w-1.5 rounded-full bg-current opacity-40" />
                )}
              </span>
              {s.label}
            </li>
          )
        })}
      </ol>

      <p className="text-xs text-muted-2">
        This reads every product once and remembers the result — re-running
        later is instant unless your catalog changes.
      </p>
    </div>
  )
}
