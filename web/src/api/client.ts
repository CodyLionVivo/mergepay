/**
 * Cliente HTTP del backend de MergePay.
 *
 * Por defecto apunta a /api, que en desarrollo Vite redirige a FastAPI
 * quitando ese prefijo. En produccion se apunta con VITE_API_BASE_URL.
 */

import type { Bounty, BountyCreate, Submission } from '../types/bounty'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  status: number
  /** Motivos concretos cuando el backend los da, por ejemplo al rechazar un PR. */
  reasons: string[]

  constructor(message: string, status: number, reasons: string[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.reasons = reasons
  }
}

export interface HealthResponse {
  status: string
}

interface ErrorDetail {
  message: string
  reasons: string[]
}

/**
 * Saca un mensaje legible del cuerpo de error.
 *
 * FastAPI devuelve `detail` como string, como objeto con `message` (y a veces
 * `reasons`) o, en los errores de validacion, como lista de entradas con `msg`.
 */
async function readErrorDetail(response: Response): Promise<ErrorDetail> {
  const fallback = { message: `Request failed with status ${response.status}`, reasons: [] }

  let body: unknown

  try {
    body = await response.json()
  } catch {
    // La respuesta no traia JSON: se usa el mensaje generico.
    return fallback
  }

  const detail = (body as { detail?: unknown } | null)?.detail

  if (typeof detail === 'string') {
    return { message: detail, reasons: [] }
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (entry as { msg?: unknown } | null)?.msg)
      .filter((message): message is string => typeof message === 'string')

    return messages.length > 0 ? { message: messages.join('. '), reasons: [] } : fallback
  }

  const structured = detail as { message?: unknown; reasons?: unknown } | null
  const message = structured?.message

  if (typeof message === 'string') {
    const reasons = Array.isArray(structured?.reasons)
      ? structured.reasons.filter((reason): reason is string => typeof reason === 'string')
      : []

    return { message, reasons }
  }

  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  })

  if (!response.ok) {
    const { message, reasons } = await readErrorDetail(response)

    throw new ApiError(message, response.status, reasons)
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

/**
 * Pide al backend que compruebe on-chain la aceptacion hecha con esta
 * transaccion. La wallet del developer la lee el backend del contrato, y
 * contra ella verifica la firma que prueba que el GitHub es de quien acepto.
 */
export function confirmBountyAssignment(
  bountyId: number,
  transactionHash: string,
  developerGithub: string,
  walletSignature: string,
): Promise<Bounty> {
  return request<Bounty>(`/bounties/${bountyId}/assigned`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      transaction_hash: transactionHash,
      developer_github: developerGithub,
      wallet_signature: walletSignature,
    }),
  })
}

export function createSubmission(
  bountyId: number,
  pullRequestUrl: string,
): Promise<Submission> {
  return request<Submission>(`/bounties/${bountyId}/submission`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pull_request_url: pullRequestUrl }),
  })
}
