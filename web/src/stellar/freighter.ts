/**
 * Capa fina sobre la API publica de Freighter.
 *
 * Freighter nunca lanza: devuelve `{ ..., error }`. Aqui ese patron se traduce
 * a excepciones con mensaje legible. Ninguna clave privada pasa por aqui: solo
 * la address publica G... y XDR de transacciones.
 */

import {
  getAddress,
  getNetworkDetails,
  isAllowed,
  isConnected,
  requestAccess,
  signTransaction,
} from '@stellar/freighter-api'

export class FreighterError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'FreighterError'
  }
}

interface FreighterResult {
  error?: { message?: string }
}

function errorMessage(result: FreighterResult, fallback: string): string | null {
  if (!result.error) {
    return null
  }

  return result.error.message?.trim() || fallback
}

export interface FreighterNetwork {
  network: string
  networkPassphrase: string
}

export interface SignedTransaction {
  signedTxXdr: string
  signerAddress: string
}

/** Si la extension esta instalada. No abre ningun popup. */
export async function isFreighterInstalled(): Promise<boolean> {
  const result = await isConnected()

  return !result.error && result.isConnected
}

/** Si esta dapp ya tiene permiso. No abre ningun popup. */
export async function isFreighterAllowed(): Promise<boolean> {
  const result = await isAllowed()

  return !result.error && result.isAllowed
}

/** Pide acceso: abre el popup de Freighter si hace falta. */
export async function requestFreighterAddress(): Promise<string> {
  const result = await requestAccess()
  const message = errorMessage(result, 'Freighter did not grant access.')

  if (message !== null) {
    throw new FreighterError(message)
  }

  if (!result.address) {
    throw new FreighterError('Freighter did not return an address.')
  }

  return result.address
}

/** Address ya autorizada, o null si Freighter esta bloqueado. Sin popup. */
export async function readFreighterAddress(): Promise<string | null> {
  const result = await getAddress()

  if (result.error || !result.address) {
    return null
  }

  return result.address
}

export async function readFreighterNetwork(): Promise<FreighterNetwork> {
  const result = await getNetworkDetails()
  const message = errorMessage(result, 'Unable to read the Freighter network.')

  if (message !== null) {
    throw new FreighterError(message)
  }

  return { network: result.network, networkPassphrase: result.networkPassphrase }
}

export async function signWithFreighter(
  transactionXdr: string,
  address: string,
  networkPassphrase: string,
): Promise<SignedTransaction> {
  const result = await signTransaction(transactionXdr, { networkPassphrase, address })
  const message = errorMessage(result, 'Freighter could not sign the transaction.')

  if (message !== null) {
    throw new FreighterError(message)
  }

  if (!result.signedTxXdr) {
    throw new FreighterError('Freighter returned no signed transaction.')
  }

  return { signedTxXdr: result.signedTxXdr, signerAddress: result.signerAddress }
}
