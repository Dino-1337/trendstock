import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CalendarClock, ExternalLink, PackageX, Sparkles } from 'lucide-react'
import PageHeader from '../components/layout/PageHeader'
import Card from '../components/primitives/Card'
import DataTable from '../components/primitives/DataTable'
import EmptyState from '../components/primitives/EmptyState'
import SkeletonCard, { SkeletonStatCard } from '../components/primitives/SkeletonCard'
import StatusPill from '../components/primitives/StatusPill'
import { useApiData } from '../hooks/useApiData'
import { getAlerts } from '../lib/api'
import { formatDays } from '../lib/format'

const LIFT_TONE = {
  high: 'bg-pastel-pink text-pastel-pink-ink',
  medium: 'bg-pastel-yellow text-pastel-yellow-ink',
  low: 'bg-black/5 text-muted',
}

// A season already underway reads differently from one approaching, and the
// difference is actionable — "started 29 days ago" means stock now, not soon.
function whenLabel(days) {
  if (days === null || days === undefined) return 'Ongoing'
  if (days < 0) return `Started ${Math.abs(days)}d ago`
  if (days === 0) return 'Today'
  return `In ${days}d`
}

function SignalRow({ signal }) {
  const isSeason = signal.source === 'curated_seasons'
  const active = signal.days_until !== null && signal.days_until < 0

  return (
    <div className="flex flex-col gap-2 border-b border-hairline py-3.5 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-ink">{signal.name}</span>
        <StatusPill
          tone={active ? 'pink' : isSeason ? 'blue' : 'purple'}
          label={whenLabel(signal.days_until)}
        />
        {signal.demand_lift && (
          <span
            className={`inline-flex w-fit items-center whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${
              LIFT_TONE[signal.demand_lift] ?? 'bg-black/5 text-muted'
            }`}
          >
            {signal.demand_lift} lift
          </span>
        )}
        {signal.in_window && <StatusPill tone="yellow" label="Act now" />}
      </div>

      {signal.reasoning && (
        <p className="max-w-[80ch] text-sm text-muted">{signal.reasoning}</p>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span>
          <span className="font-medium text-ink">{signal.matched_count}</span> product
          {signal.matched_count === 1 ? '' : 's'} affected
        </span>
        {signal.occasions?.length > 0 && <span>{signal.occasions.join(' · ')}</span>}
        {signal.lead_time_days != null && <span>{signal.lead_time_days}d lead time</span>}
        {/* Provenance: what the research pass actually read, so a claim can be
            checked rather than taken on trust. */}
        {signal.sources?.slice(0, 2).map((s) => (
          <a
            key={s.url}
            href={s.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-pastel-purple-ink hover:underline"
          >
            <ExternalLink size={11} />
            {(s.title || 'source').slice(0, 34)}
          </a>
        ))}
      </div>
    </div>
  )
}

export default function Alerts() {
  const { data, loading, error, reload } = useApiData(getAlerts, [])
  const navigate = useNavigate()

  const summary = data?.summary
  const stats = useMemo(() => {
    if (!summary) return []
    return [
      {
        key: 'warnings',
        label: 'Stock warnings',
        value: summary.warnings ?? 0,
        delta_pct: null,
        direction: null,
      },
      {
        key: 'in_window',
        label: 'Needing action now',
        value: summary.in_window ?? 0,
        delta_pct: null,
        direction: null,
      },
      {
        key: 'total_signals',
        label: 'Upcoming events',
        value: summary.total_signals ?? 0,
        delta_pct: null,
        direction: null,
      },
    ]
  }, [summary])

  const warningColumns = [
    {
      key: 'title',
      header: 'Product',
      width: '30%',
      primary: true,
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{row.title}</p>
          <p className="truncate text-xs text-muted">{row.reasons?.[0]}</p>
        </div>
      ),
    },
    {
      key: 'days_stock_remaining',
      header: 'Cover left',
      width: '16%',
      render: (row) => (
        <div className="flex flex-col gap-1">
          <StatusPill
            value={row.days_stock_remaining <= 3 ? 'critical' : 'low'}
            label={formatDays(row.days_stock_remaining)}
          />
          <span className="text-xs text-muted tabular-nums">{row.current_stock} in stock</span>
        </div>
      ),
    },
    {
      key: 'signal_name',
      header: 'Driven by',
      width: '30%',
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate text-sm text-ink">{row.signal_name}</p>
          <p className="text-xs text-muted">
            {whenLabel(row.days_until)}
            {row.demand_lift ? ` · ${row.demand_lift} lift` : ''}
          </p>
        </div>
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-5 pb-4 pt-4">
      <PageHeader
        title="Alerts"
        subtitle="What's coming, and what you're about to run out of because of it."
      />

      {loading && (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            <SkeletonStatCard />
            <SkeletonStatCard />
            <SkeletonStatCard />
          </div>
          <SkeletonCard className="h-[420px]" />
        </>
      )}

      {!loading && error && (
        <Card className="h-auto">
          <EmptyState
            icon={AlertTriangle}
            title="Couldn't load alerts"
            description={error}
            action={
              <button
                type="button"
                onClick={reload}
                className="rounded-pill bg-cta px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
              >
                Try again
              </button>
            }
          />
        </Card>
      )}

      {!loading && !error && data && !data.ready && (
        <Card className="h-auto min-h-[320px]">
          <EmptyState
            icon={Sparkles}
            title="Nothing to show yet"
            description={data.reason}
            action={
              <button
                type="button"
                onClick={() => navigate('/analysis')}
                className="rounded-pill bg-cta px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
              >
                Go to Analysis
              </button>
            }
          />
        </Card>
      )}

      {!loading && !error && data?.ready && (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            {stats.map((stat, index) => (
              <div key={stat.key} className="card-shadow flex h-[132px] flex-col justify-between rounded-card bg-card p-5">
                <p className="text-sm text-muted">{stat.label}</p>
                <p className="text-4xl font-bold tabular-nums text-ink">{stat.value}</p>
                {index === 0 && summary?.next_event && (
                  <p className="truncate text-xs text-muted">
                    Next: {summary.next_event}
                    {summary.next_event_days != null && ` · ${whenLabel(summary.next_event_days)}`}
                  </p>
                )}
              </div>
            ))}
          </div>

          <Card
            title="Restock before these run out"
            subtitle={
              data.warnings.length
                ? `${data.warnings.length} product${data.warnings.length === 1 ? '' : 's'} with low cover and rising demand`
                : undefined
            }
            className="h-[440px]"
          >
            <DataTable
              columns={warningColumns}
              rows={data.warnings}
              rowKey={(row) => row.product_id}
              emptyState={
                <EmptyState
                  icon={PackageX}
                  title="Nothing at risk"
                  description="No product with rising demand is close to running out."
                />
              }
            />
          </Card>

          <Card
            title="What's coming"
            subtitle={`${data.signals.length} events and seasons relevant to your store`}
            className="h-[560px]"
            bodyClassName="overflow-y-auto pr-1"
          >
            {data.signals.length === 0 ? (
              <EmptyState
                icon={CalendarClock}
                title="No relevant events"
                description="Nothing on the calendar looks likely to move demand for what you sell."
              />
            ) : (
              <div className="flex flex-col">
                {data.signals.map((signal) => (
                  <SignalRow key={`${signal.name}-${signal.event_date}`} signal={signal} />
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
