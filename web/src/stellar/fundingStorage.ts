/**
 * Hash de una transaccion de funding ya enviada y aun sin confirmar por
 * MergePay, guardado en sessionStorage para sobrevivir a un refresh.
 *
 * Solo se guarda el hash: nunca XDR, claves ni datos de la wallet. Si el
 * storage no esta disponible (bloqueado por el navegador), todo sigue
 * funcionando en memoria, solo que sin sobrevivir al refresh.
 */

const HASH_PATTERN = /^[0-9a-fA-F]{64}$/

function storageKey(bountyId: number): string {
  return `mergepay:funding-tx:${bountyId}`
}

export function readPendingFundingHash(bountyId: number): string | null {
  try {
    const value = window.sessionStorage.getItem(storageKey(bountyId))

    if (value === null) {
      return null
    }

    if (HASH_PATTERN.test(value)) {
      return value.toLowerCase()
    }

    // Un valor que no es un hash no sirve para recuperar nada: se descarta.
    window.sessionStorage.removeItem(storageKey(bountyId))

    return null
  } catch {
    // Storage no disponible: no hay nada que recuperar.
    return null
  }
}

export function storePendingFundingHash(bountyId: number, transactionHash: string): void {
  try {
    window.sessionStorage.setItem(storageKey(bountyId), transactionHash.toLowerCase())
  } catch {
    // Storage no disponible: el hash queda solo en el estado del componente.
    return
  }
}

export function clearPendingFundingHash(bountyId: number): void {
  try {
    window.sessionStorage.removeItem(storageKey(bountyId))
  } catch {
    // Storage no disponible: no habia nada guardado que borrar.
    return
  }
}
