import { Globe2, Package, TriangleAlert, Menu } from 'lucide-react'
import { useAppData } from '../../context/AppDataContext'

export default function Topbar({ onMenuClick }) {
  const { pipelineStatus, catalog } = useAppData()

  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-3 px-4 md:px-8">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <button
          type="button"
          onClick={onMenuClick}
          aria-label="Open menu"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-hairline bg-card text-ink lg:hidden"
        >
          <Menu size={18} />
        </button>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {/* The reference design has notification/preferences icon buttons here.
            They are deliberately absent: there is no notification system and no
            preferences to set, and a button that looks interactive but does
            nothing when clicked reads as a broken app. Same reasoning that
            removed the dead global search box. Add them back alongside the
            features, not before. */}
        <StatusPill pipelineStatus={pipelineStatus} catalog={catalog} />
      </div>
    </header>
  )
}

// Replaces the reference design's avatar + fictional name. There's no auth
// system in this project, so a person's name here would be invented — this
// pill instead surfaces two real, always-available facts: the tracked
// region (from /api/pipeline-status) and the current catalog size (from
// /api/catalog), both already fetched once by AppDataProvider for the shell.
function StatusPill({ pipelineStatus, catalog }) {
  const loading = pipelineStatus.loading || catalog.loading
  const hasError = pipelineStatus.error || catalog.error

  return (
    <div className="flex items-center gap-2.5 rounded-pill border border-hairline bg-card py-2 pl-3 pr-3.5">
      <span className="flex items-center gap-1.5 text-sm font-semibold text-ink">
        <Globe2 size={15} className="text-pastel-blue-ink" />
        {loading ? '···' : hasError ? '—' : (pipelineStatus.data?.geo ?? '—')}
      </span>
      <span className="h-4 w-px shrink-0 bg-hairline" />
      <span className="flex items-center gap-1.5 text-sm font-medium text-muted">
        {hasError ? (
          <TriangleAlert size={14} className="text-negative" />
        ) : (
          <Package size={14} className="text-pastel-purple-ink" />
        )}
        {loading
          ? 'Loading…'
          : hasError
            ? 'Unavailable'
            : `${catalog.data?.summary?.total_products ?? 0} products`}
      </span>
    </div>
  )
}
