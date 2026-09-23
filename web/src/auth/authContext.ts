import { createContext, useContext } from 'react'

export type AuthStatus =
  /** Restaurando una sesion guardada al montar. */
  | 'checking'
  | 'anonymous'
  /** Esperando la firma en Freighter. */
  | 'signing'
  | 'authenticated'
  | 'error'

export interface AuthContextValue {
  status: AuthStatus
  /** Wallet de la sesion. El token nunca sale del cliente HTTP. */
  wallet: string | null
  expiresAtUnix: number | null
  error: string | null
  signIn: () => Promise<void>
  signOut: () => Promise<void>
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)

  if (value === null) {
    throw new Error('useAuth must be used inside AuthProvider.')
  }

  return value
}
