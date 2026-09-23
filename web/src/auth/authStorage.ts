/**
 * Sesion de wallet guardada para sobrevivir a un refresh.
 *
 * Va en sessionStorage, nunca en localStorage: al cerrar la pestana se pierde.
 * El token no se muestra en la UI ni se escribe en consola; si el navegador
 * bloquea el storage, la sesion vive solo en memoria y se pierde al recargar.
 */

import { readSessionItem, removeSessionItem, writeSessionItem } from '../stellar/sessionStore'

export interface StoredAuthSession {
  accessToken: string
  wallet: string
  expiresAtUnix: number
}

const STORAGE_KEY = 'mergepay:auth-session'

/** Address de cuenta Stellar: G seguida de 55 caracteres base32. */
const ACCOUNT_PATTERN = /^G[A-Z2-7]{55}$/

function parse(raw: string): StoredAuthSession | null {
  let value: unknown

  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }

  const candidate = value as Partial<Record<keyof StoredAuthSession, unknown>> | null

  if (
    typeof candidate?.accessToken !== 'string' ||
    candidate.accessToken === '' ||
    typeof candidate.wallet !== 'string' ||
    !ACCOUNT_PATTERN.test(candidate.wallet) ||
    typeof candidate.expiresAtUnix !== 'number' ||
    !Number.isFinite(candidate.expiresAtUnix)
  ) {
    return null
  }

  return {
    accessToken: candidate.accessToken,
    wallet: candidate.wallet,
    expiresAtUnix: candidate.expiresAtUnix,
  }
}

export function readStoredSession(): StoredAuthSession | null {
  const raw = readSessionItem(STORAGE_KEY)

  if (raw === null) {
    return null
  }

  const stored = parse(raw)

  // Un valor corrupto no sirve para restaurar nada.
  if (stored === null) {
    removeSessionItem(STORAGE_KEY)
  }

  return stored
}

export function storeSession(session: StoredAuthSession): void {
  writeSessionItem(STORAGE_KEY, JSON.stringify(session))
}

export function clearStoredSession(): void {
  removeSessionItem(STORAGE_KEY)
}

/** Segundos unix, como los maneja el backend. */
export function nowUnix(): number {
  return Math.floor(Date.now() / 1000)
}

export function isExpired(session: StoredAuthSession): boolean {
  return session.expiresAtUnix <= nowUnix()
}
