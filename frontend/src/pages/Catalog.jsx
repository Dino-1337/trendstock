import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Package, UploadCloud, PackageX, Sparkles } from 'lucide-react'
import PageHeader from '../components/layout/PageHeader'
import Card from '../components/primitives/Card'
import StatCard from '../components/primitives/StatCard'
import StatusPill from '../components/primitives/StatusPill'
import DataTable from '../components/primitives/DataTable'
import EmptyState from '../components/primitives/EmptyState'
import ProductThumb from '../components/primitives/ProductThumb'
import TagChips from '../components/primitives/TagChips'
import SearchInput from '../components/primitives/SearchInput'
import SkeletonCard, { SkeletonStatCard } from '../components/primitives/SkeletonCard'
import { useAppData } from '../context/AppDataContext'
import { retagCatalog } from '../lib/api'
import { downloadCsv } from '../lib/export'
import { formatDays, formatPrice } from '../lib/format'

const REC_TONE = {
  promote: 'bg-positive-bg text-positive',
  increase_stock: 'bg-pastel-blue text-pastel-blue-ink',
  reduce_reorder_risk: 'bg-negative-bg text-negative',
  discount: 'bg-pastel-yellow text-pastel-yellow-ink',
  none: 'bg-black/5 text-muted',
}

const REC_LABEL = {
  promote: 'Promote',
  increase_stock: 'Increase stock',
  reduce_reorder_risk: 'Reduce reorder risk',
  discount: 'Discount',
  none: 'No action',
}

export default function Catalog() {
  const { catalog } = useAppData()
  const { data, loading, error, reload } = catalog
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [retagging, setRetagging] = useState(false)
  const [retagResult, setRetagResult] = useState(null)

  const runRetag = async () => {
    setRetagging(true)
    setRetagResult(null)
    try {
      const result = await retagCatalog()
      setRetagResult(result)
      reload() // tags changed — refetch so the Category column reflects them
    } catch (err) {
      setRetagResult({ ok: false, error: err.message })
    } finally {
      setRetagging(false)
    }
  }

  const summary = data?.summary
  const summaryStats = summary
    ? [
        { key: 'total_products', label: 'Total Products', value: summary.total_products, delta_pct: null, direction: null },
        { key: 'matched', label: 'Catalog Matches', value: summary.matched, delta_pct: null, direction: null },
        { key: 'gaps', label: 'Trend Gaps', value: summary.gaps, delta_pct: null, direction: null },
        { key: 'at_risk', label: 'At Risk', value: summary.at_risk, delta_pct: null, direction: null },
      ]
    : []

  const noCatalog = !loading && !error && data && (!data.products || data.products.length === 0)

  const filteredProducts = useMemo(() => {
    if (!data?.products) return data?.products
    const q = query.trim().toLowerCase()
    if (!q) return data.products
    return data.products.filter((p) => p.title.toLowerCase().includes(q))
  }, [data, query])

  const exportRows = () =>
    downloadCsv('catalog.csv', filteredProducts ?? [], [
      { header: 'Product', key: 'title' },
      { header: 'Type', key: 'product_type' },
      { header: 'Price', key: 'price' },
      { header: 'Stock status', key: 'stock_status' },
      { header: 'Days remaining', key: 'days_stock_remaining' },
      { header: 'Category tags', key: (r) => (r.category_tags ?? []).join('; ') },
      { header: 'Tags (raw CSV)', key: (r) => (r.tags ?? []).join('; ') },
      { header: 'Matched trend', key: (r) => r.matched_trends?.[0]?.trend ?? '' },
      { header: 'Recommended action', key: (r) => r.recommendation?.action ?? '' },
    ])

  return (
    <div className="flex flex-col gap-5 pb-4 pt-4">
      <PageHeader
        title="Catalog"
        subtitle="Stock health and trend matches across your product catalog."
        primaryLabel="Refresh Catalog"
        onPrimary={reload}
        onExport={filteredProducts?.length ? exportRows : undefined}
        extra={
          data?.products?.length > 0 && (
            <button
              type="button"
              onClick={runRetag}
              disabled={retagging}
              title="Clear cached tags and run the AI tagger again"
              className="flex items-center gap-2 rounded-pill border border-hairline bg-card px-4 py-2.5 text-sm font-semibold text-ink hover:bg-cream disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Sparkles size={15} className={retagging ? 'animate-pulse' : undefined} />
              {retagging ? 'Tagging…' : 'Re-run AI tags'}
            </button>
          )
        }
      />

      {retagResult && (
        <Card className="h-auto">
          {retagResult.ok ? (
            <p className="text-sm text-ink">
              Tagged <span className="font-semibold">{retagResult.products_tagged}</span> products
              {retagResult.untagged > 0 && (
                <span className="text-muted"> · {retagResult.untagged} could not be tagged</span>
              )}
              <span className="text-muted">
                {' '}· via {Object.entries(retagResult.sources || {}).map(([s, n]) => `${s} (${n})`).join(', ') || 'n/a'}
              </span>
            </p>
          ) : (
            <p className="text-sm text-negative">{retagResult.error}</p>
          )}
        </Card>
      )}

      {error && (
        <Card className="h-[120px]">
          <EmptyState icon={PackageX} title="Couldn't load the catalog" description={error} />
        </Card>
      )}

      {loading && (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonStatCard key={i} />
            ))}
          </div>
          <SkeletonCard className="h-[520px]" />
          <SkeletonCard className="h-[320px]" />
        </>
      )}

      {noCatalog && (
        <Card className="h-[420px]">
          <EmptyState
            icon={UploadCloud}
            title="No catalog loaded yet"
            description="Upload a Shopify product CSV to start matching your catalog against trending demand."
            action={
              <button
                type="button"
                onClick={() => navigate('/upload')}
                className="mt-1 rounded-pill bg-cta px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90"
              >
                Go to Upload
              </button>
            }
          />
        </Card>
      )}

      {!loading && !error && !noCatalog && data && (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
            {summaryStats.map((stat, i) => (
              <StatCard key={stat.key} stat={stat} index={i} />
            ))}
          </div>

          <Card
            title="Catalog Match Detail"
            subtitle={`${filteredProducts?.length ?? 0} of ${data.products.length} products`}
            actions={<SearchInput value={query} onChange={setQuery} placeholder="Search products" />}
            className="h-[560px]"
          >
            <DataTable
              rowKey={(r) => r.product_id}
              columns={[
                {
                  key: 'title',
                  header: 'Product',
                  primary: true,
                  width: '24%',
                  render: (r) => (
                    <div className="flex min-w-0 items-center gap-3">
                      <ProductThumb src={r.image_src} name={r.title} />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-ink">{r.title}</p>
                        <p className="truncate text-xs text-muted">
                          {r.product_type} · {formatPrice(r.price)}
                        </p>
                        {r.tags?.length > 0 && (
                          <p className="truncate text-[11px] text-muted-2" title={`Raw Shopify tags: ${r.tags.join(', ')}`}>
                            from CSV: {r.tags.join(', ')}
                          </p>
                        )}
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'category_tags',
                  header: 'Category',
                  width: '14%',
                  render: (r) => <TagChips tags={r.category_tags} />,
                },
                {
                  key: 'stock_status',
                  header: 'Stock',
                  render: (r) => <StatusPill value={r.stock_status} />,
                },
                {
                  key: 'days_stock_remaining',
                  header: 'Days remaining',
                  render: (r) => (
                    <span className="text-sm font-medium text-ink">{formatDays(r.days_stock_remaining)}</span>
                  ),
                },
                {
                  key: 'matched_trends',
                  header: 'Matched trends',
                  width: '20%',
                  render: (r) => <MatchedTrendsCell trends={r.matched_trends} />,
                },
                {
                  key: 'recommendation',
                  header: 'Recommended action',
                  width: '20%',
                  render: (r) => <RecommendationCell rec={r.recommendation} />,
                },
              ]}
              rows={filteredProducts}
              emptyState={
                query.trim() ? (
                  <EmptyState
                    icon={Package}
                    title="No matching products"
                    description={`Nothing matches "${query}". Try a different search.`}
                  />
                ) : (
                  <EmptyState icon={Package} title="No products" description="No products in the catalog." />
                )
              }
            />
          </Card>

          <Card
            title="Trend Gaps"
            subtitle="Trending searches with no matching catalog product"
            className="h-[320px]"
          >
            <DataTable
              rowKey={(r) => r.trend}
              columns={[
                {
                  key: 'trend',
                  header: 'Trend',
                  primary: true,
                  render: (r) => <span className="text-sm font-semibold text-ink">{r.trend}</span>,
                },
                {
                  key: 'classification',
                  header: 'Classification',
                  render: (r) => <StatusPill value={r.classification} />,
                },
                {
                  key: 'category_tags',
                  header: 'Tagged as',
                  width: '18%',
                  render: (r) => <TagChips tags={r.category_tags} />,
                },
                {
                  key: 'reason',
                  header: 'Why it’s a gap',
                  width: '40%',
                  render: (r) => <span className="line-clamp-1 text-sm text-muted">{r.reason}</span>,
                },
              ]}
              rows={data.gaps}
              emptyState={
                <EmptyState
                  icon={Package}
                  title="No gaps"
                  description="Every tracked trend currently has at least one matching product."
                />
              }
            />
          </Card>
        </>
      )}
    </div>
  )
}

function MatchedTrendsCell({ trends }) {
  if (!trends || trends.length === 0) {
    return <span className="text-sm text-muted">No trend match</span>
  }
  const [first, ...rest] = trends
  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-center gap-1.5">
        <StatusPill value={first.classification} />
        <span className="truncate text-sm text-ink">{first.trend}</span>
      </div>
      {rest.length > 0 && <p className="mt-1 text-xs text-muted">+{rest.length} more</p>}
    </div>
  )
}

function RecommendationCell({ rec }) {
  if (!rec) return <span className="text-sm text-muted">—</span>
  return (
    <div className="min-w-0">
      <span
        className={`inline-flex w-fit rounded-full px-2.5 py-1 text-xs font-medium ${REC_TONE[rec.action] ?? 'bg-black/5 text-muted'}`}
      >
        {REC_LABEL[rec.action] ?? rec.action}
      </span>
      <p className="mt-1 line-clamp-1 text-xs text-muted" title={rec.reason}>
        {rec.reason}
      </p>
    </div>
  )
}
