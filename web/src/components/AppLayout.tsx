import { t, useI18n } from '../i18n'
import { useEffect, useState } from 'react'
import { Menu, X } from 'lucide-react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Brand } from './Brand'
import { LanguageSelector } from '../i18n/LanguageSelector'
import { AppLoader } from './AppLoader'
import { useWallet } from '../stellar/walletContext'
import { useAuth } from '../auth/authContext'
import { ApiStatus } from './ApiStatus'
import { AuthButton } from './AuthButton'
import { WalletButton } from './WalletButton'
import './AppLayout.css'
import './InitialLoader.css'

// Temporal: mínimo de desarrollo para revisar visualmente la animación inicial.
const MIN_LOADER_DURATION = 10_000

export function AppLayout() {
  useI18n()
  const auth = useAuth()
  const wallet = useWallet()
  const [expanded, setExpanded] = useState(false)
  const [minimumLoaderTimeFinished, setMinimumLoaderTimeFinished] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => setMinimumLoaderTimeFinished(true), MIN_LOADER_DURATION)
    return () => window.clearTimeout(timer)
  }, [])
  const showLoader = !minimumLoaderTimeFinished || auth.status === 'checking' || wallet.initializing
  const { pathname } = useLocation()
  return (
    <div className="app">
      <a className="skip-link" href="#main-content">{t("Skip to content")}</a>
      <header className="app__header">
        <div className="shell app__header-inner" onKeyDown={(event) => {
          if (event.key === 'Escape') { setExpanded(false); document.getElementById('navigation-toggle')?.focus() }
        }}>
          <Link to="/" className="brand" aria-label={t("MergePay home")} onClick={() => setExpanded(false)}>
            <Brand />
          </Link>
          <span className="network-label">Testnet</span>
          <LanguageSelector />
          <button id="navigation-toggle" className="nav-toggle" type="button" aria-expanded={expanded} aria-controls="app-navigation" onClick={() => setExpanded(!expanded)}>
            {expanded ? <X size={20} /> : <Menu size={20} />}<span className="visually-hidden">{t("Navigation and account")}</span>
          </button>
          <div id="app-navigation" className={expanded ? "app__navigation is-expanded" : 'app__navigation'}>
            <nav className="app__nav" aria-label={t("Main")}>
              <NavLink to="/" end className={({ isActive }) => isActive ? "app__nav-link app__nav-link--active" : 'app__nav-link'} onClick={() => setExpanded(false)}>{t("Explore")}</NavLink>
              <NavLink to="/bounties/new" className={({ isActive }) => isActive ? "app__nav-link app__nav-link--active" : 'app__nav-link'} onClick={() => setExpanded(false)}>{t("Create bounty")}</NavLink>
            </nav>
            <div className="app__status"><WalletButton /><AuthButton /></div>
          </div>
        </div>
      </header>
      <main id="main-content" className="app__main" tabIndex={-1} key={pathname}>
        {showLoader ? <AppLoader /> : null}
        {/* Mounted even under the loader: data requests and session restoration run normally. */}
        <div hidden={showLoader} inert={showLoader} aria-hidden={showLoader || undefined}>
          <Outlet />
        </div>
      </main>
      <footer className="shell app__footer"><span>{t("Verified code. Secured rewards.")}</span><ApiStatus /></footer>
    </div>
  )
}
