import clsx from 'clsx'

// Generic empty/explanatory state used across screens: momentum chart
// before enough snapshots exist, catalog before a CSV upload, zero trend
// matches, etc. Always honest about *why* the data is missing.
export default function EmptyState({ icon: Icon, title, description, action, className }) {
  return (
    <div
      className={clsx(
        'flex h-full flex-col items-center justify-center gap-3 rounded-chip px-6 py-8 text-center',
        className,
      )}
    >
      {Icon && (
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-pastel-purple text-pastel-purple-ink">
          <Icon size={22} strokeWidth={2} />
        </span>
      )}
      <div className="max-w-sm">
        <p className="text-sm font-semibold text-ink">{title}</p>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {action}
    </div>
  )
}
