import { useState } from 'react'
import { AlertTriangle, Info, Loader, RotateCcw, ShieldCheck, Wallet } from 'lucide-react'
import { ApiError, confirmBountyFunding } from '../api/client'
import { fundingConfigurationProblem } from '../stellar/config'
import { FundingError, fundBounty } from '../stellar/escrow'
import type { FundingPhase } from '../stellar/escrow'
import { FreighterError } from '../stellar/freighter'
import {
  clearPendingFundingHash,
  readPendingFundingHash,
  storePendingFundingHash,
} from '../stellar/fundingStorage'
import { useWallet } from '../stellar/walletContext'
import type { Bounty } from '../types/bounty'
import './FundingPanel.css'

type Step = 'idle' | FundingPhase | 'syncing'

const STEP_LABELS: Record<Exclude<Step, 'idle'>, string> = {
  preparing: 'Preparing transaction...',
  signing: 'Confirm in Freighter...',
  submitting: 'Submitting to Stellar...',
  confirming: 'Waiting for Stellar...',
  syncing: 'Confirming with MergePay...',
}

/**
 * Transaccion ya enviada a Stellar. Mientras exista, la UI no vuelve a firmar:
 * solo reintenta la confirmacion con el backend.
 */
interface SubmittedTransaction {
  hash: string
  /**
   * confirmed: Stellar la dio por SUCCESS y fallo MergePay.
   * pending: enviada, pero el polling no llego a ver el resultado.
   * recovered: leida de sessionStorage tras un refresh; su estado se ignora.
   */
  origin: 'confirmed' | 'pending' | 'recovered'
}

const SUBMITTED_MESSAGES: Record<SubmittedTransaction['origin'], string> = {
  confirmed: 'Reward is secured on Stellar, but MergePay could not confirm it.',
  pending: 'The transaction was submitted, but Stellar has not confirmed it yet.',
  recovered:
    'A funding transaction was already submitted for this task in this browser session.',
}

/** Al montar: si quedo una transaccion enviada de antes del refresh, se retoma. */
function recoverSubmitted(bountyId: number): SubmittedTransaction | null {
  const hash = readPendingFundingHash(bountyId)

  return hash === null ? null : { hash, origin: 'recovered' }
}

function describe(error: unknown): string {
  if (error instanceof ApiError || error instanceof FundingError || error instanceof FreighterError) {
    return error.message
  }

  return error instanceof Error && error.message
    ? error.message
    : 'Something went wrong while securing the reward.'
}

interface FundingPanelProps {
  bounty: Bounty
  onFunded: (bounty: Bounty) => void
}

export function FundingPanel({ bounty, onFunded }: FundingPanelProps) {
  const wallet = useWallet()

  const [step, setStep] = useState<Step>('idle')
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState<SubmittedTransaction | null>(() =>
    recoverSubmitted(bounty.id),
  )

  const busy = step !== 'idle'
  const configurationProblem = fundingConfigurationProblem()

  async function confirmWithMergePay(transaction: SubmittedTransaction) {
    setStep('syncing')
    setError(null)

    try {
      const updated = await confirmBountyFunding(bounty.id, transaction.hash)

      // Confirmado: ya no hay nada que recuperar tras un refresh.
      clearPendingFundingHash(bounty.id)
      setSubmitted(null)
      setStep('idle')
      onFunded(updated)
    } catch (caught) {
      // El hash se conserva, en memoria y en sessionStorage: el siguiente
      // intento solo vuelve a confirmar.
      setError(describe(caught))
      setStep('idle')
    }
  }

  async function secureReward() {
    if (busy || submitted !== null || wallet.address === null) {
      return
    }

    setError(null)

    // Se rellena en cuanto Stellar acepta el envio. Es un objeto y no un `let`
    // para que TypeScript no asuma que sigue a null tras el await.
    const sent: { hash: string | null } = { hash: null }

    let hash: string

    try {
      hash = await fundBounty(bounty, wallet.address, {
        onPhase: setStep,
        onSubmitted: (transactionHash) => {
          sent.hash = transactionHash
          storePendingFundingHash(bounty.id, transactionHash)
        },
      })
    } catch (caught) {
      if (sent.hash !== null) {
        if (caught instanceof FundingError && caught.transactionHash === null) {
          // FAILED definitivo: no se movio ningun fondo y reintentar es
          // seguro, asi que no queda nada que recuperar.
          clearPendingFundingHash(bounty.id)
        } else {
          // Timeout o fallo de red tras el envio: la transaccion aun puede
          // entrar. Se conserva y no se vuelve a firmar.
          setSubmitted({ hash: sent.hash, origin: 'pending' })
        }
      }

      setError(describe(caught))
      setStep('idle')
      return
    }

    const transaction: SubmittedTransaction = { hash, origin: 'confirmed' }

    setSubmitted(transaction)
    await confirmWithMergePay(transaction)
  }

  return (
    <section className="funding-panel" aria-labelledby="funding-title">
      <div className="funding-panel__head">
        <Info size={18} aria-hidden="true" />
        <div>
          <h2 className="funding-panel__title" id="funding-title">
            Draft task
          </h2>
          <p>
            Draft tasks are created in MergePay but their reward has not been
            secured on Stellar yet.
          </p>
        </div>
      </div>

      <p className="funding-panel__network">
        <AlertTriangle size={14} aria-hidden="true" />
        Stellar Testnet — no real funds
      </p>

      {submitted !== null ? (
        <SubmittedState
          transaction={submitted}
          busy={busy}
          step={step}
          onRetry={() => void confirmWithMergePay(submitted)}
        />
      ) : (
        <div className="funding-panel__action">
          <FundingAction
            configurationProblem={configurationProblem}
            busy={busy}
            step={step}
            onConnect={() => void wallet.connect()}
            onRecheck={() => void wallet.refresh()}
            onSecure={() => void secureReward()}
          />
        </div>
      )}

      {error !== null ? (
        <p className="funding-panel__error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          {error}
        </p>
      ) : null}

      {busy ? (
        <p className="visually-hidden" role="status">
          {STEP_LABELS[step]}
        </p>
      ) : null}
    </section>
  )
}

interface FundingActionProps {
  configurationProblem: string | null
  busy: boolean
  step: Step
  onConnect: () => void
  onRecheck: () => void
  onSecure: () => void
}

function FundingAction({
  configurationProblem,
  busy,
  step,
  onConnect,
  onRecheck,
  onSecure,
}: FundingActionProps) {
  const wallet = useWallet()

  if (configurationProblem !== null) {
    return (
      <>
        <button type="button" className="button button--primary" disabled>
          Secure reward
        </button>
        <span className="funding-panel__hint">
          Funding is disabled: {configurationProblem}
        </span>
      </>
    )
  }

  if (busy) {
    return (
      <button type="button" className="button button--primary" disabled>
        <Loader size={16} aria-hidden="true" />
        {step === 'idle' ? 'Working...' : STEP_LABELS[step]}
      </button>
    )
  }

  if (wallet.status === 'connected') {
    return (
      <button type="button" className="button button--primary" onClick={onSecure}>
        <ShieldCheck size={16} aria-hidden="true" />
        Secure reward
      </button>
    )
  }

  if (wallet.status === 'wrong-network') {
    return (
      <>
        <button type="button" className="button button--secondary" onClick={onRecheck}>
          <RotateCcw size={16} aria-hidden="true" />
          Check network again
        </button>
        <span className="funding-panel__hint funding-panel__hint--warning">
          Switch Freighter to Testnet
        </span>
      </>
    )
  }

  if (wallet.status === 'connecting') {
    return (
      <button type="button" className="button button--primary" disabled>
        <Loader size={16} aria-hidden="true" />
        Connecting...
      </button>
    )
  }

  if (wallet.status === 'unavailable') {
    return (
      <>
        <button type="button" className="button button--secondary" onClick={onRecheck}>
          <RotateCcw size={16} aria-hidden="true" />
          Check for Freighter
        </button>
        <span className="funding-panel__hint">
          Install the Freighter browser extension to secure the reward.
        </span>
      </>
    )
  }

  return (
    <>
      <button type="button" className="button button--primary" onClick={onConnect}>
        <Wallet size={16} aria-hidden="true" />
        Connect wallet to secure reward
      </button>
      {wallet.status === 'error' && wallet.error !== null ? (
        <span className="funding-panel__hint">{wallet.error}</span>
      ) : null}
    </>
  )
}

interface SubmittedStateProps {
  transaction: SubmittedTransaction
  busy: boolean
  step: Step
  onRetry: () => void
}

/** La transaccion ya esta en Stellar: solo queda confirmarla con MergePay. */
function SubmittedState({ transaction, busy, step, onRetry }: SubmittedStateProps) {
  return (
    <div className="funding-panel__submitted">
      <p className="funding-panel__submitted-text">
        {SUBMITTED_MESSAGES[transaction.origin]}
      </p>
      <p className="funding-panel__hint">
        Transaction <code title={transaction.hash}>{transaction.hash}</code>
      </p>
      <div className="funding-panel__action">
        <button
          type="button"
          className="button button--primary"
          onClick={onRetry}
          disabled={busy}
        >
          {busy ? (
            <>
              <Loader size={16} aria-hidden="true" />
              {step === 'idle' ? 'Working...' : STEP_LABELS[step]}
            </>
          ) : (
            <>
              <RotateCcw size={16} aria-hidden="true" />
              Retry confirmation
            </>
          )}
        </button>
      </div>
    </div>
  )
}
