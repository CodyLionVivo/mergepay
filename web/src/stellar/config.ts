/**
 * Configuracion Stellar del navegador, en un unico sitio.
 *
 * Todo es publico: RPC, red y contrato. Aqui no hay ni puede haber secretos.
 */

/** La unica red soportada. Freighter tiene que estar exactamente en esta. */
export const TESTNET_PASSPHRASE = 'Test SDF Network ; September 2015'

export const STELLAR_RPC_URL =
  import.meta.env.VITE_STELLAR_RPC_URL?.trim() || 'https://soroban-testnet.stellar.org'

export const STELLAR_NETWORK = import.meta.env.VITE_STELLAR_NETWORK?.trim() || 'TESTNET'

export const STELLAR_NETWORK_PASSPHRASE =
  import.meta.env.VITE_STELLAR_NETWORK_PASSPHRASE?.trim() || TESTNET_PASSPHRASE

export const STELLAR_CONTRACT_ID = import.meta.env.VITE_STELLAR_CONTRACT_ID?.trim() ?? ''

/** Id de contrato Soroban: C seguido de 55 caracteres base32. */
const CONTRACT_ID_PATTERN = /^C[A-Z2-7]{55}$/

/**
 * Motivo por el que el funding no puede usarse, o null si esta listo.
 *
 * Una passphrase distinta de Testnet cuenta como configuracion invalida: el
 * MVP no soporta otras redes.
 */
export function fundingConfigurationProblem(): string | null {
  if (STELLAR_CONTRACT_ID === '') {
    return 'VITE_STELLAR_CONTRACT_ID is not set.'
  }

  if (!CONTRACT_ID_PATTERN.test(STELLAR_CONTRACT_ID)) {
    return 'VITE_STELLAR_CONTRACT_ID is not a valid contract id.'
  }

  if (STELLAR_NETWORK_PASSPHRASE !== TESTNET_PASSPHRASE) {
    return 'MergePay only supports Stellar Testnet.'
  }

  return null
}
