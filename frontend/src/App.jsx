import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AppDataProvider } from './context/AppDataContext'
import AppShell from './components/layout/AppShell'
import Dashboard from './pages/Dashboard'
import Catalog from './pages/Catalog'
import ProductDetail from './pages/ProductDetail'
import Alerts from './pages/Alerts'
import Upload from './pages/Upload'

function App() {
  return (
    <AppDataProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Dashboard />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="catalog" element={<Catalog />} />
            <Route path="catalog/:productId" element={<ProductDetail />} />
            <Route path="upload" element={<Upload />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppDataProvider>
  )
}

export default App
