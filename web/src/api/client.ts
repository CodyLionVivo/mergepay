/**
 * Cliente HTTP del backend de MergePay.
 *
 * Por defecto apunta a /api, que en desarrollo Vite redirige a FastAPI
 * quitando ese prefijo. En produccion se apunta con VITE_API_BASE_URL.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export interface HealthResponse {
  status: string
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`, {
    signal,
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`)
  }

  return (await response.json()) as HealthResponse
}
