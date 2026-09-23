/**
 * Enlaces a exploradores publicos de Stellar Testnet.
 *
 * Solo se construyen URLs: MergePay nunca consulta StellarExpert ni Stellar
 * Lab. Sirven para que cualquiera compruebe los datos fuera de MergePay.
 */

const STELLAR_EXPERT_TESTNET = 'https://stellar.expert/explorer/testnet'
const STELLAR_LAB_TESTNET = 'https://lab.stellar.org/r/testnet'

function requireValue(value: string, name: string): string {
  const trimmed = value.trim()

  if (trimmed === '') {
    throw new Error(`${name} must not be empty`)
  }

  return trimmed
}

/** Busqueda en StellarExpert: vale para transacciones y cuentas G... */
export function stellarExpertSearchUrl(value: string): string {
  return `${STELLAR_EXPERT_TESTNET}/search?term=${encodeURIComponent(requireValue(value, 'value'))}`
}

export function stellarExpertContractUrl(contractId: string): string {
  return `${STELLAR_EXPERT_TESTNET}/contract/${encodeURIComponent(requireValue(contractId, 'contractId'))}`
}

/** Stellar Lab puede mostrar el contrato y su storage directamente. */
export function stellarLabContractUrl(contractId: string): string {
  return `${STELLAR_LAB_TESTNET}/contract/${encodeURIComponent(requireValue(contractId, 'contractId'))}`
}
