import {
  Area,
  AreaChart,
  ReferenceArea,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
  ResponsiveContainer,
} from 'recharts'
import { PackageX } from 'lucide-react'
import EmptyState from './EmptyState'
import { formatDate } from '../../lib/format'

// One colour per occasion band, echoing Catalog's OCCASION_TONE but as a
// fill colour rather than a chip class - the chart draws directly with
// tokens, not Tailwind classes.
const BAND_FILL = {
  festive: '#f28fb8',
  wedding: '#b9a4ef',
  bridal: '#b9a4ef',
  gifting: '#fae49b',
  party: '#f28fb8',
  religious: '#b9a4ef',
  work_formal: '#d2e0f8',
  sport_active: '#d2e0f8',
  travel: '#d2e0f8',
  summer: '#fae49b',
  winter: '#d2e0f8',
  monsoon: '#d2e0f8',
}

function primaryOccasionFill(signal) {
  const occ = (signal.reasons || []).find((r) => r.startsWith('occasion:'))
  const first = occ?.replace('occasion: ', '').split(',')[0]?.trim()
  return BAND_FILL[first] || '#b9a4ef'
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null
  const stock = payload.find((p) => p.dataKey === 'stock')
  return (
    <div className="rounded-xl border border-hairline bg-card px-4 py-3 card-shadow">
      <p className="text-xs font-medium text-muted">{formatDate(label)}</p>
      <p className="mt-1 text-sm font-semibold text-ink">
        {stock ? Math.round(stock.value) : 0} units projected
      </p>
    </div>
  )
}

/**
 * Stock depletion on current velocity, with bands for every matched signal's
 * lead window. Answers one question at a glance: does the stock line cross
 * zero before or during a demand spike.
 *
 * Deliberately not a "sales forecast" - there is no real order history, only
 * synthetic velocity, so the line is a projection of the current trend, not a
 * prediction of a different one.
 */
export default function StockOutlookChart({ points, signals, today }) {
  if (!points || points.length < 2) {
    return (
      <EmptyState
        icon={PackageX}
        title="Not enough data to project"
        description="This product needs stock and sales velocity to chart an outlook."
      />
    )
  }

  return (
    <div className="h-full min-h-0">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 12, right: 12, bottom: 0, left: -16 }}>
          <defs>
            <linearGradient id="stockFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-chart-purple)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--color-chart-purple)" stopOpacity={0.02} />
            </linearGradient>
          </defs>

          <XAxis
            dataKey="date"
            tickFormatter={(d) => formatDate(d, { month: 'short', day: 'numeric', year: undefined })}
            tick={{ fill: '#8A8A8A', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            tick={{ fill: '#8A8A8A', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={32}
            allowDecimals={false}
            domain={[0, 'dataMax']}
          />
          <Tooltip cursor={{ stroke: '#D8D2C6', strokeDasharray: '4 4' }} content={<CustomTooltip />} />

          {/* Lead-window bands, one per matched signal that has a date. */}
          {(signals || [])
            .filter((s) => s.lead_window_start && s.event_date)
            .map((s) => (
              <ReferenceArea
                key={s.name}
                x1={s.lead_window_start < today ? today : s.lead_window_start}
                x2={s.event_date}
                fill={primaryOccasionFill(s)}
                fillOpacity={0.22}
                ifOverflow="visible"
              />
            ))}

          <ReferenceLine x={today} stroke="#1a1a1a" strokeDasharray="3 3" strokeOpacity={0.4} />

          <Area
            type="monotone"
            dataKey="stock"
            stroke="var(--color-chart-purple)"
            strokeWidth={2.5}
            fill="url(#stockFill)"
            dot={false}
            activeDot={{ r: 5, strokeWidth: 2, stroke: '#fff' }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
