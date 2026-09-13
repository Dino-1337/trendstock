import { Flame, ArrowUpRight, PackageX, ShieldCheck } from 'lucide-react'
import PageHeader from '../components/layout/PageHeader'
import Card from '../components/primitives/Card'
import StatCard from '../components/primitives/StatCard'
import StatusPill from '../components/primitives/StatusPill'
import DataTable from '../components/primitives/DataTable'
import EmptyState from '../components/primitives/EmptyState'
import MomentumChart from '../components/primitives/MomentumChart'
import InitialsTile from '../components/primitives/InitialsTile'
import SkeletonCard, { SkeletonStatCard } from '../components/primitives/SkeletonCard'
import { useApiData } from '../hooks/useApiData'
import { getDashboard } from '../lib/api'
import { downloadJson } from '../lib/export'
import { formatDays, formatNumber } from '../lib/format'

export default function Dashboard() {
  const { data, loading, error, reload } = useApiData(getDashboard, [])

  // dropped_trends_count is a quick sanity check that the relevance gate is
  // doing something (not nothing, not everything) — surfaced here rather
  // than as a 5th KPI card so the fixed 4-across stat row is untouched.
  //
  // Note: `trends_tracked` in `stats` reflects only trends that survived the
  // gate (it mirrors /api/trends' `trends.length`, live-verified against a
  // day where it dropped all 10 of 10 — trends_tracked read 0, not 10). So
  // "how many did we check" has to be reconstructed as tracked + dropped,
  // not read off trends_tracked alone.
  const droppedCount = data?.dropped_trends_count ?? 0
  const trendsTracked = data?.stats?.find((s) => s.key === 'trends_tracked')?.value ?? 0
  const totalChecked = trendsTracked + droppedCount

  return (
    <div className="flex flex-col gap-5 pb-4 pt-4">
      <PageHeader
        title="Dashboard"
        subtitle="Track trending demand and keep your catalog ahead of it."
        primaryLabel="Refresh"
        onPrimary={reload}
        onExport={data ? () => downloadJson(`dashboard-${data.generated_at.slice(0, 10)}.json`, data) : undefined}
        exportDisabled={loading}
      />

      {error && (
        <Card className="h-[120px]">
          <EmptyState
            icon={PackageX}
            title="Couldn't load the dashboard"
            description={error}
          />
        </Card>
      )}

      {/* KPI row: 4 across on desktop -> 2x2 on tablet -> stacked on mobile */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {loading
          ? Array.from({ length: 4 }).map((_, i) => <SkeletonStatCard key={i} />)
          : data?.stats?.map((stat, i) => <StatCard key={stat.key} stat={stat} index={i} />)}
      </div>

      {/* Chart + side panel: side by side on lg+, stacked below */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {loading ? (
          <>
            <SkeletonCard className="h-[420px] lg:col-span-2" />
            <SkeletonCard className="h-[420px]" />
          </>
        ) : (
          <>
            <Card
              title="Trend Momentum Flow"
              subtitle="Spiking vs. rising trend counts over time"
              className="h-[420px] lg:col-span-2"
            >
              <MomentumChart chart={data?.momentum_chart} />
            </Card>

            <Card
              title="Top Spiking Trends"
              subtitle={
                droppedCount
                  ? `${droppedCount} trend${droppedCount === 1 ? '' : 's'} filtered out as not commerce-relevant today`
                  : undefined
              }
              className="h-[420px]"
              bodyClassName="flex flex-col"
            >
              {data?.top_trends?.length ? (
                <>
                  <div className="flex-1 overflow-y-auto pr-1">
                    <ul className="flex flex-col gap-2.5">
                      {data.top_trends.map((t, i) => (
                        <TrendRow key={t.id} trend={t} rank={i + 1} />
                      ))}
                    </ul>
                  </div>
                  <a
                    href="/trends"
                    className="mt-3 flex shrink-0 items-center justify-center gap-1.5 rounded-pill border border-hairline py-2.5 text-sm font-semibold text-ink hover:bg-cream"
                  >
                    See All
                    <ArrowUpRight size={15} />
                  </a>
                </>
              ) : droppedCount ? (
                <>
                  <div className="flex-1">
                    <EmptyState
                      icon={ShieldCheck}
                      title="No commerce-relevant trends today"
                      description={`${totalChecked} trend${totalChecked === 1 ? '' : 's'} checked, ${droppedCount} filtered out as not commerce-relevant (cricket, politics, regional news, and similar). The gate ran and made a call — it's not a data outage.`}
                    />
                  </div>
                  <a
                    href="/trends"
                    className="mt-3 flex shrink-0 items-center justify-center gap-1.5 rounded-pill border border-hairline py-2.5 text-sm font-semibold text-ink hover:bg-cream"
                  >
                    See why on Trends
                    <ArrowUpRight size={15} />
                  </a>
                </>
              ) : (
                <EmptyState
                  icon={Flame}
                  title="No trends yet"
                  description="Once the pipeline collects its first snapshot, spiking trends will show up here."
                />
              )}
            </Card>
          </>
        )}
      </div>

      {/* Products at risk table */}
      {loading ? (
        <SkeletonCard className="h-[440px]" />
      ) : (
        <Card title="Products at Risk" subtitle="Lowest days-of-stock remaining" className="h-[440px]">
          <DataTable
            rowKey={(r) => r.product_id}
            columns={[
              {
                key: 'title',
                header: 'Product',
                primary: true,
                width: '40%',
                render: (r) => (
                  <div className="flex min-w-0 items-center gap-3">
                    <InitialsTile name={r.title} />
                    <span className="truncate text-sm font-semibold text-ink">{r.title}</span>
                  </div>
                ),
              },
              {
                key: 'stock_status',
                header: 'Stock status',
                render: (r) => <StatusPill value={r.stock_status} />,
              },
              {
                key: 'days_stock_remaining',
                header: 'Days remaining',
                align: 'right',
                render: (r) => (
                  <span className="font-medium text-ink">{formatDays(r.days_stock_remaining)}</span>
                ),
              },
            ]}
            rows={data?.at_risk_products}
            emptyState={
              <EmptyState
                icon={PackageX}
                title="Nothing at risk right now"
                description="No products are projected to run out soon."
              />
            }
          />
        </Card>
      )}
    </div>
  )
}

function TrendRow({ trend, rank }) {
  const PILL_TONE = {
    spiking: 'bg-pastel-pink text-pastel-pink-ink',
    rising: 'bg-pastel-purple text-pastel-purple-ink',
    steady: 'bg-pastel-blue text-pastel-blue-ink',
    falling: 'bg-pastel-yellow text-pastel-yellow-ink',
    new: 'bg-black/5 text-muted',
  }
  const tone = PILL_TONE[trend.classification] ?? 'bg-black/5 text-muted'

  return (
    <li className="flex items-center gap-3">
      <span className="w-6 shrink-0 text-center text-xs font-semibold text-muted-2">
        {String(rank).padStart(2, '0')}
      </span>
      <div className={`flex min-w-0 flex-1 items-center justify-between gap-2 rounded-pill px-3.5 py-2.5 ${tone}`}>
        <span className="min-w-0 truncate text-sm font-semibold">{trend.trend}</span>
        <span className="shrink-0 text-xs font-medium opacity-80">
          {formatNumber(trend.traffic_min)}+
        </span>
      </div>
    </li>
  )
}
