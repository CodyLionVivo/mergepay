import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  ApiError,
  createAuthChallenge,
  getAuthMe,
  logoutAuth,
  requestErrorMessage,
  setAccessToken,
  verifyAuthChallenge,
} from '../api/client'
import { AuthContext } from '../auth/authContext'
import type { AuthContextValue, AuthStatus } from '../auth/authContext'
import {
  clearStoredSession,
  isExpired,
  readStoredSession,
  storeSession,
} from '../auth/authStorage'
import type { StoredAuthSession } from '../auth/authStorage'
import { TESTNET_PASSPHRASE } from '../stellar/config'
import { signMessageWithFreighter } from '../stellar/freighter'
import { useWallet } from '../stellar/walletContext'

interface AuthState {
  status: AuthStatus
  session: StoredAuthSession | null
  error: string | null
}

const ANONYMOUS: AuthState = { status: 'anonymous', session: null, error: null }

/**
 * Estado con el que arranca el provider, derivado de lo guardado.
 *
 * Una sesion caducada se descarta sin preguntar al backend; una viva queda en
 * "checking" hasta que /auth/me la confirme.
 */
function initialState(): AuthState {
  const stored = readStoredSession()

  if (stored === null) {
    return ANONYMOUS
  }

  if (isExpired(stored)) {
    clearStoredSession()

    return ANONYMOUS
  }

  setAccessToken(stored.accessToken)

  return { status: 'checking', session: stored, error: null }
}

/**
 * El rechazo de Freighter trae su propio mensaje y merece mostrarse; un fallo
 * de red (TypeError de fetch) se sustituye por el texto generico.
 */
function signInErrorMessage(caught: unknown): string {
  if (
    !(caught instanceof ApiError) &&
    caught instanceof Error &&
    !(caught instanceof TypeError) &&
    caught.message !== ''
  ) {
    return caught.message
  }

  return requestErrorMessage(caught)
}

/** Resultado de comprobar contra el backend una sesion guardada. */
type CheckOutcome =
  | { kind: 'authenticated'; session: StoredAuthSession }
  | { kind: 'rejected' }
  | { kind: 'unreachable'; session: StoredAuthSession; error: string }

/**
 * Pregunta al backend por la sesion guardada y devuelve que hacer con ella.
 *
 * No toca estado de React: asi quien la llama decide cuando aplicarlo, y el
 * efecto de montaje puede hacerlo dentro del callback de la promesa.
 */
async function inspectStoredSession(
  stored: StoredAuthSession,
): Promise<CheckOutcome> {
  setAccessToken(stored.accessToken)

  try {
    const me = await getAuthMe()

    return {
      kind: 'authenticated',
      session: { ...stored, wallet: me.wallet, expiresAtUnix: me.expires_at_unix },
    }
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      // El backend ya no la reconoce: conservarla no sirve de nada.
      return { kind: 'rejected' }
    }

    // Otro fallo (red, 5xx): se conserva por si vuelve, y se avisa.
    return { kind: 'unreachable', session: stored, error: requestErrorMessage(caught) }
  }
}

interface AuthProviderProps {
  children: ReactNode
}

/**
 * Sesion de wallet: un challenge del backend firmado con SEP-53.
 *
 * No hay contrasenas ni cookies. El token vive en sessionStorage y en el
 * cliente HTTP; nunca se muestra ni se registra. La identidad es la address.
 */
export function AuthProvider({ children }: AuthProviderProps) {
  const wallet = useWallet()

  const [state, setState] = useState<AuthState>(initialState)

  // Evita dos firmas simultaneas.
  const signing = useRef(false)

  const adopt = useCallback((session: StoredAuthSession) => {
    setAccessToken(session.accessToken)
    storeSession(session)
    setState({ status: 'authenticated', session, error: null })
  }, [])

  const forget = useCallback(() => {
    setAccessToken(null)
    clearStoredSession()
    setState(ANONYMOUS)
  }, [])

  const applyOutcome = useCallback(
    (outcome: CheckOutcome) => {
      if (outcome.kind === 'authenticated') {
        adopt(outcome.session)

        return
      }

      if (outcome.kind === 'rejected') {
        forget()

        return
      }

      setState({ status: 'error', session: outcome.session, error: outcome.error })
    },
    [adopt, forget],
  )

  // Al montar se comprueba la sesion guardada. Nunca se abre Freighter aqui.
  useEffect(() => {
    const stored = readStoredSession()

    if (stored !== null && !isExpired(stored)) {
      void inspectStoredSession(stored).then(applyOutcome)
    }
  }, [applyOutcome])

  const refresh = useCallback(async () => {
    const stored = readStoredSession()

    if (stored === null || isExpired(stored)) {
      forget()

      return
    }

    applyOutcome(await inspectStoredSession(stored))
  }, [applyOutcome, forget])

  /** Cierra la sesion en el backend si puede, y siempre en local. */
  const revoke = useCallback(async () => {
    try {
      await logoutAuth()
    } catch {
      // Best-effort: cerrar sesion nunca debe fallar en la UI.
    }

    forget()
  }, [forget])

  const signIn = useCallback(async () => {
    const address = wallet.address

    // Firmar exige Freighter conectada y en Testnet; el boton ya lo refleja.
    if (signing.current || wallet.status !== 'connected' || address === null) {
      return
    }

    signing.current = true
    setState({ status: 'signing', session: null, error: null })

    try {
      const challenge = await createAuthChallenge(address)

      // Se firma exactamente el mensaje del backend, sin reconstruirlo.
      const signed = await signMessageWithFreighter(
        challenge.message,
        address,
        TESTNET_PASSPHRASE,
      )

      if (signed.signerAddress !== address) {
        throw new Error('Freighter signed with a different account.')
      }

      const created = await verifyAuthChallenge(
        challenge.challenge_id,
        signed.signature,
      )

      if (created.wallet !== address) {
        throw new Error('The session was issued for a different wallet.')
      }

      adopt({
        accessToken: created.access_token,
        wallet: created.wallet,
        expiresAtUnix: created.expires_at_unix,
      })
    } catch (caught) {
      setAccessToken(null)
      clearStoredSession()
      setState({
        status: 'error',
        session: null,
        error: signInErrorMessage(caught),
      })
    } finally {
      signing.current = false
    }
  }, [adopt, wallet.address, wallet.status])

  // Cambio de wallet en Freighter: la sesion anterior deja de valer. Si
  // Freighter solo esta bloqueada (sin address), no se revoca nada.
  const connectedAddress = wallet.address
  const sessionWallet = state.session?.wallet ?? null

  useEffect(() => {
    if (
      connectedAddress === null ||
      sessionWallet === null ||
      connectedAddress === sessionWallet
    ) {
      return
    }

    // Best-effort: se revoca en el backend y se olvida en local pase lo que pase.
    void logoutAuth()
      .catch(() => undefined)
      .then(forget)
  }, [connectedAddress, sessionWallet, forget])

  const authenticated = state.status === 'authenticated' ? state.session : null

  const value: AuthContextValue = {
    status: state.status,
    wallet: authenticated?.wallet ?? null,
    expiresAtUnix: authenticated?.expiresAtUnix ?? null,
    error: state.error,
    signIn,
    signOut: revoke,
    refresh,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
