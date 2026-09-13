import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Sparkles, UploadCloud, Store } from 'lucide-react'
import PageHeader from '../components/layout/PageHeader'
import AnalysisProgress from '../components/primitives/AnalysisProgress'
import Card from '../components/primitives/Card'
import DataTable from '../components/primitives/DataTable'
import EmptyState from '../components/primitives/EmptyState'
import ProductThumb from '../components/primitives/ProductThumb'
import SearchInput from '../components/primitives/SearchInput'
import SkeletonCard from '../components/primitives/SkeletonCard'
import StatusPill from '../components/primitives/StatusPill'
import { useAppData } from '../context/AppDataContext'
import useEnrichmentJob from '../hooks/useEnrichmentJob'
import { downloadCsv } from '../lib/export'
import { formatDays, formatPrice } from '../lib/format'

// Occasions are the join key between a seasonal signal and a product, so they
// get their own colour per value rather than one flat chip — the seller scans
// this column looking for "what's festive", not for a list of words.
const OCCASION_TONE = {
  festive: 'bg-pastel-pink text-pastel-pink-ink',
  wedding: 'bg-pastel-purple text-pastel-purple-ink',
  bridal: 'bg-pastel-purple text-pastel-purple-ink',
  gifting: 'bg-pastel-yellow text-pastel-yellow-ink',
  party: 'bg-pastel-pink text-pastel-pink-ink',
  religious: 'bg-pastel-purple text-pastel-purple-ink',
  casual: 'bg-black/5 text-muted',
  work_formal: 'bg-pastel-blue text-pastel-blue-ink',
  sport_active: 'bg-pastel-blue text-pastel-blue-ink',
  travel: 'bg-pastel-blue text-pastel-blue-ink',
  summer: 'bg-pastel-yellow text-pastel-yellow-ink',
  winter: 'bg-pastel-blue text-pastel-blue-ink',
  monsoon: 'bg-pastel-blue text-pastel-blue-ink',
}

const OCCASION_LABEL = {
  work_formal: 'work',
  sport_active: 'active',
}

function OccasionChips({ values }) {
  // null means "not analysed yet", [] means "analysed, nothing applied". The
  // old tagger collapsed those into the same empty list, which hid the
  // difference between a broken pipeline and an honest result.
  if (values === null || values === undefined) {
    return <span className="text-xs text-muted-2">Not analysed</span>
  }
  if (values.length === 0) {
    return <span className="text-xs text-muted-2">None</span>
  }
  return (
    <div className="flex flex-wrap gap-1">
      {values.map((v) => (
        <span
          key={v}
          className={`inline-flex w-fit items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${
            OCCASION_TONE[v] ?? 'bg-black/5 text-muted'
          }`}
        >
          {OCCASION_LABEL[v] ?? v}
        </span>
      ))}
    </div>
  )
}

function PlainList({ values, empty = '—' }) {
  if (!values || values.length === 0) {
    return <span className="text-xs text-muted-2">{empty}</span>
  }
  return <span className="text-xs text-muted">{values.join(', ')}</span>
}

export default function Catalog() {
  const { catalog } = useAppData()
  const { data, loading, error, reload } = catalog
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [showProgress, setShowProgress] = useState(false)

  const enrichment = useEnrichmentJob({
    onComplete: () => {
      setShowProgress(false)
      reload()
    },
  })

  const runAnalysis = useCallback(() => {
    setShowProgress(true)
    enrichment.start()
  }, [enrichment])

  // Keep the panel visible while a job is live, including one started from
  // the Upload page and still running when the seller navigates here.
  useEffect(() => {
    if (enrichment.running) setShowProgress(true)
  }, [enrichment.running])

  const products = data?.products ?? []
  const profile = data?.store_profile
  const summary = data?.summary

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return products
    return products.filter((p) =>
      [p.title, p.product_type, p.vendor, ...(p.occasions || []), ...(p.categories || [])]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(q),
    )
  }, [products, query])

  const openProduct = useCallback(
    (row) => navigate(`/catalog/${encodeURIComponent(row.product_id)}`),
    [navigate],
  )

  const columns = [
    {
      key: 'title',
      header: 'Product',
      width: '24%',
      primary: true,
      render: (row) => (
        <div className="flex min-w-0 items-center gap-2.5">
          <ProductThumb src={row.image_src} name={row.title} size="sm" />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">{row.title}</p>
            <p className="truncate text-xs text-muted">
              {row.product_type} · {row.vendor}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: 'occasions',
      header: 'Occasions',
      width: '18%',
      render: (row) => <OccasionChips values={row.occasions} />,
    },
    {
      key: 'categories',
      header: 'Category',
      width: '15%',
      hideOnMobile: true,
      render: (row) => <PlainList values={row.categories} empty="Not analysed" />,
    },
    {
      key: 'materials',
      header: 'Materials',
      width: '12%',
      hideOnMobile: true,
      render: (row) => <PlainList values={row.materials} />,
    },
    {
      key: 'audience',
      header: 'For',
      width: '8%',
      hideOnMobile: true,
      render: (row) =>
        row.audience ? (
          <StatusPill tone="neutral" label={row.audience} />
        ) : (
          <span className="text-xs text-muted-2">—</span>
        ),
    },
    {
      key: 'price_tier',
      header: 'Price',
      width: '10%',
      align: 'right',
      render: (row) => (
        <div className="flex flex-col items-end">
          <span className="text-sm font-medium text-ink tabular-nums">
            {formatPrice(row.price)}
          </span>
          {row.price_tier && (
            <span className="text-xs capitalize text-muted">{row.price_tier}</span>
          )}
        </div>
      ),
    },
    {
      key: 'stock_status',
      header: 'Stock',
      width: '13%',
      render: (row) => (
        <div className="flex flex-col gap-1">
          <StatusPill value={row.stock_status} />
          <span className="text-xs text-muted tabular-nums">
            {row.current_stock} · {formatDays(row.days_stock_remaining)}
          </span>
        </div>
      ),
    },
  ]

  const exportRows = () =>
    downloadCsv(
      'trendstock-catalog.csv',
      filtered.map((p) => ({
        product: p.title,
        type: p.product_type,
        vendor: p.vendor,
        categories: (p.categories || []).join(' | '),
        occasions: (p.occasions || []).join(' | '),
        materials: (p.materials || []).join(' | '),
        audience: p.audience || '',
        price: p.price,
        price_tier: p.price_tier || '',
        current_stock: p.current_stock,
        days_stock_remaining: p.days_stock_remaining,
      })),
    )

  return (
    <div className="flex flex-col gap-5 pb-4 pt-4">
      <PageHeader
        title="Catalog"
        subtitle="What the AI understands about each product. Click a row for its full outlook."
        onExport={products.length ? exportRows : undefined}
        exportDisabled={!filtered.length}
        primaryLabel={data?.enriched ? 'Re-run analysis' : 'Run analysis'}
        primaryIcon={Sparkles}
        onPrimary={products.length ? runAnalysis : undefined}
        primaryDisabled={enrichment.running}
      />

      {(showProgress || enrichment.running || enrichment.error) && (
        <Card className="h-auto">
          {enrichment.error ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm font-semibold text-ink">Analysis stopped</p>
              <p className="text-sm text-muted">{enrichment.error}</p>
              <div className="flex gap-2.5">
                <button
                  type="button"
                  onClick={runAnalysis}
                  className="w-fit rounded-pill bg-cta px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
                >
                  Try again
                </button>
                <button
                  type="button"
                  onClick={() => {
                    enrichment.reset()
                    setShowProgress(false)
                  }}
                  className="w-fit rounded-pill border border-hairline bg-card px-4 py-2 text-sm font-semibold text-ink hover:bg-cream"
                >
                  Dismiss
                </button>
              </div>
            </div>
          ) : (
            <AnalysisProgress job={enrichment.job} />
          )}
        </Card>
      )}

      {loading && (
        <>
          <SkeletonCard className="h-[120px]" />
          <SkeletonCard className="h-[560px]" />
        </>
      )}

      {!loading && error && (
        <Card className="h-auto">
          <EmptyState
            icon={Store}
            title="Couldn't load the catalog"
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

      {!loading && !error && products.length === 0 && (
        <Card className="h-auto min-h-[320px]">
          <EmptyState
            icon={UploadCloud}
            title="No catalog yet"
            description="Upload your product CSV and it will be analysed automatically."
            action={
              <button
                type="button"
                onClick={() => navigate('/upload')}
                className="rounded-pill bg-cta px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
              >
                Upload a CSV
              </button>
            }
          />
        </Card>
      )}

      {!loading && !error && products.length > 0 && (
        <>
          {profile?.store_type && (
            <Card className="h-auto">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-pastel-purple text-pastel-purple-ink">
                  <Store size={19} strokeWidth={2} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold tracking-wider text-muted-2">
                    YOUR STORE, AS UNDERSTOOD
                  </p>
                  <p className="mt-1 text-base font-semibold capitalize text-ink">
                    {profile.store_type}
                    {profile.price_positioning && (
                      <span className="ml-2 align-middle">
                        <StatusPill
                          tone="neutral"
                          label={profile.price_positioning.replace('_', ' ')}
                        />
                      </span>
                    )}
                  </p>
                  {profile.summary && (
                    <p className="mt-1.5 max-w-[70ch] text-sm text-muted">{profile.summary}</p>
                  )}
                </div>
              </div>
            </Card>
          )}

          {!data.enriched && (
            <Card className="h-auto">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-ink">
                    These products haven&apos;t been analysed yet
                  </p>
                  <p className="mt-0.5 text-sm text-muted">
                    Analysis works out what each product is for, so seasonal demand can
                    be matched to it.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={runAnalysis}
                  disabled={enrichment.running}
                  className="flex items-center gap-2 rounded-pill bg-cta px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Sparkles size={15} strokeWidth={2.25} />
                  Run analysis
                </button>
              </div>
            </Card>
          )}

          <Card
            title="Products"
            subtitle={
              summary
                ? `${summary.with_occasions} of ${summary.total_products} matched to occasions`
                : undefined
            }
            className="h-[600px]"
            actions={
              <SearchInput
                value={query}
                onChange={setQuery}
                placeholder="Search products or occasions"
              />
            }
          >
            <DataTable
              columns={columns}
              rows={filtered}
              rowKey={(row) => row.product_id}
              onRowClick={openProduct}
              emptyState={
                <EmptyState
                  icon={Sparkles}
                  title="No matching products"
                  description="Try a different search term."
                />
              }
            />
          </Card>
        </>
      )}
    </div>
  )
}
