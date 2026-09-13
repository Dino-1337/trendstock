import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { LineChart as LineChartIcon } from 'lucide-react'
import EmptyState from './EmptyState'
import { formatDate } from '../../lib/format'

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="rounded-xl border border-hairline bg-card px-4 py-3 card-shadow">
      <p className="text-xs font-medium text-muted">{formatDate(label)}</p>
      <div className="mt-1.5 flex flex-col gap-1">
        {payload.map((p) => (
          <p key={p.dataKey} className="flex items-center gap-2 text-sm font-semibold text-ink">
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: p.stroke }}
            />
            {p.name}: {p.value}
          </p>
        ))}
      </div>
    </div>
  )
}

// Renders the "Trend Momentum Flow" chart, or — the expected day-one state
// — an honest empty state when the backend hasn't accumulated enough daily
// snapshots yet. `chart` is dashboard.momentum_chart from the API contract:
// { available, message, points: [{ date, spiking, rising, steady }] }.
export default function MomentumChart({ chart }) {
  if (!chart || !chart.available || !chart.points || chart.points.length < 2) {
    return (
      <EmptyState
        icon={LineChartIcon}
        title="Momentum is still warming up"
        description={
          chart?.message ??
          'Momentum needs a run of daily snapshots before a trend line means anything.'
        }
      />
    )
  }

  const latest = chart.points[chart.points.length - 1]
  const total = (latest.spiking ?? 0) + (latest.rising ?? 0) + (latest.steady ?? 0)

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 shrink-0">
        <p className="text-2xl font-bold tracking-tight text-ink md:text-[28px]">{total}</p>
        <p className="mt-0.5 text-sm font-medium text-positive">
          {latest.spiking} spiking · {latest.rising} rising today
        </p>
      </div>
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chart.points} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <XAxis
              dataKey="date"
              tickFormatter={(d) => formatDate(d, { month: 'short', day: 'numeric', year: undefined })}
              tick={{ fill: '#8A8A8A', fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis tick={{ fill: '#8A8A8A', fontSize: 12 }} axisLine={false} tickLine={false} width={28} />
            <Tooltip cursor={{ stroke: '#D8D2C6', strokeDasharray: '4 4' }} content={<CustomTooltip />} />
            <Line
              type="monotone"
              dataKey="rising"
              name="Rising"
              stroke="var(--color-chart-purple)"
              strokeWidth={2.5}
              dot={false}
              activeDot={{ r: 5, strokeWidth: 2, stroke: '#fff' }}
            />
            <Line
              type="monotone"
              dataKey="spiking"
              name="Spiking"
              stroke="var(--color-chart-pink)"
              strokeWidth={2.5}
              dot={false}
              activeDot={{ r: 5, strokeWidth: 2, stroke: '#fff' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
