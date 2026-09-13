import clsx from 'clsx'

// Column shape: { key, header, render(row), align, width, primary, hideOnMobile }
// - `primary` marks the column shown as the mobile card's title row.
// - Desktop/tablet renders a real <table> that scrolls horizontally inside
//   its own wrapper (the page body itself never scrolls sideways).
// - Below `md` the table becomes a stack of card-rows (checklist requirement),
//   each showing label/value pairs for every non-primary column.
// - `onRowClick(row)` is optional; when passed, every row (table row and
//   mobile card alike) becomes a click target with a visible hover/focus
//   state, for pages that drill into a per-row detail view.
export default function DataTable({ columns, rows, rowKey, emptyState, onRowClick }) {
  if (!rows || rows.length === 0) {
    return <div className="flex h-full items-center justify-center">{emptyState}</div>
  }

  const primaryCol = columns.find((c) => c.primary) ?? columns[0]
  const restCols = columns.filter((c) => c !== primaryCol)

  return (
    <>
      {/* Desktop / tablet table */}
      <div className="hidden h-full overflow-y-auto overflow-x-auto md:block">
        <table className="w-full min-w-[680px] border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-card">
            <tr className="border-b border-hairline text-left text-xs font-medium uppercase tracking-wide text-muted">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={clsx('whitespace-nowrap px-4 py-3', col.align === 'right' && 'text-right')}
                  style={col.width ? { width: col.width } : undefined}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === 'Enter' || e.key === ' ') onRowClick(row)
                      }
                    : undefined
                }
                className={clsx(
                  'border-b border-hairline last:border-0 hover:bg-cream/60',
                  onRowClick && 'cursor-pointer focus:outline-none focus:bg-cream/80',
                )}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={clsx('px-4 py-4 align-middle', col.align === 'right' && 'text-right')}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile stacked cards */}
      <div className="flex h-full flex-col gap-3 overflow-y-auto md:hidden">
        {rows.map((row) => (
          <div
            key={rowKey(row)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            role={onRowClick ? 'button' : undefined}
            tabIndex={onRowClick ? 0 : undefined}
            className={clsx(
              'rounded-chip border border-hairline p-4',
              onRowClick && 'cursor-pointer active:bg-cream/60',
            )}
          >
            <div>{primaryCol.render(row)}</div>
            <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-3 text-sm">
              {restCols
                .filter((c) => !c.hideOnMobile)
                .map((col) => (
                  <div key={col.key} className="min-w-0">
                    <div className="text-xs text-muted">{col.header}</div>
                    <div className={clsx('mt-0.5', col.noTruncateMobile ? 'whitespace-normal break-words' : 'truncate')}>
                      {col.render(row)}
                    </div>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
