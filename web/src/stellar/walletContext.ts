import { createContext, useContext } from 'react'

export type WalletStatus =
  | 'unavailable'
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'wrong-network'
  | 'error'

export interface WalletContextValue {
  status: WalletStatus
  /** Address publica G.... Es el unico dato de la wallet que se guarda. */
  address: string | null
  /** Nombre de la red de Freighter, por ejemplo "TESTNET". */
  network: string | null
  error: string | null
  connect: () => Promise<void>
  refresh: () => Promise<void>
}

export const WalletContext = createContext<WalletContextValue | null>(null)

export function useWallet(): WalletContextValue {
  const value = useContext(WalletContext)

  if (value === null) {
    throw new Error('useWallet must be used inside WalletProvider.')
  }

  return value
}

/** GABC...WXYZ */
export function abbreviateAddress(address: string): string {
  if (address.length <= 10) {
    return address
  }

  return `${address.slice(0, 4)}…${address.slice(-4)}`
}
