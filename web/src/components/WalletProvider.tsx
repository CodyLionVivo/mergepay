import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { TESTNET_PASSPHRASE } from '../stellar/config'
import {
  isFreighterAllowed,
  isFreighterInstalled,
  readFreighterAddress,
  readFreighterNetwork,
  requestFreighterAddress,
} from '../stellar/freighter'
import { WalletContext } from '../stellar/walletContext'
import type { WalletContextValue, WalletStatus } from '../stellar/walletContext'

interface WalletSnapshot {
  status: WalletStatus
  address: string | null
  network: string | null
  error: string | null
}

function snapshot(status: WalletStatus, error: string | null = null): WalletSnapshot {
  return { status, address: null, network: null, error }
}

function describe(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'Freighter returned an unexpected error.'
}

/** Con una address ya autorizada, decide segun la red de Freighter. */
async function withNetwork(address: string): Promise<WalletSnapshot> {
  const details = await readFreighterNetwork()

  return {
    status:
      details.networkPassphrase === TESTNET_PASSPHRASE ? 'connected' : 'wrong-network',
    address,
    network: details.network,
    error: null,
  }
}

/** Estado actual sin abrir ningun popup: solo si la dapp ya estaba autorizada. */
async function readWalletSnapshot(): Promise<WalletSnapshot> {
  try {
    if (!(await isFreighterInstalled())) {
      return snapshot('unavailable')
    }

    if (!(await isFreighterAllowed())) {
      return snapshot('disconnected')
    }

    const address = await readFreighterAddress()

    // Autorizada pero bloqueada: hasta que el usuario la desbloquee, cuenta
    // como desconectada.
    if (address === null) {
      return snapshot('disconnected')
    }

    return await withNetwork(address)
  } catch (error) {
    return snapshot('error', describe(error))
  }
}

/** Conexion explicita: aqui si se abre el popup de Freighter. */
async function connectWallet(): Promise<WalletSnapshot> {
  try {
    if (!(await isFreighterInstalled())) {
      return snapshot('unavailable')
    }

    const address = await requestFreighterAddress()

    return await withNetwork(address)
  } catch (error) {
    return snapshot('error', describe(error))
  }
}

export function WalletProvider({ children }: { children: ReactNode }) {
  const [initializing, setInitializing] = useState(true)
  const [wallet, setWallet] = useState<WalletSnapshot>(() => snapshot('disconnected'))

  // Solo aplica la respuesta de la ultima operacion lanzada, para que una
  // lectura lenta al montar no pise una conexion posterior.
  const latestRequest = useRef(0)

  const refresh = useCallback(async () => {
    const request = ++latestRequest.current
    const next = await readWalletSnapshot()

    if (request === latestRequest.current) {
      setWallet(next)
      setInitializing(false)
    }
  }, [])

  const connect = useCallback(async () => {
    const request = ++latestRequest.current

    setWallet((current) => ({ ...current, status: 'connecting', error: null }))

    const next = await connectWallet()

    if (request === latestRequest.current) {
      setWallet(next)
      setInitializing(false)
    }
  }, [])

  const disconnect = useCallback(() => {
    // Invalida cualquier refresh o conexión pendiente.
    ++latestRequest.current

    // Desconecta la wallet únicamente dentro de MergePay.
    setWallet(snapshot('disconnected'))
    setInitializing(false)
  }, [])

  // Al montar solo se lee: nunca se abre el popup sin un clic del usuario.
  useEffect(() => {
    const request = ++latestRequest.current

    void readWalletSnapshot().then((next) => {
      if (request === latestRequest.current) {
        setWallet(next)
        setInitializing(false)
      }
    })
  }, [])

  const value = useMemo<WalletContextValue>(
    () => ({
      ...wallet,
      initializing,
      connect,
      refresh,
      disconnect,
    }),
    [wallet, initializing, connect, refresh, disconnect],
  )

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>
}
