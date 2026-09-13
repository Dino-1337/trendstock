// Client-side CSV export. Writes exactly what's already on screen — no
// backend endpoint, no synthesised fields, just a serialization of the data
// the page already fetched and rendered.

function triggerDownload(filename, blob) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function csvEscape(value) {
  if (value === null || value === undefined) return ''
  const str = String(value)
  if (/[",\n]/.test(str)) return `"${str.replace(/"/g, '""')}"`
  return str
}

// columns: [{ header, key }] where key is either a string field name on the
// row, or a function(row) for derived/nested values. Optional — when omitted,
// columns are derived from the first row's own keys (header = key, value =
// row[key]), which is enough for a flat, already-shaped export row.
export function downloadCsv(filename, rows, columns) {
  const cols = columns ?? Object.keys(rows[0] ?? {}).map((key) => ({ header: key, key }))
  const header = cols.map((c) => csvEscape(c.header)).join(',')
  const lines = rows.map((row) =>
    cols
      .map((c) => csvEscape(typeof c.key === 'function' ? c.key(row) : row[c.key]))
      .join(','),
  )
  const csv = [header, ...lines].join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  triggerDownload(filename, blob)
}
