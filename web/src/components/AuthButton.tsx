import { AlertTriangle, Loader, Lock, LogOut, RotateCcw } from 'lucide-react'
import { useAuth } from '../auth/authContext'
import { abbreviateAddress, useWallet } from '../stellar/walletContext'
import './AuthButton.css'

/**
 * Sesion de wallet en el header. Sin menus: iniciar sesion, o verla y cerrarla.
 *
 * Sin wallet conectada no se ofrece autenticacion: firmar necesita Freighter.
 */
export function AuthButton() {
  const auth = useAuth()
  const wallet = useWallet()

  if (auth.status === 'authenticated' && auth.wallet !== null) {
    return (
      <span className="auth-chip" title={auth.wallet}>
        <Lock size={13} aria-hidden="true" />
        <span className="auth-chip__label">Authenticated</span>
        <span className="auth-chip__address">{abbreviateAddress(auth.wallet)}</span>
        <button
          type="button"
          className="auth-chip__action"
          onClick={() => void auth.signOut()}
        >
          <LogOut size={13} aria-hidden="true" />
          Sign out
        </button>
      </span>
    )
  }

  if (auth.status === 'checking') {
    return (
      <button type="button" className="auth-button" disabled>
        <Loader size={14} aria-hidden="true" />
        Checking session...
      </button>
    )
  }

  if (auth.status === 'signing') {
    return (
      <button type="button" className="auth-button" disabled>
        <Loader size={14} aria-hidden="true" />
        Signing in...
      </button>
    )
  }

  // El error de restaurar una sesion guardada se reintenta, no se re-firma.
  if (auth.status === 'error' && auth.wallet === null && wallet.status !== 'connected') {
    return (
      <button
        type="button"
        className="auth-button auth-button--warning"
        onClick={() => void auth.refresh()}
        title={auth.error ?? undefined}
      >
        <RotateCcw size={14} aria-hidden="true" />
        Retry session
      </button>
    )
  }

  if (wallet.status !== 'connected' || wallet.address === null) {
    return null
  }

  return (
    <button
      type="button"
      className={`auth-button${auth.status === 'error' ? ' auth-button--warning' : ''}`}
      onClick={() => void auth.signIn()}
      title={auth.error ?? 'Sign a message to prove you control this wallet.'}
    >
      {auth.status === 'error' ? (
        <AlertTriangle size={14} aria-hidden="true" />
      ) : (
        <Lock size={14} aria-hidden="true" />
      )}
      Sign in
    </button>
  )
}
