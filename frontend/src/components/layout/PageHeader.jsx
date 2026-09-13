import { Upload, RefreshCw } from 'lucide-react'

// Both action buttons are opt-in: a screen only gets an Export button if it
// passes onExport (i.e. it has real, currently-displayed data to write out),
// and only gets the primary button if it passes onPrimary (a genuine
// reload()). A screen with nothing to export or refresh renders neither —
// no dead buttons that look actionable but do nothing.
export default function PageHeader({
  title,
  subtitle,
  onExport,
  exportDisabled = false,
  primaryLabel = 'Refresh',
  primaryIcon: PrimaryIcon = RefreshCw,
  onPrimary,
  primaryDisabled = false,
  extra,
}) {
  const hasActions = Boolean(onExport || onPrimary)

  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div className="min-w-0">
        <h1 className="text-[26px] font-bold tracking-tight text-ink md:text-[30px]">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted md:text-base">{subtitle}</p>}
        {extra && <div className="mt-2">{extra}</div>}
      </div>
      {hasActions && (
        <div className="flex shrink-0 items-center gap-2.5">
          {onExport && (
            <button
              type="button"
              onClick={onExport}
              disabled={exportDisabled}
              className="flex items-center gap-2 rounded-pill border border-hairline bg-card px-4 py-2.5 text-sm font-semibold text-ink hover:bg-cream disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-card"
            >
              <Upload size={15} strokeWidth={2.25} />
              Export
            </button>
          )}
          {onPrimary && (
            <button
              type="button"
              onClick={onPrimary}
              disabled={primaryDisabled}
              className="flex items-center gap-2 rounded-pill bg-cta px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <PrimaryIcon size={15} strokeWidth={2.25} />
              {primaryLabel}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
