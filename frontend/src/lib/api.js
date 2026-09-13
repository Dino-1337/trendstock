// Thin API wrapper around the backend (proxied at /api -> localhost:8100 by
// vite.config.js).
//
// There is deliberately no mock/fixture fallback here. If the backend is
// unreachable or returns something unexpected, the screen shows an error and
// a retry — it never substitutes fabricated data, because a dashboard that
// invents plausible-looking numbers is worse than one that admits it has none.

// `shapeCheck` guards against trusting a 200 response that happens to be JSON
// but isn't actually our contract (e.g. a stray dev server answering on the
// proxied port).
async function getJson(path, shapeCheck) {
  const res = await fetch(`/api${path}`, {
    headers: { Accept: 'application/json' },
  })
  const body = await res.json().catch(() => null)

  if (!res.ok || !body || body.ok === false) {
    throw new Error(body?.error || `Request failed (${res.status})`)
  }
  if (shapeCheck && !shapeCheck(body)) {
    throw new Error('The server responded, but not with the expected data.')
  }
  return { data: body, error: null }
}

// Home screen: the smallest number of things worth acting on this week, not a
// KPI grid. `ready: false` means the catalog hasn't been analysed yet.
export function getDashboard() {
  return getJson('/dashboard', (b) => typeof b.ready === 'boolean')
}

// Raw trend-feed fetch health (independent of analysis) — used by the
// sidebar's "N of 7 days collected" indicator.
export function getPipelineStatus() {
  return getJson('/pipeline-status', (b) => typeof b.snapshot_count === 'number')
}

// Upload/preview report exactly what the backend said. Column validation and
// variant-grouping both live on the backend so there is one source of truth;
// the client does not pre-judge the file or synthesise a result when the
// request fails.
async function postCsv(path, file) {
  const form = new FormData()
  form.append('file', file)

  const res = await fetch(path, { method: 'POST', body: form })
  const body = await res.json().catch(() => null)

  if (typeof body?.ok !== 'boolean') {
    throw new Error(`Unexpected response (${res.status})`)
  }
  if (body.ok === false && !Array.isArray(body.detail)) {
    body.detail = []
  }
  return { data: body }
}

// Dry run: same validation/parsing as uploadCsv, but the backend persists
// nothing. Lets the UI show a review step (grouped products, counts,
// warnings) before the user commits the import.
export function previewCsv(file) {
  return postCsv('/api/upload/preview', file)
}

export function uploadCsv(file) {
  return postCsv('/api/upload', file)
}

// The catalog with its AI-derived columns (occasions, materials, audience,
// price tier). `enriched: false` means nothing has been analysed yet — the UI
// offers to start it rather than showing an empty table that looks broken.
export function getCatalog() {
  return getJson('/catalog', (b) => Array.isArray(b.products))
}

// One product's full detail: enrichment, a stock-depletion projection, and
// every signal that matches it.
export function getProductDetail(productId) {
  return getJson(`/catalog/${encodeURIComponent(productId)}`, (b) => b.product)
}

// Enrichment is minutes, not milliseconds — one model call per batch of ten
// products — so it runs as a background job and the UI polls for progress.
// Returns the initial job record, including its job_id.
export async function startEnrichment() {
  const res = await fetch('/api/enrich', { method: 'POST' })
  const body = await res.json().catch(() => null)
  if (!res.ok || body?.ok !== true) {
    throw new Error(body?.error || `Could not start analysis (${res.status})`)
  }
  return body
}

export function getJobStatus(jobId) {
  return getJson(`/jobs/${jobId}`, (b) => typeof b.stage === 'string')
}

// Upcoming events/seasons, what each affects, and which products are about to
// run out because of them. `ready: false` carries a `reason` explaining what
// is still missing rather than rendering an empty page.
export function getAlerts() {
  return getJson('/alerts', (b) => Array.isArray(b.signals) && Array.isArray(b.warnings))
}
