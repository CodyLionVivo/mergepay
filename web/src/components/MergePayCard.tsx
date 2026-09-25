import { useId, useState } from 'react'
import type { PointerEvent } from 'react'
import { Lock, RotateCw, Wallet } from 'lucide-react'
import { useAuth } from '../auth/authContext'
import { useI18n } from '../i18n'
import { abbreviateAddress, useWallet } from '../stellar/walletContext'
import { AuthButton } from './AuthButton'
import './MergePayCard.css'

function CardChip() {
  return (
    <svg className="mergepay-card__chip" viewBox="0 0 46 34" aria-hidden="true">
      <rect x="1" y="1" width="44" height="32" rx="7" fill="currentColor" />
      <g fill="none" stroke="#4c4b5e" strokeWidth="1">
        <rect x="15" y="8" width="16" height="18" rx="4" />
        <path d="M15 12H1m14 10H1m30-10h14M31 22h14M19 8V1m8 7V1M19 26v7m8-7v7M8 1l7 7m23-7-7 7M8 33l7-7m23 7-7-7" />
      </g>
    </svg>
  )
}

function Contactless() {
  return (
    <svg className="mergepay-card__contactless" viewBox="0 0 30 34" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M7 13q4 4 0 8M13 9q7 8 0 16M19 5q10 12 0 24" />
      </g>
    </svg>
  )
}

/** Wallet presentation only. No local copy of wallet/auth state, balances or escrow data. */
export function MergePayCard() {
  const { t } = useI18n()
  const wallet = useWallet()
  const auth = useAuth()
  const [flipped, setFlipped] = useState(false)
  const id = useId()
  const connected = wallet.status === 'connected' && wallet.address !== null
  const authenticated = auth.status === 'authenticated'
  const matchingSession = connected && authenticated && auth.wallet === wallet.address
  const sessionLabel = auth.status === 'checking' ? 'Checking session...'
    : auth.status === 'signing' ? 'Signing in...'
    : authenticated ? 'Authenticated' : 'Authentication required'
  const walletLabel = wallet.status === 'wrong-network' ? 'Wrong network'
    : connected ? 'Connected' : 'Wallet disconnected'
  const network = wallet.status === 'wrong-network' ? wallet.network : 'Stellar Testnet'

  function hover(event: PointerEvent<HTMLButtonElement>, next: boolean) {
    // React controls both the 3D face and its accessibility state. Touch never uses hover.
    if (event.pointerType === 'mouse' && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
      setFlipped(next)
    }
  }

  return (
    <section className="mergepay-wallet" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className="mergepay-wallet__title">{t('Wallet / escrow')}</h2>
      <button
        type="button"
        className={`flip-card mergepay-card${flipped ? ' is-flipped' : ''}`}
        aria-label={t('Flip wallet card')}
        aria-pressed={flipped}
        aria-describedby={`${id}-hint`}
        onPointerEnter={event => hover(event, true)}
        onPointerLeave={event => hover(event, false)}
        onClick={() => setFlipped(current => !current)}
        onKeyDown={event => { if (event.key === 'Escape') setFlipped(false) }}
      >
        <span className="flip-card-inner">
          <span className="flip-card-front" aria-hidden={flipped}>
            <span className="mergepay-card__brand"><img src="/Logo.svg" alt="" />MergePay</span>
            <span className="mergepay-card__hardware"><CardChip /><Contactless /></span>
            {network ? <span className="mergepay-card__network">{network}</span> : null}
            <span className="mergepay-card__address" title={wallet.address ?? undefined}>
              {wallet.address ? abbreviateAddress(wallet.address) : t('Not connected')}
            </span>
            <span className="mergepay-card__state">{t(connected ? sessionLabel : walletLabel)}</span>
          </span>
          <span className="flip-card-back" aria-hidden={!flipped}>
            <span className="mergepay-card__stripe" />
            <span className="mergepay-card__back-content">
              <span className="mergepay-card__back-title">{t('Escrow')}</span>
              <span className="mergepay-card__signature-strip">{t(walletLabel)}</span>
              <span className="mergepay-card__session">{t(sessionLabel)}</span>
              <span className="mergepay-card__back-footer"><span>{network}</span><span>MergePay</span></span>
            </span>
          </span>
        </span>
      </button>
      <p id={`${id}-hint`} className="mergepay-wallet__hint"><RotateCw size={12} aria-hidden="true" />{t('Tap or press Enter to flip')}</p>
      <div className="mergepay-wallet__control" aria-live="polite">
        {!connected ? (
          <>
            <button className="button button--secondary" type="button" disabled={wallet.initializing || wallet.status === 'connecting'}
              onClick={() => void (wallet.status === 'wrong-network' ? wallet.refresh() : wallet.connect())}>
              <Wallet size={15} aria-hidden="true" />
              {t(wallet.initializing || wallet.status === 'connecting' ? 'Connecting...' : wallet.status === 'wrong-network' ? 'Check network again' : 'Connect wallet')}
            </button>
            {wallet.status === 'unavailable' ? <p className="mergepay-wallet__notice">{t('Install the Freighter extension, then click to check again.')}</p> : null}
            {wallet.status === 'wrong-network' ? <p className="mergepay-wallet__notice">{t('Switch Freighter to Testnet')}</p> : null}
          </>
        ) : matchingSession ? (
          <p className="mergepay-wallet__authenticated"><span aria-hidden="true" />{t('Authenticated')}<code title={wallet.address!}>{abbreviateAddress(wallet.address!)}</code></p>
        ) : authenticated ? (
          <p className="mergepay-wallet__notice">{t('Switch to your authenticated wallet.')}</p>
        ) : (
          <><p className="mergepay-wallet__notice"><Lock size={13} aria-hidden="true" />{t('Authentication required')}</p><AuthButton /></>
        )}
        {wallet.status === 'error' && wallet.error ? <p className="mergepay-wallet__notice" role="alert">{t(wallet.error)}</p> : null}
        {connected && auth.status === 'error' && auth.error ? <p className="mergepay-wallet__notice" role="alert">{t(auth.error)}</p> : null}
      </div>
    </section>
  )
}
