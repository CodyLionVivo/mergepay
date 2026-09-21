/**
 * Transacciones del escrow firmadas desde el navegador.
 *
 * Quien firma con Freighter es siempre la source account de la transaccion, y
 * esa firma es la que satisface el `require_auth()` del contrato: el cliente en
 * `create_bounty`, el developer en `accept_bounty`. El backend no firma nada
 * aqui ni conoce ninguna clave.
 */

import {
  Address,
  BASE_FEE,
  Contract,
  StrKey,
  TransactionBuilder,
  nativeToScVal,
  rpc,
  xdr,
} from '@stellar/stellar-sdk'
import type { Bounty } from '../types/bounty'
import {
  STELLAR_CONTRACT_ID,
  STELLAR_RPC_URL,
  TESTNET_PASSPHRASE,
  fundingConfigurationProblem,
} from './config'
import { signWithFreighter } from './freighter'

export type TransactionPhase = 'preparing' | 'signing' | 'submitting' | 'confirming'

export interface TransactionCallbacks {
  onPhase?: (phase: TransactionPhase) => void
  /**
   * En cuanto Stellar acepta el envio. Desde aqui la transaccion puede entrar
   * en la red, asi que el hash no debe perderse aunque algo falle despues.
   */
  onSubmitted?: (transactionHash: string) => void
}

export class EscrowError extends Error {
  /**
   * Presente cuando la transaccion ya se envio: aunque algo fallara despues,
   * volver a firmar podria duplicar la operacion, asi que el hash no se pierde.
   */
  transactionHash: string | null

  constructor(message: string, transactionHash: string | null = null) {
    super(message)
    this.name = 'EscrowError'
    this.transactionHash = transactionHash
  }
}

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

function assertConfigured(): void {
  const configurationProblem = fundingConfigurationProblem()

  if (configurationProblem !== null) {
    throw new EscrowError(`Stellar is not configured. ${configurationProblem}`)
  }
}

function assertBountyId(bounty: Bounty): void {
  if (!Number.isSafeInteger(bounty.id) || bounty.id <= 0) {
    throw new EscrowError('This task has an invalid identifier.')
  }
}

/** Solo una cuenta publica G.... Una S... (secret seed) nunca es valida aqui. */
function assertAccountAddress(address: string, missingMessage: string): void {
  if (address.trim() === '') {
    throw new EscrowError(missingMessage)
  }

  if (!StrKey.isValidEd25519PublicKey(address.trim())) {
    throw new EscrowError('The connected wallet address is not a valid Stellar account.')
  }
}

interface ContractInvocation {
  /** Cuenta que firma con Freighter y paga la transaccion. */
  source: string
  method: string
  args: xdr.ScVal[]
  /** Mensaje si la transaccion entra en la red pero acaba FAILED. */
  failedMessage: string
}

/**
 * Ciclo comun: preparar, firmar con Freighter, enviar y esperar a Stellar.
 * Devuelve el hash cuando la transaccion queda confirmada como SUCCESS.
 */
async function signAndSubmit(
  invocation: ContractInvocation,
  callbacks: TransactionCallbacks,
): Promise<string> {
  const { onPhase, onSubmitted } = callbacks

  onPhase?.('preparing')

  const server = new rpc.Server(STELLAR_RPC_URL)

  let account

  try {
    account = await server.getAccount(invocation.source)
  } catch {
    throw new EscrowError(
      'Unable to load this account from Stellar Testnet. Make sure it exists and is funded, for example with Friendbot.',
    )
  }

  const contract = new Contract(STELLAR_CONTRACT_ID)

  const transaction = new TransactionBuilder(account, {
    fee: BASE_FEE,
    networkPassphrase: TESTNET_PASSPHRASE,
  })
    .addOperation(contract.call(invocation.method, ...invocation.args))
    .setTimeout(TRANSACTION_TIMEOUT_SECONDS)
    .build()

  let prepared

  try {
    prepared = await server.prepareTransaction(transaction)
  } catch (error) {
    // La simulacion falla, por ejemplo, sin saldo suficiente o si el contrato
    // rechaza la operacion en el estado actual del bounty.
    throw new EscrowError(`Stellar could not prepare the transaction: ${firstLine(error)}`)
  }

  onPhase?.('signing')

  const signed = await signWithFreighter(
    prepared.toXDR(),
    invocation.source,
    TESTNET_PASSPHRASE,
  )

  if (signed.signerAddress !== invocation.source) {
    throw new EscrowError(
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
    throw new EscrowError(`Stellar rejected the transaction (${sent.status}).`)
  }

  const transactionHash = sent.hash

  onSubmitted?.(transactionHash)
  onPhase?.('confirming')

  for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
    const result = await server.getTransaction(transactionHash)

    if (result.status === rpc.Api.GetTransactionStatus.SUCCESS) {
      return transactionHash
    }

    // FAILED: la transaccion entro pero no hizo efecto, asi que volver a
    // intentarlo es seguro.
    if (result.status === rpc.Api.GetTransactionStatus.FAILED) {
      throw new EscrowError(invocation.failedMessage)
    }

    await sleep(POLL_INTERVAL_MS)
  }

  // Tras el timeout la transaccion aun puede confirmarse: se conserva el hash.
  throw new EscrowError('Stellar has not confirmed the transaction yet.', transactionHash)
}

/**
 * Crea y financia el escrow del bounty, y devuelve el hash de la transaccion
 * una vez que Stellar la confirma como SUCCESS.
 */
export async function fundBounty(
  bounty: Bounty,
  clientAddress: string,
  callbacks: TransactionCallbacks = {},
): Promise<string> {
  assertConfigured()
  assertBountyId(bounty)

  if (bounty.status !== 'DRAFT') {
    throw new EscrowError('Only draft tasks can be funded.')
  }

  const criteriaHash = bounty.criteria_hash

  if (criteriaHash === null || !HASH_PATTERN.test(criteriaHash)) {
    throw new EscrowError('This task has no valid criteria commitment.')
  }

  if (!Number.isSafeInteger(bounty.amount_stroops) || bounty.amount_stroops <= 0) {
    throw new EscrowError('This task has an invalid reward amount.')
  }

  if (
    !Number.isSafeInteger(bounty.deadline_unix) ||
    bounty.deadline_unix <= Math.floor(Date.now() / 1000)
  ) {
    throw new EscrowError('The deadline of this task has already passed.')
  }

  assertAccountAddress(clientAddress, 'Connect a wallet before securing the reward.')

  // Orden y tipos exactos de create_bounty(id, client, amount, criteria_hash,
  // deadline). Los enteros viajan como BigInt: nada de floats para el monto.
  return signAndSubmit(
    {
      source: clientAddress,
      method: 'create_bounty',
      args: [
        nativeToScVal(BigInt(bounty.id), { type: 'u64' }),
        new Address(clientAddress).toScVal(),
        nativeToScVal(BigInt(bounty.amount_stroops), { type: 'i128' }),
        nativeToScVal(hexToBytes(criteriaHash), { type: 'bytes' }),
        nativeToScVal(BigInt(bounty.deadline_unix), { type: 'u64' }),
      ],
      failedMessage: 'The funding transaction failed on Stellar. No funds were moved.',
    },
    callbacks,
  )
}

/**
 * Acepta el bounty con la wallet del developer y devuelve el hash de la
 * transaccion una vez que Stellar la confirma como SUCCESS.
 */
export async function acceptBounty(
  bounty: Bounty,
  developerAddress: string,
  callbacks: TransactionCallbacks = {},
): Promise<string> {
  assertConfigured()
  assertBountyId(bounty)

  if (bounty.status !== 'OPEN_FUNDED') {
    throw new EscrowError('Only funded tasks can be accepted.')
  }

  // El contrato exige timestamp <= deadline para aceptar.
  if (
    !Number.isSafeInteger(bounty.deadline_unix) ||
    bounty.deadline_unix < Math.floor(Date.now() / 1000)
  ) {
    throw new EscrowError('The deadline of this task has already passed.')
  }

  assertAccountAddress(developerAddress, 'Connect a wallet before accepting this task.')

  if (bounty.client_wallet !== null && developerAddress.trim() === bounty.client_wallet) {
    throw new EscrowError('Switch to a developer wallet before accepting this task.')
  }

  // accept_bounty(id, developer). El usuario de GitHub no pertenece al
  // contrato: se envia despues solo al backend.
  return signAndSubmit(
    {
      source: developerAddress,
      method: 'accept_bounty',
      args: [
        nativeToScVal(BigInt(bounty.id), { type: 'u64' }),
        new Address(developerAddress).toScVal(),
      ],
      failedMessage: 'The assignment transaction failed on Stellar.',
    },
    callbacks,
  )
}
