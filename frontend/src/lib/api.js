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

export function getDashboard() {
  return getJson('/dashboard', (b) => Array.isArray(b.stats) && b.momentum_chart)
}

export function getTrends() {
  return getJson('/trends', (b) => Array.isArray(b.trends))
}

export function getCatalog() {
  return getJson('/catalog', (b) => Array.isArray(b.products) && Array.isArray(b.gaps))
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
// Clears the product tag cache and tags again from scratch. Manual because
// tagging is cached: a run that fell back to rule-based (Groq rate limited)
// otherwise stays that way, and the seller has no way to ask for another try.
export async function retagCatalog() {
  const res = await fetch('/api/catalog/retag', { method: 'POST' })
  const body = await res.json().catch(() => null)
  if (!res.ok || typeof body?.ok !== 'boolean') {
    throw new Error(body?.error || `Re-tag failed (${res.status})`)
  }
  return body
}

export function previewCsv(file) {
  return postCsv('/api/upload/preview', file)
}

export function uploadCsv(file) {
  return postCsv('/api/upload', file)
}
