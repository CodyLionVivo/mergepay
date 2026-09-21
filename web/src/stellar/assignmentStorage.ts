/**
 * Aceptacion ya enviada a Stellar y aun sin confirmar por MergePay, guardada
 * en sessionStorage para sobrevivir a un refresh.
 *
 * Solo datos publicos: el hash de la transaccion, el usuario de GitHub, la
 * address G del developer y, cuando ya existe, su firma de propiedad. Nunca
 * XDR ni claves.
 */

import { normalizeSignatureBase64 } from '../utils/base64'
import { isValidGithubUsername } from '../utils/github'
import { readSessionItem, removeSessionItem, writeSessionItem } from './sessionStore'

export interface PendingAssignment {
  transactionHash: string
  developerGithub: string
  /** Wallet que acepto: solo ella puede firmar la prueba de propiedad. */
  developerAddress: string
  /** null mientras falte firmar la prueba de propiedad. */
  walletSignature: string | null
}

const HASH_PATTERN = /^[0-9a-fA-F]{64}$/

/** Address de cuenta Stellar: G seguida de 55 caracteres base32. */
const ACCOUNT_PATTERN = /^G[A-Z2-7]{55}$/

function storageKey(bountyId: number): string {
  return `mergepay:assignment:${bountyId}`
}

function parse(raw: string): PendingAssignment | null {
  let value: unknown

  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }

  const candidate = value as Partial<Record<keyof PendingAssignment, unknown>> | null

  if (
    typeof candidate?.transactionHash !== 'string' ||
    typeof candidate.developerGithub !== 'string' ||
    typeof candidate.developerAddress !== 'string' ||
    !HASH_PATTERN.test(candidate.transactionHash) ||
    !isValidGithubUsername(candidate.developerGithub) ||
    !ACCOUNT_PATTERN.test(candidate.developerAddress)
  ) {
    return null
  }

  // Una firma corrupta no invalida la aceptacion, que ya esta en Stellar: se
  // descarta solo la firma y el usuario puede volver a firmar.
  const walletSignature =
    typeof candidate.walletSignature === 'string'
      ? normalizeSignatureBase64(candidate.walletSignature)
      : null

  return {
    transactionHash: candidate.transactionHash.toLowerCase(),
    developerGithub: candidate.developerGithub.trim(),
    developerAddress: candidate.developerAddress,
    walletSignature,
  }
}

export function readPendingAssignment(bountyId: number): PendingAssignment | null {
  const raw = readSessionItem(storageKey(bountyId))

  if (raw === null) {
    return null
  }

  const pending = parse(raw)

  // Un valor corrupto no sirve para recuperar nada: se descarta.
  if (pending === null) {
    removeSessionItem(storageKey(bountyId))
  }

  return pending
}

export function storePendingAssignment(bountyId: number, pending: PendingAssignment): void {
  const value: PendingAssignment = {
    transactionHash: pending.transactionHash.toLowerCase(),
    developerGithub: pending.developerGithub.trim(),
    developerAddress: pending.developerAddress,
    walletSignature: pending.walletSignature,
  }

  writeSessionItem(storageKey(bountyId), JSON.stringify(value))
}

export function clearPendingAssignment(bountyId: number): void {
  removeSessionItem(storageKey(bountyId))
}
