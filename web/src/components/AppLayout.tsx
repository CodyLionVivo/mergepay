import { useState } from 'react'
import { GitMerge, Menu, X } from 'lucide-react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { ApiStatus } from './ApiStatus'
import { AuthButton } from './AuthButton'
import { WalletButton } from './WalletButton'
import './AppLayout.css'

export function AppLayout() {
  const [expanded, setExpanded] = useState(false)
  const { pathname } = useLocation()
  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="app__header">
        <div className="shell app__header-inner" onKeyDown={(event) => {
          if (event.key === 'Escape') { setExpanded(false); document.getElementById('navigation-toggle')?.focus() }
        }}>
          <Link to="/" className="brand" aria-label="MergePay home" onClick={() => setExpanded(false)}>
            <span className="brand__symbol"><GitMerge size={21} aria-hidden="true" /></span>
            <span className="brand__name">MergePay</span>
          </Link>
          <span className="network-label">Testnet</span>
          <button id="navigation-toggle" className="nav-toggle" type="button" aria-expanded={expanded} aria-controls="app-navigation" onClick={() => setExpanded(!expanded)}>
            {expanded ? <X size={20} /> : <Menu size={20} />}<span className="visually-hidden">Navigation and account</span>
          </button>
          <div id="app-navigation" className={expanded ? 'app__navigation is-expanded' : 'app__navigation'}>
            <nav className="app__nav" aria-label="Main">
              <NavLink to="/" end className={({ isActive }) => isActive ? 'app__nav-link app__nav-link--active' : 'app__nav-link'} onClick={() => setExpanded(false)}>Explore</NavLink>
              <NavLink to="/bounties/new" className={({ isActive }) => isActive ? 'app__nav-link app__nav-link--active' : 'app__nav-link'} onClick={() => setExpanded(false)}>Create bounty</NavLink>
            </nav>
            <div className="app__status"><WalletButton /><AuthButton /></div>
          </div>
        </div>
      </header>
      <main id="main-content" className="app__main" tabIndex={-1} key={pathname}><Outlet /></main>
      <footer className="shell app__footer"><span>Verified code. Secured rewards.</span><ApiStatus /></footer>
    </div>
  )
}
