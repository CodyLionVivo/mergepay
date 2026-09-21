/**
 * Creacion del escrow on-chain desde el navegador.
 *
 * El cliente firma con Freighter como source account de la transaccion, y esa
 * firma es la que satisface el `client.require_auth()` de `create_bounty`. El
 * backend no firma nada aqui ni conoce ninguna clave.
 */

import {
  Address,
  BASE_FEE,
  Contract,
  StrKey,
  TransactionBuilder,
  nativeToScVal,
  rpc,
} from '@stellar/stellar-sdk'
import type { Bounty } from '../types/bounty'
import {
  STELLAR_CONTRACT_ID,
  STELLAR_RPC_URL,
  TESTNET_PASSPHRASE,
  fundingConfigurationProblem,
} from './config'
import { signWithFreighter } from './freighter'

export type FundingPhase = 'preparing' | 'signing' | 'submitting' | 'confirming'

export interface FundingCallbacks {
  onPhase?: (phase: FundingPhase) => void
  /**
   * En cuanto Stellar acepta el envio. Desde aqui la transaccion puede entrar
   * en la red, asi que el hash no debe perderse aunque algo falle despues.
   */
  onSubmitted?: (transactionHash: string) => void
}

export class FundingError extends Error {
  /**
   * Presente cuando la transaccion ya se envio: aunque algo fallara despues,
   * volver a firmar podria duplicar el funding, asi que el hash no se pierde.
   */
  transactionHash: string | null

  constructor(message: string, transactionHash: string | null = null) {
    super(message)
    this.name = 'FundingError'
    this.transactionHash = transactionHash
  }
}

const CREATE_BOUNTY_FUNCTION = 'create_bounty'
const TRANSACTION_TIMEOUT_SECONDS = 30

const POLL_INTERVAL_MS = 1000
const MAX_POLL_ATTEMPTS = 30

const HASH_PATTERN = /^[0-9a-fA-F]{64}$/

const ACCEPTED_SEND_STATUSES = new Set(['PENDING', 'DUPLICATE'])

/** 64 caracteres hex a exactamente 32 bytes. */
function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2)

  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16)
  }

  return bytes
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds)
  })
}

function firstLine(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)

  return message.split('\n')[0].slice(0, 180)
}

/** Todo lo que puede comprobarse antes de tocar la red. */
function assertFundable(bounty: Bounty, clientAddress: string): string {
  const configurationProblem = fundingConfigurationProblem()

  if (configurationProblem !== null) {
    throw new FundingError(`Stellar funding is not configured. ${configurationProblem}`)
  }

  if (!Number.isSafeInteger(bounty.id) || bounty.id <= 0) {
    throw new FundingError('This task has an invalid identifier.')
  }

  if (bounty.status !== 'DRAFT') {
    throw new FundingError('Only draft tasks can be funded.')
  }

  if (bounty.criteria_hash === null || !HASH_PATTERN.test(bounty.criteria_hash)) {
    throw new FundingError('This task has no valid criteria commitment.')
  }

  if (!Number.isSafeInteger(bounty.amount_stroops) || bounty.amount_stroops <= 0) {
    throw new FundingError('This task has an invalid reward amount.')
  }

  if (
    !Number.isSafeInteger(bounty.deadline_unix) ||
    bounty.deadline_unix <= Math.floor(Date.now() / 1000)
  ) {
    throw new FundingError('The deadline of this task has already passed.')
  }

  const address = clientAddress.trim()

  if (address === '') {
    throw new FundingError('Connect a wallet before securing the reward.')
  }

  // Solo una cuenta publica G.... Una S... (secret seed) nunca es valida aqui.
  if (!StrKey.isValidEd25519PublicKey(address)) {
    throw new FundingError('The connected wallet address is not a valid Stellar account.')
  }

  return bounty.criteria_hash
}

/**
 * Crea y financia el escrow del bounty, y devuelve el hash de la transaccion
 * una vez que Stellar la confirma como SUCCESS.
 */
export async function fundBounty(
  bounty: Bounty,
  clientAddress: string,
  callbacks: FundingCallbacks = {},
): Promise<string> {
  const { onPhase, onSubmitted } = callbacks

  const criteriaHash = assertFundable(bounty, clientAddress)

  onPhase?.('preparing')

  const server = new rpc.Server(STELLAR_RPC_URL)

  let account

  try {
    account = await server.getAccount(clientAddress)
  } catch {
    throw new FundingError(
      'Unable to load this account from Stellar Testnet. Make sure it exists and is funded, for example with Friendbot.',
    )
  }

  const contract = new Contract(STELLAR_CONTRACT_ID)

  // Orden y tipos exactos de create_bounty(id, client, amount, criteria_hash,
  // deadline). Los enteros viajan como BigInt: nada de floats para el monto.
  const transaction = new TransactionBuilder(account, {
    fee: BASE_FEE,
    networkPassphrase: TESTNET_PASSPHRASE,
  })
    .addOperation(
      contract.call(
        CREATE_BOUNTY_FUNCTION,
        nativeToScVal(BigInt(bounty.id), { type: 'u64' }),
        new Address(clientAddress).toScVal(),
        nativeToScVal(BigInt(bounty.amount_stroops), { type: 'i128' }),
        nativeToScVal(hexToBytes(criteriaHash), { type: 'bytes' }),
        nativeToScVal(BigInt(bounty.deadline_unix), { type: 'u64' }),
      ),
    )
    .setTimeout(TRANSACTION_TIMEOUT_SECONDS)
    .build()

  let prepared

  try {
    prepared = await server.prepareTransaction(transaction)
  } catch (error) {
    // La simulacion falla, por ejemplo, sin saldo suficiente o si el bounty
    // ya existe on-chain.
    throw new FundingError(`Stellar could not prepare the transaction: ${firstLine(error)}`)
  }

  onPhase?.('signing')

  const signed = await signWithFreighter(
    prepared.toXDR(),
    clientAddress,
    TESTNET_PASSPHRASE,
  )

  if (signed.signerAddress !== clientAddress) {
    throw new FundingError(
      'Freighter signed with a different account than the one connected. Nothing was submitted.',
    )
  }

  const signedTransaction = TransactionBuilder.fromXDR(
    signed.signedTxXdr,
    TESTNET_PASSPHRASE,
  )

  onPhase?.('submitting')

  const sent = await server.sendTransaction(signedTransaction)

  if (!ACCEPTED_SEND_STATUSES.has(sent.status)) {
    throw new FundingError(`Stellar rejected the transaction (${sent.status}).`)
  }

  const transactionHash = sent.hash

  onSubmitted?.(transactionHash)
  onPhase?.('confirming')

  for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
    const result = await server.getTransaction(transactionHash)

    if (result.status === rpc.Api.GetTransactionStatus.SUCCESS) {
      return transactionHash
    }

    // FAILED: la transaccion entro pero no hizo efecto, asi que no se movio
    // ningun fondo y volver a intentarlo es seguro.
    if (result.status === rpc.Api.GetTransactionStatus.FAILED) {
      throw new FundingError('The funding transaction failed on Stellar. No funds were moved.')
    }

    await sleep(POLL_INTERVAL_MS)
  }

  // Tras el timeout la transaccion aun puede confirmarse: se conserva el hash.
  throw new FundingError(
    'Stellar has not confirmed the transaction yet.',
    transactionHash,
  )
}
