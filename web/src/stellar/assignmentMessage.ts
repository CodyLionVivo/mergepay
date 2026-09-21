/**
 * Prueba de propiedad de la wallet del developer para la aceptacion.
 *
 * El hash de la aceptacion es publico: sin esta firma, cualquiera podria
 * confirmar la task en MergePay con otro usuario de GitHub. El developer firma
 * con SEP-53 un mensaje que ata bounty, transaccion, wallet, GitHub y contrato,
 * y el backend lo verifica contra la wallet que registro el contrato.
 */

import { STELLAR_CONTRACT_ID, TESTNET_PASSPHRASE } from './config'
import { FreighterError, signMessageWithFreighter } from './freighter'

export interface AssignmentMessageFields {
  bountyId: number
  transactionHash: string
  developerWallet: string
  developerGithub: string
  contractId: string
}

/**
 * Mensaje canonico. Tiene que coincidir byte a byte con el del backend:
 * una linea por campo y sin salto de linea final.
 */
export function buildAssignmentMessage(fields: AssignmentMessageFields): string {
  return [
    'MergePay assignment v1',
    `bounty_id=${fields.bountyId}`,
    `transaction_hash=${fields.transactionHash.toLowerCase()}`,
    `developer_wallet=${fields.developerWallet}`,
    `developer_github=${fields.developerGithub.trim()}`,
    `contract_id=${fields.contractId}`,
  ].join('\n')
}

/**
 * Pide a Freighter la firma del mensaje de aceptacion y la devuelve en base64.
 *
 * Solo llama a signMessage: no construye ni envia ninguna transaccion.
 */
export async function signAssignmentOwnership(params: {
  bountyId: number
  transactionHash: string
  developerAddress: string
  developerGithub: string
}): Promise<string> {
  if (STELLAR_CONTRACT_ID === '') {
    throw new FreighterError('Stellar is not configured: VITE_STELLAR_CONTRACT_ID is not set.')
  }

  const message = buildAssignmentMessage({
    bountyId: params.bountyId,
    transactionHash: params.transactionHash,
    developerWallet: params.developerAddress,
    developerGithub: params.developerGithub,
    contractId: STELLAR_CONTRACT_ID,
  })

  const signed = await signMessageWithFreighter(
    message,
    params.developerAddress,
    TESTNET_PASSPHRASE,
  )

  if (signed.signerAddress !== params.developerAddress) {
    throw new FreighterError(
      'Freighter signed with a different account than the one that accepted this task.',
    )
  }

  return signed.signature
}
