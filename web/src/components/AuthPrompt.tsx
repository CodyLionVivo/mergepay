import { AlertTriangle, Loader, Lock } from 'lucide-react'
import { useAuth } from '../auth/authContext'
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
  const auth = useAuth()

  const canSignIn = auth.status !== 'authenticated' && auth.status !== 'checking'

  return (
    <div className="action-panel__blocked">
      <p className="action-panel__blocked-title">{message}</p>
      {hint !== undefined ? <p className="action-panel__hint">{hint}</p> : null}

      {canSignIn ? (
        <div className="action-panel__action">
          <button
            type="button"
            className="button button--primary"
            onClick={() => void auth.signIn()}
            disabled={auth.status === 'signing'}
          >
            {auth.status === 'signing' ? (
              <>
                <Loader size={16} aria-hidden="true" />
                Signing in...
              </>
            ) : (
              <>
                <Lock size={16} aria-hidden="true" />
                Sign in with your wallet
              </>
            )}
          </button>
          <span className="action-panel__hint">
            Freighter will ask you to sign a message. No transaction, no fees.
          </span>
        </div>
      ) : null}

      {auth.status === 'error' && auth.error !== null ? (
        <p className="action-panel__error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          {auth.error}
        </p>
      ) : null}
    </div>
  )
}
