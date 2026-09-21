/**
 * Hash de una transaccion de funding ya enviada y aun sin confirmar por
 * MergePay, guardado en sessionStorage para sobrevivir a un refresh.
 *
 * Solo se guarda el hash: nunca XDR, claves ni datos de la wallet.
 */

import { readSessionItem, removeSessionItem, writeSessionItem } from './sessionStore'

const HASH_PATTERN = /^[0-9a-fA-F]{64}$/

function storageKey(bountyId: number): string {
  return `mergepay:funding-tx:${bountyId}`
}

export function readPendingFundingHash(bountyId: number): string | null {
  const value = readSessionItem(storageKey(bountyId))

  if (value === null) {
    return null
  }

  if (HASH_PATTERN.test(value)) {
    return value.toLowerCase()
  }

  // Un valor que no es un hash no sirve para recuperar nada: se descarta.
  removeSessionItem(storageKey(bountyId))

  return null
}

export function storePendingFundingHash(bountyId: number, transactionHash: string): void {
  writeSessionItem(storageKey(bountyId), transactionHash.toLowerCase())
}

export function clearPendingFundingHash(bountyId: number): void {
  removeSessionItem(storageKey(bountyId))
}
