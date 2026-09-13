import { useParams, useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, CalendarClock, ExternalLink, PackageX } from 'lucide-react'
import PageHeader from '../components/layout/PageHeader'
import Card from '../components/primitives/Card'
import EmptyState from '../components/primitives/EmptyState'
import ProductThumb from '../components/primitives/ProductThumb'
import SkeletonCard from '../components/primitives/SkeletonCard'
import StatusPill from '../components/primitives/StatusPill'
import StockOutlookChart from '../components/primitives/StockOutlookChart'
import { useApiData } from '../hooks/useApiData'
import { getProductDetail } from '../lib/api'
import { formatDate, formatDays, formatPrice } from '../lib/format'

const LIFT_TONE = {
  high: 'bg-pastel-pink text-pastel-pink-ink',
  medium: 'bg-pastel-yellow text-pastel-yellow-ink',
  low: 'bg-black/5 text-muted',
}

function whenLabel(days) {
  if (days === null || days === undefined) return 'Ongoing'
  if (days < 0) return `Started ${Math.abs(days)}d ago`
  if (days === 0) return 'Today'
  return `In ${days}d`
}

function SignalCard({ signal }) {
  return (
    <div className="flex flex-col gap-1.5 border-b border-hairline py-3.5 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-ink">{signal.name}</span>
        <StatusPill tone={signal.in_window ? 'pink' : 'purple'} label={whenLabel(signal.days_until)} />
        {signal.demand_lift && (
          <span
            className={`inline-flex w-fit items-center whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${
              LIFT_TONE[signal.demand_lift] ?? 'bg-black/5 text-muted'
            }`}
          >
            {signal.demand_lift} lift
          </span>
        )}
      </div>
      {signal.reasoning && <p className="max-w-[70ch] text-sm text-muted">{signal.reasoning}</p>}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span>{signal.reasons?.join(' · ')}</span>
        {signal.lead_window_start && (
          <span>
            Demand window: {formatDate(signal.lead_window_start)} → {formatDate(signal.event_date)}
          </span>
        )}
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

export default function ProductDetail() {
  const { productId } = useParams()
  const navigate = useNavigate()
  const { data, loading, error } = useApiData(() => getProductDetail(productId), [productId])

  return (
    <div className="flex flex-col gap-5 pb-4 pt-4">
      <button
        type="button"
        onClick={() => navigate('/catalog')}
        className="flex w-fit items-center gap-1.5 text-sm font-medium text-muted hover:text-ink"
      >
        <ArrowLeft size={15} />
        Back to catalog
      </button>

      {loading && (
        <>
          <SkeletonCard className="h-[120px]" />
          <SkeletonCard className="h-[360px]" />
          <SkeletonCard className="h-[320px]" />
        </>
      )}

      {!loading && error && (
        <Card className="h-auto">
          <EmptyState icon={PackageX} title="Couldn't load this product" description={error} />
        </Card>
      )}

      {!loading && !error && data && (
        <>
          <PageHeader
            title={data.product.title}
            subtitle={`${data.product.product_type} · ${data.product.vendor}`}
          />

          <Card className="h-auto">
            <div className="flex flex-wrap items-center gap-4">
              <ProductThumb src={data.product.image_src} name={data.product.title} size="lg" />
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                <div>
                  <p className="text-xs text-muted">Price</p>
                  <p className="text-lg font-semibold text-ink tabular-nums">
                    {formatPrice(data.product.price)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted">Current stock</p>
                  <p className="text-lg font-semibold text-ink tabular-nums">
                    {data.product.current_stock}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted">Cover remaining</p>
                  <div className="flex items-center gap-2">
                    <p className="text-lg font-semibold text-ink tabular-nums">
                      {formatDays(data.product.days_stock_remaining)}
                    </p>
                    <StatusPill value={data.product.stock_status} />
                  </div>
                </div>
                {data.enrichment?.occasions?.length > 0 && (
                  <div>
                    <p className="text-xs text-muted">Occasions</p>
                    <p className="text-sm font-medium capitalize text-ink">
                      {data.enrichment.occasions.join(', ')}
                    </p>
                  </div>
                )}
                {data.enrichment?.audience && (
                  <div>
                    <p className="text-xs text-muted">Audience</p>
                    <p className="text-sm font-medium capitalize text-ink">{data.enrichment.audience}</p>
                  </div>
                )}
              </div>
            </div>
          </Card>

          {data.reorder_alert && (
            <Card className="h-auto border-2 border-pastel-pink bg-pastel-pink/10">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-pastel-pink text-pastel-pink-ink">
                  <AlertTriangle size={19} strokeWidth={2} />
                </span>
                <div>
                  <p className="text-sm font-semibold text-ink">Reorder before you run out</p>
                  <p className="mt-0.5 text-sm text-muted">
                    On current velocity this sells out around{' '}
                    <span className="font-medium text-ink">
                      {formatDate(data.reorder_alert.stockout_date)}
                    </span>
                    , at or before {data.reorder_alert.signal_name} on{' '}
                    <span className="font-medium text-ink">
                      {formatDate(data.reorder_alert.event_date)}
                    </span>
                    .
                  </p>
                </div>
              </div>
            </Card>
          )}

          <Card
            title="Stock outlook"
            subtitle="Projected stock on current velocity, with demand windows from matched events"
            className="h-[380px]"
          >
            <StockOutlookChart
              points={data.projection.points}
              signals={data.signals}
              today={data.projection.points[0]?.date}
            />
          </Card>

          <Card
            title="What affects this product"
            subtitle={`${data.signals.length} matched signal${data.signals.length === 1 ? '' : 's'}`}
            className="h-auto min-h-[200px]"
          >
            {data.signals.length === 0 ? (
              <EmptyState
                icon={CalendarClock}
                title="No signals matched yet"
                description="Nothing on the calendar currently affects this product's occasions."
              />
            ) : (
              <div className="flex flex-col">
                {data.signals.map((signal) => (
                  <SignalCard key={signal.name} signal={signal} />
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
