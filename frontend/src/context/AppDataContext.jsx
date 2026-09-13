import { createContext, useContext } from 'react'
import { useApiData } from '../hooks/useApiData'
import { getCatalog, getPipelineStatus } from '../lib/api'

// Sidebar and Topbar both need a sliver of real data (pipeline freshness,
// catalog size) that otherwise lives inside the Catalog page's own full
// fetch. Rather than have the shell fire its own extra requests, this
// context is the *single* fetch of /api/catalog and /api/pipeline-status for
// the whole app — Catalog.jsx consumes the same state instead of calling
// useApiData itself, so navigating between routes never re-fetches data the
// shell already has.
const AppDataContext = createContext(null)

export function AppDataProvider({ children }) {
  const catalog = useApiData(getCatalog, [])
  const pipelineStatus = useApiData(getPipelineStatus, [])

  return (
    <AppDataContext.Provider value={{ catalog, pipelineStatus }}>
      {children}
    </AppDataContext.Provider>
  )
}

export function useAppData() {
  const ctx = useContext(AppDataContext)
  if (!ctx) {
    throw new Error('useAppData must be used within an AppDataProvider')
  }
  return ctx
}
