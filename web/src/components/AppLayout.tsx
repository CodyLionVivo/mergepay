import { t, useI18n } from '../i18n'
import { useEffect, useState } from 'react'
import { Menu, Moon, Sun, X } from 'lucide-react'
import { Link, Outlet, useLocation } from 'react-router-dom'
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

type Theme = 'light' | 'dark'

const MIN_LOADER_DURATION = 4_500

export function AppLayout() {
  useI18n()

  const auth = useAuth()
  const wallet = useWallet()

  const [expanded, setExpanded] = useState(false)

  const [minimumLoaderTimeFinished, setMinimumLoaderTimeFinished] =
    useState(false)

  const [theme, setTheme] = useState<Theme>(() => {
    const storedTheme =
      window.localStorage.getItem('mergepay-theme')

    return storedTheme === 'dark'
      ? 'dark'
      : 'light'
  })

  const { pathname } = useLocation()

  /* =======================================================
     INITIAL LOADER
     ======================================================= */

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setMinimumLoaderTimeFinished(true)
    }, MIN_LOADER_DURATION)

    return () => {
      window.clearTimeout(timer)
    }
  }, [])

  const showLoader =
    !minimumLoaderTimeFinished ||
    auth.status === 'checking' ||
    wallet.initializing

  /* =======================================================
     THEME
     ======================================================= */

  useEffect(() => {
    document.documentElement.dataset.theme = theme

    window.localStorage.setItem(
      'mergepay-theme',
      theme,
    )
  }, [theme])

  const toggleTheme = () => {
    setTheme((currentTheme) =>
      currentTheme === 'light'
        ? 'dark'
        : 'light',
    )
  }

  /* =======================================================
     LOADER SCREEN
     ======================================================= */

  /*
   * Mientras MergePay restaura la sesión,
   * solamente mostramos el loader.
   *
   * Navbar, contenido, footer y API status
   * todavía no se renderizan.
   */
  if (showLoader) {
    return <AppLoader />
  }

  /* =======================================================
     APPLICATION
     ======================================================= */

  return (
    <div className="app">

      <a
        className="skip-link"
        href="#main-content"
      >
        {t('Skip to content')}
      </a>

      {/* ===================================================
          HEADER
          =================================================== */}

      <header className="app__header">

        <div
          className="shell app__header-inner"
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setExpanded(false)

              document
                .getElementById('navigation-toggle')
                ?.focus()
            }
          }}
        >

          {/* BRAND */}

          <Link
            to="/"
            className="brand"
            aria-label={t('MergePay home')}
            onClick={() => setExpanded(false)}
          >
            <Brand />
          </Link>


          {/* NETWORK */}

          <span className="network-label">
            Testnet
          </span>


          {/* LANGUAGE */}

          <LanguageSelector />


          {/* THEME */}

          <button
            type="button"
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={
              theme === 'light'
                ? t('Switch to dark mode')
                : t('Switch to light mode')
            }
          >

            {theme === 'light' ? (
              <>
                <Sun
                  size={16}
                  aria-hidden="true"
                />

                <span>
                  {t('Light')}
                </span>
              </>
            ) : (
              <>
                <Moon
                  size={16}
                  aria-hidden="true"
                />

                <span>
                  {t('Dark')}
                </span>
              </>
            )}

          </button>


          {/* MOBILE MENU */}

          <button
            id="navigation-toggle"
            className="nav-toggle"
            type="button"
            aria-expanded={expanded}
            aria-controls="app-navigation"
            onClick={() =>
              setExpanded(!expanded)
            }
          >

            {expanded ? (
              <X size={20} />
            ) : (
              <Menu size={20} />
            )}

            <span className="visually-hidden">
              {t('Navigation and account')}
            </span>

          </button>


          {/* ACCOUNT AREA */}

          <div
            id="app-navigation"
            className={
              expanded
                ? 'app__navigation is-expanded'
                : 'app__navigation'
            }
          >

            <div className="app__status">

              <WalletButton />

              <AuthButton />

            </div>

          </div>

        </div>

      </header>


      {/* ===================================================
          CONTENT
          =================================================== */}

      <main
        id="main-content"
        className="app__main"
        tabIndex={-1}
        key={pathname}
      >
        <Outlet />
      </main>


      {/* ===================================================
          FOOTER
          =================================================== */}

      <footer className="shell app__footer">

        <span>
          {t('Verified code. Secured rewards.')}
        </span>

        <ApiStatus />

      </footer>

    </div>
  )
}