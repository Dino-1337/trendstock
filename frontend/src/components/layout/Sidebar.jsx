import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import {
  Diamond,
  LayoutGrid,
  BellRing,
  Package,
  UploadCloud,
  X,
  TriangleAlert,
} from 'lucide-react'
import { useAppData } from '../../context/AppDataContext'
import { formatDateTime } from '../../lib/format'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutGrid, end: true },
  { to: '/alerts', label: 'Alerts', icon: BellRing },
  { to: '/catalog', label: 'Catalog', icon: Package },
  { to: '/upload', label: 'Upload', icon: UploadCloud },
]

function SidebarContent({ onNavigate }) {
  return (
    <div className="flex h-full flex-col px-4 py-5">
      <div className="mb-6 flex items-center justify-between px-2">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-cta text-white">
            <Diamond size={16} strokeWidth={2.5} fill="currentColor" />
          </span>
          <span className="text-lg font-bold tracking-tight text-ink">Trendstock</span>
        </div>
        <button
          type="button"
          onClick={onNavigate}
          aria-label="Close sidebar"
          className="rounded-lg p-1.5 text-muted hover:bg-cream lg:hidden"
        >
          <X size={18} />
        </button>
        {/* No desktop collapse button: there is no collapse behaviour to
            trigger. The mobile close button above is real and does close the
            drawer. */}
      </div>

      <p className="mb-2 px-3 text-xs font-semibold tracking-wider text-muted-2">GENERAL</p>

      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 rounded-pill px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-pastel-purple text-pastel-purple-ink'
                  : 'text-muted hover:bg-cream hover:text-ink',
              )
            }
          >
            <item.icon size={17} strokeWidth={2.15} />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto flex flex-col gap-4 pt-6">
        <PipelineStatusCard />

        {/* Settings / Help Center from the reference design are omitted: there
            are no such screens to navigate to. Dead nav items are worse than a
            shorter sidebar - they make every other control look untrustworthy
            too. Restore them when the pages exist. */}
      </div>
    </div>
  )
}

// Real pipeline status, sourced from /api/pipeline-status (shared via
// AppDataContext so it doesn't trigger its own fetch). This reports the raw
// Google Trends fetch history, independent of whether a catalog has been
// analysed — momentum classification needs ~7 days of daily snapshots, so
// snapshot_count / 7 is an honest progress ratio, not an invented one.
function PipelineStatusCard() {
  const { pipelineStatus } = useAppData()
  const { data, loading, error } = pipelineStatus

  return (
    <div className="rounded-chip bg-cream p-4">
      <p className="text-sm font-semibold leading-snug text-ink">Pipeline status</p>

      {loading && (
        <div className="mt-2 flex flex-col gap-2">
          <div className="h-3 w-3/4 animate-pulse rounded-full bg-black/10" />
          <div className="h-1.5 w-full animate-pulse rounded-full bg-black/10" />
        </div>
      )}

      {!loading && error && (
        <p className="mt-1 flex items-start gap-1.5 text-xs text-negative">
          <TriangleAlert size={13} className="mt-0.5 shrink-0" />
          Couldn&apos;t reach the trend pipeline.
        </p>
      )}

      {!loading && !error && data && (
        <>
          <p className="mt-1 text-xs text-muted">
            {data.geo} · updated {formatDateTime(data.generated_at)}
          </p>
          <div className="my-3 h-1.5 w-full overflow-hidden rounded-full bg-white">
            <div
              className="h-full rounded-full bg-pastel-pink"
              style={{ width: `${Math.min(100, (data.snapshot_count / 7) * 100)}%` }}
            />
          </div>
          <p className="text-xs text-muted">
            {data.snapshot_count} of 7 days of snapshots collected
          </p>
        </>
      )}
    </div>
  )
}

export default function Sidebar({ mobileOpen, onClose }) {
  return (
    <>
      {/* Desktop: fixed sidebar, always visible at lg+ */}
      <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-30 lg:flex lg:w-[240px] lg:flex-col lg:border-r lg:border-hairline lg:bg-card">
        <SidebarContent />
      </aside>

      {/* Mobile: drawer overlay */}
      <div
        className={clsx(
          'fixed inset-0 z-40 lg:hidden',
          mobileOpen ? 'pointer-events-auto' : 'pointer-events-none',
        )}
        aria-hidden={!mobileOpen}
      >
        <div
          className={clsx(
            'absolute inset-0 bg-black/30 transition-opacity',
            mobileOpen ? 'opacity-100' : 'opacity-0',
          )}
          onClick={onClose}
        />
        <aside
          className={clsx(
            'absolute inset-y-0 left-0 w-[260px] max-w-[80vw] bg-card shadow-2xl transition-transform duration-200',
            mobileOpen ? 'translate-x-0' : '-translate-x-full',
          )}
        >
          <SidebarContent onNavigate={onClose} />
        </aside>
      </div>
    </>
  )
}
