import { useEffect, useState, useCallback } from 'react'

// Generic loader around the api.js getters. `fetcher` is one of
// getDashboard / getTrends / getCatalog — anything shaped like
// () => Promise<{ data, error }>.
export function useApiData(fetcher, deps = []) {
  const [state, setState] = useState({
    data: null,
    loading: true,
    error: null,
  })

  const load = useCallback(() => {
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    fetcher()
      .then(({ data, error }) => {
        if (cancelled) return
        setState({ data, loading: false, error: error ?? null })
      })
      .catch((err) => {
        if (cancelled) return
        setState({ data: null, loading: false, error: err.message })
      })
    return () => {
      cancelled = true
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => load(), [load])

  return { ...state, reload: load }
}
