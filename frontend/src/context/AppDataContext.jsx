import { createContext, useContext } from 'react'
import { useApiData } from '../hooks/useApiData'
import { getTrends, getCatalog } from '../lib/api'

// Sidebar and Topbar both need a sliver of real data (geo, pipeline
// freshness, catalog size) that otherwise lives inside the Trends and
// Catalog pages' own full fetches. Rather than have the shell fire its own
// extra requests, this context is the *single* fetch of /api/trends and
// /api/catalog for the whole app — Trends.jsx and Catalog.jsx consume the
// same state instead of calling useApiData themselves, so navigating
// between routes never re-fetches data the shell already has.
const AppDataContext = createContext(null)

export function AppDataProvider({ children }) {
  const trends = useApiData(getTrends, [])
  const catalog = useApiData(getCatalog, [])

  return <AppDataContext.Provider value={{ trends, catalog }}>{children}</AppDataContext.Provider>
}

export function useAppData() {
  const ctx = useContext(AppDataContext)
  if (!ctx) {
    throw new Error('useAppData must be used within an AppDataProvider')
  }
  return ctx
}
