import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AppDataProvider } from './context/AppDataContext'
import AppShell from './components/layout/AppShell'
import Dashboard from './pages/Dashboard'
import Trends from './pages/Trends'
import Catalog from './pages/Catalog'
import Upload from './pages/Upload'

function App() {
  return (
    <AppDataProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Dashboard />} />
            <Route path="trends" element={<Trends />} />
            <Route path="catalog" element={<Catalog />} />
            <Route path="upload" element={<Upload />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppDataProvider>
  )
}

export default App
