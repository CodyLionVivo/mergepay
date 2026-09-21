/**
 * Cliente HTTP del backend de MergePay.
 *
 * Por defecto apunta a /api, que en desarrollo Vite redirige a FastAPI
 * quitando ese prefijo. En produccion se apunta con VITE_API_BASE_URL.
 */

import type { Bounty, BountyCreate } from '../types/bounty'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface HealthResponse {
  status: string
}

/**
 * Saca un mensaje legible del cuerpo de error.
 *
 * FastAPI devuelve `detail` como string, como objeto con `message` o, en los
 * errores de validacion, como lista de entradas con `msg`.
 */
async function readErrorMessage(response: Response): Promise<string> {
  let body: unknown

  try {
    body = await response.json()
  } catch {
    // La respuesta no traia JSON: se usa el mensaje generico de abajo.
    return `Request failed with status ${response.status}`
  }

  const detail = (body as { detail?: unknown } | null)?.detail

  if (typeof detail === 'string') {
    return detail
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (entry as { msg?: unknown } | null)?.msg)
      .filter((message): message is string => typeof message === 'string')

    if (messages.length > 0) {
      return messages.join('. ')
    }
  }

  const message = (detail as { message?: unknown } | null)?.message

  if (typeof message === 'string') {
    return message
  }

  return `Request failed with status ${response.status}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  })

  if (!response.ok) {
    throw new ApiError(await readErrorMessage(response), response.status)
  }

  return (await response.json()) as T
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>('/health', { signal })
}

export function getBounties(signal?: AbortSignal): Promise<Bounty[]> {
  return request<Bounty[]>('/bounties', { signal })
}

export function getBounty(id: number, signal?: AbortSignal): Promise<Bounty> {
  return request<Bounty>(`/bounties/${id}`, { signal })
}

export function createBounty(
  payload: BountyCreate,
  signal?: AbortSignal,
): Promise<Bounty> {
  return request<Bounty>('/bounties', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
}

/**
 * Pide al backend que compruebe on-chain el escrow creado por esta
 * transaccion. Solo viaja el hash: wallet, monto y status los lee el backend.
 */
export function confirmBountyFunding(
  bountyId: number,
  transactionHash: string,
): Promise<Bounty> {
  return request<Bounty>(`/bounties/${bountyId}/funded`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transaction_hash: transactionHash }),
  })
}
