import clsx from 'clsx'

// Fixed-height card shell. Height must always come from the caller via
// `className` (e.g. "h-[440px]") — never let content push it taller. The
// body is a flex child with min-h-0 so its own overflow scrolls instead of
// stretching the card.
export default function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
  padded = true,
}) {
  return (
    <div
      className={clsx(
        'flex flex-col rounded-card border border-hairline bg-card card-shadow',
        padded && 'p-5 md:p-6',
        className,
      )}
    >
      {(title || actions) && (
        <div className="mb-4 flex shrink-0 items-start justify-between gap-3">
          <div className="min-w-0">
            {title && (
              <h3 className="truncate text-base font-semibold text-ink md:text-lg">
                {title}
              </h3>
            )}
            {subtitle && (
              <p className="mt-0.5 truncate text-xs text-muted">{subtitle}</p>
            )}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={clsx('min-h-0 flex-1', bodyClassName)}>{children}</div>
    </div>
  )
}
