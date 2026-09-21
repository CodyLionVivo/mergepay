import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { BountyDetailPage } from './pages/BountyDetailPage'
import { CreateBountyPage } from './pages/CreateBountyPage'
import { MarketplacePage } from './pages/MarketplacePage'
import { NotFoundPage } from './pages/NotFoundPage'

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<MarketplacePage />} />
        <Route path="/bounties/new" element={<CreateBountyPage />} />
        <Route path="/bounties/:id" element={<BountyDetailPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
