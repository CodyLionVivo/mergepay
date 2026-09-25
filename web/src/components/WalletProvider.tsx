import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
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

import type {
  WalletContextValue,
  WalletStatus,
} from '../stellar/walletContext'


/* =========================================================
   TYPES
   ========================================================= */

interface WalletSnapshot {
  status: WalletStatus
  address: string | null
  network: string | null
  error: string | null
}


/* =========================================================
   HELPERS
   ========================================================= */

function snapshot(
  status: WalletStatus,
  error: string | null = null,
): WalletSnapshot {
  return {
    status,
    address: null,
    network: null,
    error,
  }
}


function describe(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'Freighter returned an unexpected error.'
}


/* =========================================================
   NETWORK VALIDATION
   ========================================================= */

/**
 * Con una address ya autorizada,
 * determina si Freighter esta usando Testnet.
 */
async function withNetwork(
  address: string,
): Promise<WalletSnapshot> {
  const details = await readFreighterNetwork()

  return {
    status:
      details.networkPassphrase === TESTNET_PASSPHRASE
        ? 'connected'
        : 'wrong-network',

    address,

    network: details.network,

    error: null,
  }
}


/* =========================================================
   PASSIVE WALLET READ
   ========================================================= */

/**
 * Lee el estado actual de Freighter sin abrir
 * ningun popup.
 *
 * Solo devuelve una wallet cuando la dApp
 * ya fue autorizada anteriormente.
 */
async function readWalletSnapshot(): Promise<WalletSnapshot> {
  try {
    const installed =
      await isFreighterInstalled()

    if (!installed) {
      return snapshot('unavailable')
    }


    const allowed =
      await isFreighterAllowed()

    if (!allowed) {
      return snapshot('disconnected')
    }


    const address =
      await readFreighterAddress()


    /*
     * Freighter puede estar autorizado,
     * pero bloqueado.
     *
     * En ese caso lo tratamos como
     * desconectado dentro de MergePay.
     */
    if (address === null) {
      return snapshot('disconnected')
    }


    return await withNetwork(address)

  } catch (error) {

    return snapshot(
      'error',
      describe(error),
    )

  }
}


/* =========================================================
   EXPLICIT CONNECTION
   ========================================================= */

/**
 * Conexion solicitada por el usuario.
 *
 * Esta funcion SI puede abrir el popup
 * de Freighter.
 */
async function connectWallet(): Promise<WalletSnapshot> {
  try {
    const installed =
      await isFreighterInstalled()

    if (!installed) {
      return snapshot('unavailable')
    }


    const address =
      await requestFreighterAddress()


    return await withNetwork(address)

  } catch (error) {

    return snapshot(
      'error',
      describe(error),
    )

  }
}


/* =========================================================
   PROVIDER
   ========================================================= */

export function WalletProvider({
  children,
}: {
  children: ReactNode
}) {

  const [initializing, setInitializing] =
    useState(true)


  const [wallet, setWallet] =
    useState<WalletSnapshot>(() =>
      snapshot('disconnected'),
    )


  /*
   * Identificador de operaciones.
   *
   * Evita que una lectura vieja de Freighter
   * sobrescriba una accion mas reciente.
   *
   * Ejemplo:
   *
   * 1. inicia refresh
   * 2. usuario pulsa Change wallet
   * 3. refresh termina tarde
   *
   * Sin este control la wallet podria
   * volver a aparecer.
   */
  const latestRequest =
    useRef(0)


  /* =======================================================
     REFRESH
     ======================================================= */

  const refresh =
    useCallback(async () => {

      const request =
        ++latestRequest.current


      const next =
        await readWalletSnapshot()


      if (
        request ===
        latestRequest.current
      ) {

        setWallet(next)

        setInitializing(false)

      }

    }, [])


  /* =======================================================
     CONNECT
     ======================================================= */

  const connect =
    useCallback(async () => {

      const request =
        ++latestRequest.current


      /*
       * Conservamos temporalmente la address
       * mientras se procesa la conexion.
       */
      setWallet((current) => ({
        ...current,

        status: 'connecting',

        error: null,
      }))


      const next =
        await connectWallet()


      if (
        request ===
        latestRequest.current
      ) {

        setWallet(next)

        setInitializing(false)

      }

    }, [])


  /* =======================================================
     DISCONNECT / CHANGE WALLET
     ======================================================= */

  const disconnect =
    useCallback(async () => {

      /*
       * Invalidamos cualquier refresh/connect
       * que siga ejecutandose.
       *
       * De esta forma una operacion anterior
       * no puede volver a colocar la address
       * despues de pulsar Change wallet.
       */
      ++latestRequest.current


      /*
       * IMPORTANTE:
       *
       * Esto desconecta la wallet de la interfaz
       * de MergePay.
       *
       * NO elimina la cuenta Stellar.
       * NO elimina fondos.
       * NO modifica informacion on-chain.
       * NO elimina Freighter.
       */
      setWallet(
        snapshot('disconnected'),
      )


      setInitializing(false)

    }, [])


  /* =======================================================
     INITIAL WALLET RESTORE
     ======================================================= */

  useEffect(() => {

    /*
     * Al montar la aplicacion hacemos
     * solamente una lectura pasiva.
     *
     * Nunca abrimos Freighter automaticamente.
     */
    const request =
      ++latestRequest.current


    void readWalletSnapshot()
      .then((next) => {

        if (
          request ===
          latestRequest.current
        ) {

          setWallet(next)

          setInitializing(false)

        }

      })

  }, [])


  /* =======================================================
     CONTEXT VALUE
     ======================================================= */

  const value =
    useMemo<WalletContextValue>(
      () => ({
        ...wallet,

        initializing,

        connect,

        refresh,

        disconnect,
      }),

      [
        wallet,
        initializing,
        connect,
        refresh,
        disconnect,
      ],
    )


  /* =======================================================
     RENDER
     ======================================================= */

  return (
    <WalletContext.Provider value={value}>
      {children}
    </WalletContext.Provider>
  )
}