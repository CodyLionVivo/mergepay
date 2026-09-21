import { GitMerge } from 'lucide-react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { ApiStatus } from './ApiStatus'
import { WalletButton } from './WalletButton'
import './AppLayout.css'

const NAV_ITEMS = [
  { to: '/', label: 'Explore Tasks', end: true },
  { to: '/bounties/new', label: 'Create Task', end: false },
]

export function AppLayout() {
  return (
    <div className="app">
      <header className="app__header">
        <div className="shell app__header-inner">
          <Link to="/" className="brand" aria-label="MergePay home">
            <GitMerge className="brand__mark" size={20} aria-hidden="true" />
            <span className="brand__name">MergePay</span>
          </Link>

          <nav className="app__nav" aria-label="Main">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  isActive ? 'app__nav-link app__nav-link--active' : 'app__nav-link'
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="app__status">
            <ApiStatus />
            <WalletButton />
          </div>
        </div>
      </header>

      <main className="app__main">
        <Outlet />
      </main>
    </div>
  )
}
