import { t, useI18n } from '../i18n'
import { AlertTriangle, Loader, Lock } from 'lucide-react'
import { useAuth } from '../auth/authContext'
import { useWallet } from '../stellar/walletContext'
import { WalletButton } from './WalletButton'
import './ActionPanel.css'

interface AuthPromptProps {
  /** Que hace falta para continuar, en una linea. */
  message: string
  hint?: string
}

/**
 * Bloqueo por sesion dentro de un panel de accion.
 *
 * Ofrece iniciar sesion cuando no hay ninguna; si la sesion existe pero es de
 * otra wallet, solo explica que hay que cambiarla: firmar de nuevo con la
 * misma wallet no arreglaria nada.
 */
export function AuthPrompt({ message, hint }: AuthPromptProps) {
  useI18n()
  const auth = useAuth()
  const wallet = useWallet()

  const canSignIn = auth.status !== 'authenticated' && auth.status !== 'checking'

  return (
    <div className="action-panel__blocked">
      <p className="action-panel__blocked-title">{t(message)}</p>
      {hint !== undefined ? <p className="action-panel__hint">{t(hint)}</p> : null}

      {canSignIn && wallet.status !== 'connected' ? <WalletButton /> : canSignIn ? (
        <div className="action-panel__action">
          <button
            type="button"
            className="button button--primary"
            onClick={() => void auth.signIn()}
            disabled={auth.status === 'signing'}
          >
            {auth.status === 'signing' ? (
              <>
                <Loader size={16} aria-hidden="true" />{t("Signing in...")}</>
            ) : (
              <>
                <Lock size={16} aria-hidden="true" />{t("Sign in with your wallet")}</>
            )}
          </button>
          <span className="action-panel__hint">{t("Freighter will ask you to sign a message. No transaction, no fees.")}</span>
        </div>
      ) : null}

      {auth.status === 'error' && auth.error !== null ? (
        <p className="action-panel__error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          {t(auth.error)}
        </p>
      ) : null}
    </div>
  )
}
