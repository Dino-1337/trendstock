import { useNavigate } from 'react-router-dom'
import { ArrowUpRight, CalendarClock, PackageX, UploadCloud } from 'lucide-react'
import PageHeader from '../components/layout/PageHeader'
import Card from '../components/primitives/Card'
import DataTable from '../components/primitives/DataTable'
import EmptyState from '../components/primitives/EmptyState'
import StatusPill from '../components/primitives/StatusPill'
import SkeletonCard, { SkeletonStatCard } from '../components/primitives/SkeletonCard'
import { useApiData } from '../hooks/useApiData'
import { getDashboard } from '../lib/api'
import { formatDays } from '../lib/format'

// Deliberately not a KPI grid. An operational/decision-support dashboard's
// job is "what do I act on this week" in a few seconds - the exhaustive lists
// (every signal, every product) live one click away on Alerts and Catalog.

function whenLabel(days) {
  if (days === null || days === undefined) return 'Ongoing'
  if (days < 0) return `Started ${Math.abs(days)}d ago`
  if (days === 0) return 'Today'
  return `In ${days}d`
}

const LIFT_TONE = {
  high: 'bg-pastel-pink text-pastel-pink-ink',
  medium: 'bg-pastel-yellow text-pastel-yellow-ink',
  low: 'bg-black/5 text-muted',
}

export default function Dashboard() {
  const { data, loading, error, reload } = useApiData(getDashboard, [])
  const navigate = useNavigate()

  const stats = data?.stats
  const nextEvent = data?.next_events?.[0]

  const warningColumns = [
    {
      key: 'title',
      header: 'Product',
      width: '38%',
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
      width: '20%',
      render: (row) => (
        <StatusPill
          value={row.days_stock_remaining <= 3 ? 'critical' : 'low'}
          label={formatDays(row.days_stock_remaining)}
        />
      ),
    },
    {
      key: 'signal_name',
      header: 'Driven by',
      width: '42%',
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate text-sm text-ink">{row.signal_name}</p>
          <p className="text-xs text-muted">{whenLabel(row.days_until)}</p>
        </div>
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-5 pb-4 pt-4">
      <PageHeader
        title="Dashboard"
        subtitle="What to act on this week."
        primaryLabel="Refresh"
        onPrimary={reload}
      />

      {loading && (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            <SkeletonStatCard />
            <SkeletonStatCard />
            <SkeletonStatCard />
          </div>
          <SkeletonCard className="h-[360px]" />
        </>
      )}

      {!loading && error && (
        <Card className="h-[160px]">
          <EmptyState icon={PackageX} title="Couldn't load the dashboard" description={error} />
        </Card>
      )}

      {!loading && !error && data && !data.ready && (
        <Card className="h-auto min-h-[320px]">
          <EmptyState
            icon={UploadCloud}
            title="Nothing to show yet"
            description={data.reason}
            action={
              <button
                type="button"
                onClick={() => navigate('/catalog')}
                className="rounded-pill bg-cta px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
              >
                Go to Catalog
              </button>
            }
          />
        </Card>
      )}

      {!loading && !error && data?.ready && (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            <div className="card-shadow flex h-[132px] flex-col justify-between rounded-card bg-card p-5">
              <p className="text-sm text-muted">Stock warnings</p>
              <p className="text-4xl font-bold tabular-nums text-ink">{stats.warnings_total}</p>
            </div>
            <div className="card-shadow flex h-[132px] flex-col justify-between rounded-card bg-card p-5">
              <p className="text-sm text-muted">Needing action now</p>
              <p className="text-4xl font-bold tabular-nums text-ink">{stats.signals_in_window}</p>
            </div>
            <div className="card-shadow flex h-[132px] flex-col justify-between rounded-card bg-card p-5">
              <p className="text-sm text-muted">Catalog analysed</p>
              <p className="text-4xl font-bold tabular-nums text-ink">
                {stats.enriched_products}/{stats.total_products}
              </p>
              {nextEvent && (
                <p className="truncate text-xs text-muted">
                  Next: {nextEvent.name} · {whenLabel(nextEvent.days_until)}
                </p>
              )}
            </div>
          </div>

          <Card
            title="Restock before these run out"
            subtitle={
              data.top_warnings.length
                ? `Top ${data.top_warnings.length} by urgency`
                : undefined
            }
            className="h-[360px]"
          >
            <DataTable
              columns={warningColumns}
              rows={data.top_warnings}
              rowKey={(row) => row.product_id}
              onRowClick={(row) => navigate(`/catalog/${encodeURIComponent(row.product_id)}`)}
              emptyState={
                <EmptyState
                  icon={PackageX}
                  title="Nothing at risk"
                  description="No product with rising demand is close to running out."
                />
              }
            />
          </Card>

          <Card title="What's coming" className="h-auto min-h-[240px]">
            {data.next_events.length === 0 ? (
              <EmptyState
                icon={CalendarClock}
                title="No upcoming events"
                description="Nothing relevant to your store is coming up right now."
              />
            ) : (
              <div className="flex flex-col">
                {data.next_events.map((event) => (
                  <div
                    key={event.name}
                    className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline py-3 last:border-0"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-ink">{event.name}</span>
                      <StatusPill
                        tone={event.days_until < 0 ? 'pink' : 'purple'}
                        label={whenLabel(event.days_until)}
                      />
                      {event.demand_lift && (
                        <span
                          className={`inline-flex w-fit items-center whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${
                            LIFT_TONE[event.demand_lift] ?? 'bg-black/5 text-muted'
                          }`}
                        >
                          {event.demand_lift} lift
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-muted">{event.matched_count} products</span>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => navigate('/alerts')}
                  className="mt-3 flex shrink-0 items-center justify-center gap-1.5 rounded-pill border border-hairline py-2.5 text-sm font-semibold text-ink hover:bg-cream"
                >
                  See all alerts
                  <ArrowUpRight size={15} />
                </button>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
