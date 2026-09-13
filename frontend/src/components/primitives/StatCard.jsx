import clsx from 'clsx'
import {
  ArrowUpRight,
  ArrowDownRight,
  Activity,
  TrendingUp,
  PackageSearch,
  AlertTriangle,
  BarChart3,
  Package,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react'
import { formatNumber, formatPercent } from '../../lib/format'

const CHIP_STYLES = {
  pink: 'bg-pastel-pink text-pastel-pink-ink',
  purple: 'bg-pastel-purple text-pastel-purple-ink',
  yellow: 'bg-pastel-yellow text-pastel-yellow-ink',
  blue: 'bg-pastel-blue text-pastel-blue-ink',
}

// Reference spec: chip colors cycle pink / purple / yellow / blue across
// the four KPI columns, in that order.
const CHIP_ORDER = ['pink', 'purple', 'yellow', 'blue']

const ICON_BY_KEY = {
  trends_tracked: Activity,
  rising_trends: TrendingUp,
  catalog_matches: PackageSearch,
  stock_alerts: AlertTriangle,
  // catalog summary stats
  total_products: Package,
  matched: CheckCircle2,
  gaps: AlertCircle,
  at_risk: AlertTriangle,
}

export default function StatCard({ stat, index = 0 }) {
  const tone = CHIP_ORDER[index % CHIP_ORDER.length]
  const Icon = ICON_BY_KEY[stat.key] ?? BarChart3
  const hasDelta = stat.delta_pct !== null && stat.delta_pct !== undefined
  const isUp = stat.direction === 'up'
  const isDown = stat.direction === 'down'

  return (
    <div className="flex h-[132px] flex-col justify-between rounded-card border border-hairline bg-card card-shadow p-5">
      <div className="flex items-center gap-3">
        <span
          className={clsx(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
            CHIP_STYLES[tone],
          )}
        >
          <Icon size={16} strokeWidth={2.25} />
        </span>
        <span className="truncate text-sm font-medium text-muted">{stat.label}</span>
      </div>

      <div className="flex items-end justify-between gap-2">
        <span className="text-2xl font-bold tracking-tight text-ink md:text-[28px]">
          {formatNumber(stat.value)}
        </span>
        {hasDelta ? (
          <span
            className={clsx(
              'flex shrink-0 items-center gap-0.5 rounded-full px-2 py-1 text-xs font-semibold',
              isUp && 'bg-positive-bg text-positive',
              isDown && 'bg-negative-bg text-negative',
              !isUp && !isDown && 'bg-black/5 text-muted',
            )}
          >
            {isUp && <ArrowUpRight size={13} />}
            {isDown && <ArrowDownRight size={13} />}
            {formatPercent(stat.delta_pct)}
          </span>
        ) : (
          <span className="shrink-0 rounded-full bg-black/5 px-2 py-1 text-xs font-medium text-muted">
            No history
          </span>
        )}
      </div>
    </div>
  )
}
