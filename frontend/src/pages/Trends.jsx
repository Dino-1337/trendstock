import { useMemo, useState } from 'react'
import { TrendingUp, Newspaper, ShieldCheck, FilterX } from 'lucide-react'
import PageHeader from '../components/layout/PageHeader'
import Card from '../components/primitives/Card'
import DataTable from '../components/primitives/DataTable'
import StatusPill from '../components/primitives/StatusPill'
import TagChips from '../components/primitives/TagChips'
import EmptyState from '../components/primitives/EmptyState'
import SearchInput from '../components/primitives/SearchInput'
import SkeletonCard from '../components/primitives/SkeletonCard'
import { useAppData } from '../context/AppDataContext'
import { downloadCsv } from '../lib/export'
import { formatNumber, formatPercent } from '../lib/format'

export default function Trends() {
  const { trends } = useAppData()
  const { data, loading, error, reload } = trends
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    if (!data?.trends) return data?.trends
    const q = query.trim().toLowerCase()
    if (!q) return data.trends
    return data.trends.filter((t) => t.trend.toLowerCase().includes(q))
  }, [data, query])

  // Every trend that reaches /api/trends already passed the relevance gate —
  // on a real feed day it's common for *all* of them to get filtered out
  // (cricket, politics, regional news). That's the gate working, not the
  // pipeline being down, so the empty state and header both need to say so
  // explicitly rather than reading as "no data".
  const droppedCount = data?.dropped_trends?.count ?? 0
  const keptCount = data?.trends?.length ?? 0
  const totalChecked = keptCount + droppedCount
  const allFilteredOut = Boolean(data) && keptCount === 0 && droppedCount > 0

  const subtitle = data
    ? `${data.geo} · ${data.snapshot_count} snapshot${data.snapshot_count === 1 ? '' : 's'} collected${
        droppedCount > 0
          ? ` · ${droppedCount} of ${totalChecked} filtered out as not commerce-relevant`
          : ''
      }`
    : 'Ranked by traffic and momentum'

  const exportRows = () =>
    downloadCsv('trends.csv', filtered ?? [], [
      { header: 'Trend', key: 'trend' },
      { header: 'Traffic', key: 'traffic_label' },
      { header: 'Classification', key: 'classification' },
      { header: 'Momentum %', key: (r) => r.momentum_pct ?? '' },
      { header: 'Matched products', key: 'matched_product_count' },
      { header: 'Category tags', key: (r) => (r.category_tags ?? []).join('; ') },
      { header: 'Tag source', key: 'tag_source' },
      { header: 'Top headline', key: (r) => r.why?.[0]?.headline ?? '' },
      { header: 'Source', key: (r) => r.why?.[0]?.source ?? '' },
    ])

  return (
    <div className="flex flex-col gap-5 pb-4 pt-4">
      <PageHeader
        title="Trends"
        subtitle={subtitle}
        primaryLabel="Refresh Trends"
        onPrimary={reload}
        onExport={filtered?.length ? exportRows : undefined}
      />

      {error && (
        <Card className="h-[120px]">
          <EmptyState icon={TrendingUp} title="Couldn't load trends" description={error} />
        </Card>
      )}

      {loading ? (
        <SkeletonCard className="h-[640px]" />
      ) : (
        <Card
          title="Ranked Trends"
          subtitle="Traffic, classification, momentum and why each is trending"
          actions={<SearchInput value={query} onChange={setQuery} placeholder="Search trends" />}
          className="h-[640px]"
        >
          <DataTable
            rowKey={(r) => r.id}
            columns={[
              {
                key: 'trend',
                header: 'Trend',
                primary: true,
                width: '22%',
                render: (r) => (
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-ink">{r.trend}</p>
                    <p className="truncate text-xs text-muted">{r.traffic_label} searches</p>
                  </div>
                ),
              },
              {
                key: 'classification',
                header: 'Classification',
                render: (r) => <StatusPill value={r.classification} />,
              },
              {
                key: 'momentum_pct',
                header: 'Momentum',
                render: (r) => <MomentumCell value={r.momentum_pct} isNew={r.classification === 'new'} />,
              },
              {
                key: 'category_tags',
                header: 'Category',
                width: '16%',
                render: (r) => <TagChips tags={r.category_tags} sourceLabel={r.tag_source} />,
              },
              {
                key: 'matched_product_count',
                header: 'Matched products',
                align: 'right',
                render: (r) => (
                  <span className="font-medium text-ink">{formatNumber(r.matched_product_count)}</span>
                ),
              },
              {
                key: 'why',
                header: 'Why it’s trending',
                width: '26%',
                render: (r) => <WhyCell why={r.why} />,
              },
            ]}
            rows={filtered}
            emptyState={
              query.trim() ? (
                <EmptyState
                  icon={TrendingUp}
                  title="No matching trends"
                  description={`Nothing matches "${query}". Try a different search.`}
                />
              ) : allFilteredOut ? (
                <EmptyState
                  icon={ShieldCheck}
                  title="None of today's trends were commerce-relevant"
                  description={`${totalChecked} trend${totalChecked === 1 ? '' : 's'} checked, 0 passed the relevance gate. That's expected on a feed dominated by cricket, politics, or regional news — see "Filtered Out" below for the exact reason each one was dropped.`}
                />
              ) : (
                <EmptyState
                  icon={TrendingUp}
                  title="No trend data yet"
                  description="The pipeline hasn't produced a snapshot yet. Check back after the next run."
                />
              )
            }
          />
        </Card>
      )}

      {!loading && data?.dropped_trends && (
        <Card
          title="Filtered Out"
          subtitle={
            droppedCount > 0
              ? `${droppedCount} of ${totalChecked} trends didn't pass the relevance gate — kept here for audit, not shown above`
              : 'Nothing filtered out this snapshot'
          }
          className="h-[300px]"
        >
          <DataTable
            rowKey={(r) => r.trend}
            columns={[
              {
                key: 'trend',
                header: 'Trend',
                primary: true,
                width: '30%',
                render: (r) => <span className="text-sm font-semibold text-ink">{r.trend}</span>,
              },
              {
                key: 'reason',
                header: 'Why it was dropped',
                noTruncateMobile: true,
                render: (r) => (
                  <span className="text-sm text-muted" title={r.reason}>
                    {r.reason}
                  </span>
                ),
              },
            ]}
            rows={data.dropped_trends.trends}
            emptyState={
              <EmptyState
                icon={FilterX}
                title="Nothing filtered out"
                description="Every trend in this snapshot passed the relevance gate."
              />
            }
          />
        </Card>
      )}
    </div>
  )
}

function MomentumCell({ value, isNew }) {
  if (value === null || value === undefined) {
    return (
      <span className="text-sm text-muted">{isNew ? 'New — no history yet' : '—'}</span>
    )
  }
  const positive = value > 0
  return (
    <span className={`text-sm font-semibold ${positive ? 'text-positive' : 'text-negative'}`}>
      {formatPercent(value)}
    </span>
  )
}

function WhyCell({ why }) {
  if (!why || why.length === 0) {
    return <span className="text-sm text-muted">—</span>
  }
  const [first, ...rest] = why
  return (
    <div className="flex min-w-0 items-start gap-2">
      <Newspaper size={14} className="mt-0.5 shrink-0 text-muted-2" />
      <div className="min-w-0">
        <p className="line-clamp-2 text-sm text-ink" title={first.headline}>
          {first.headline}
        </p>
        <p className="mt-0.5 truncate text-xs text-muted">
          {first.source}
          {rest.length > 0 && ` · +${rest.length} more`}
        </p>
      </div>
    </div>
  )
}
