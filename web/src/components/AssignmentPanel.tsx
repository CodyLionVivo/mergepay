import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  AlertTriangle,
  Handshake,
  KeyRound,
  Loader,
  RotateCcw,
  UserCheck,
  Wallet,
} from 'lucide-react'
import { ApiError, confirmBountyAssignment } from '../api/client'
import { useAuth } from '../auth/authContext'
import { assignmentIssue } from '../auth/taskAccess'
import { AuthPrompt } from './AuthPrompt'
import { signAssignmentOwnership } from '../stellar/assignmentMessage'
import {
  clearPendingAssignment,
  readPendingAssignment,
  storePendingAssignment,
} from '../stellar/assignmentStorage'
import type { PendingAssignment } from '../stellar/assignmentStorage'
import { fundingConfigurationProblem } from '../stellar/config'
import { EscrowError, acceptBounty } from '../stellar/escrow'
import type { TransactionPhase } from '../stellar/escrow'
import { abbreviateAddress, useWallet } from '../stellar/walletContext'
import type { Bounty } from '../types/bounty'
import { formatUnixSeconds } from '../utils/format'
import { isValidGithubUsername } from '../utils/github'
import { formatXlm } from '../utils/xlm'
import './ActionPanel.css'

type Step = 'idle' | TransactionPhase | 'proving' | 'syncing'

const STEP_LABELS: Record<Exclude<Step, 'idle'>, string> = {
  preparing: 'Preparing assignment...',
  signing: 'Confirm in Freighter...',
  submitting: 'Submitting to Stellar...',
  confirming: 'Waiting for Stellar...',
  proving: 'Confirm wallet ownership',
  syncing: 'Confirming assignment with MergePay...',
}

/** Aceptacion pendiente con su prueba de propiedad ya firmada. */
type SignedAssignment = PendingAssignment & { walletSignature: string }

function describe(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'Something went wrong while accepting this task.'
}

interface AssignmentPanelProps {
  bounty: Bounty
  onAssigned: (bounty: Bounty) => void
}

export function AssignmentPanel({ bounty, onAssigned }: AssignmentPanelProps) {
  const [step, setStep] = useState<Step>('idle')
  const [error, setError] = useState<string | null>(null)
  const [username, setUsername] = useState('')

  // Aceptacion ya enviada a Stellar, de esta visita o de antes de un refresh.
  // Mientras exista no se puede firmar otra aceptacion.
  const [pending, setPending] = useState<PendingAssignment | null>(() =>
    readPendingAssignment(bounty.id),
  )

  const busy = step !== 'idle'

  const wallet = useWallet()
  const auth = useAuth()

  // Aceptar exige sesion propia: el backend comprueba que la wallet que
  // acepto on-chain es la de la sesion.
  const accessIssue =
    wallet.status === 'connected' && wallet.address !== null
      ? assignmentIssue(auth, wallet.address, bounty)
      : null

  /** Solo POST /assigned: ni Freighter ni transacciones. */
  async function confirmWithMergePay(signed: SignedAssignment) {
    setStep('syncing')
    setError(null)

    try {
      const updated = await confirmBountyAssignment(
        bounty.id,
        signed.transactionHash,
        signed.developerGithub,
        signed.walletSignature,
      )

      // Confirmado: ya no hay nada que recuperar tras un refresh.
      clearPendingAssignment(bounty.id)
      setPending(null)
      setStep('idle')
      onAssigned(updated)
    } catch (caught) {
      if (
        caught instanceof ApiError &&
        caught.status === 403 &&
        caught.message === 'Developer wallet signature is invalid'
      ) {
        // El backend rechazo la firma: reenviarla daria otro 403, asi que se
        // descarta solo la firma y se puede volver a firmar la prueba.
        const unsigned: PendingAssignment = { ...signed, walletSignature: null }

        storePendingAssignment(bounty.id, unsigned)
        setPending(unsigned)
      }

      // Cualquier otro fallo conserva la firma: reintentar solo confirma.
      setError(describe(caught))
      setStep('idle')
    }
  }

  /** Solo signMessage y despues la confirmacion: nunca accept_bounty. */
  async function proveOwnership(unsigned: PendingAssignment) {
    setStep('proving')
    setError(null)

    let walletSignature: string

    try {
      walletSignature = await signAssignmentOwnership({
        bountyId: bounty.id,
        transactionHash: unsigned.transactionHash,
        developerAddress: unsigned.developerAddress,
        developerGithub: unsigned.developerGithub,
      })
    } catch (caught) {
      // Popup cerrado o rechazado: la aceptacion sigue en Stellar y queda
      // pendiente de firmar la prueba.
      setError(describe(caught))
      setStep('idle')
      return
    }

    const signed: SignedAssignment = { ...unsigned, walletSignature }

    storePendingAssignment(bounty.id, signed)
    setPending(signed)

    await confirmWithMergePay(signed)
  }

  async function acceptTask(developerAddress: string) {
    const developerGithub = username.trim()

    if (busy || pending !== null || !isValidGithubUsername(developerGithub)) {
      return
    }

    setError(null)

    // Se rellena en cuanto Stellar acepta el envio.
    const sent: { hash: string | null } = { hash: null }

    const unsignedFor = (transactionHash: string): PendingAssignment => ({
      transactionHash,
      developerGithub,
      developerAddress,
      walletSignature: null,
    })

    let hash: string

    try {
      hash = await acceptBounty(bounty, developerAddress, {
        onPhase: setStep,
        onSubmitted: (transactionHash) => {
          sent.hash = transactionHash
          storePendingAssignment(bounty.id, unsignedFor(transactionHash))
        },
      })
    } catch (caught) {
      if (sent.hash !== null) {
        if (caught instanceof EscrowError && caught.transactionHash === null) {
          // FAILED definitivo: la aceptacion no hizo efecto y reintentar es
          // seguro, asi que no queda nada que recuperar.
          clearPendingAssignment(bounty.id)
        } else {
          // Timeout o fallo de red tras el envio: la aceptacion aun puede
          // entrar. Se conserva y no se vuelve a firmar otra.
          setPending(unsignedFor(sent.hash))
        }
      }

      setError(describe(caught))
      setStep('idle')
      return
    }

    const unsigned = unsignedFor(hash)

    setPending(unsigned)

    // Segundo popup de Freighter, esperado: la prueba de propiedad.
    await proveOwnership(unsigned)
  }

  return (
    <section className="action-panel" aria-labelledby="assignment-title">
      <div className="action-panel__head">
        <Handshake size={18} aria-hidden="true" />
        <div>
          <h2 className="action-panel__title" id="assignment-title">
            Ready for a developer
          </h2>
          <p>
            The reward is secured. Accept this task to bind your wallet to the
            bounty.
          </p>
        </div>
      </div>

      <dl className="action-panel__facts">
        <div>
          <dt>Reward</dt>
          <dd>{formatXlm(bounty.amount_stroops)} XLM</dd>
        </div>
        <div>
          <dt>Deadline</dt>
          <dd>{formatUnixSeconds(bounty.deadline_unix)}</dd>
        </div>
      </dl>

      <p className="action-panel__network">
        <AlertTriangle size={14} aria-hidden="true" />
        Stellar Testnet — no real funds
      </p>

      {accessIssue !== null ? (
        <AuthPrompt message={accessIssue.message} hint={accessIssue.hint} />
      ) : pending === null ? (
        <AcceptAction
          bounty={bounty}
          busy={busy}
          step={step}
          username={username}
          onUsernameChange={setUsername}
          onAccept={(address) => void acceptTask(address)}
        />
      ) : pending.walletSignature !== null ? (
        <SignedPending
          pending={{ ...pending, walletSignature: pending.walletSignature }}
          busy={busy}
          step={step}
          onRetry={(signed) => void confirmWithMergePay(signed)}
        />
      ) : (
        <UnsignedPending
          pending={pending}
          busy={busy}
          step={step}
          onSign={(unsigned) => void proveOwnership(unsigned)}
        />
      )}

      {error !== null ? (
        <p className="action-panel__error" role="alert">
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

function BusyLabel({ step }: { step: Step }) {
  return (
    <>
      <Loader size={16} aria-hidden="true" />
      {step === 'idle' ? 'Working...' : STEP_LABELS[step]}
    </>
  )
}

function PendingDetails({ pending }: { pending: PendingAssignment }) {
  return (
    <p className="action-panel__hint">
      GitHub <code>{pending.developerGithub}</code> · Wallet{' '}
      <code title={pending.developerAddress}>
        {abbreviateAddress(pending.developerAddress)}
      </code>{' '}
      · Transaction{' '}
      <code title={pending.transactionHash}>{pending.transactionHash}</code>
    </p>
  )
}

interface SignedPendingProps {
  pending: SignedAssignment
  busy: boolean
  step: Step
  onRetry: (signed: SignedAssignment) => void
}

/** Todo firmado: reintentar solo vuelve a llamar a POST /assigned. */
function SignedPending({ pending, busy, step, onRetry }: SignedPendingProps) {
  return (
    <div className="action-panel__submitted">
      <p className="action-panel__submitted-text">
        Assignment transaction already submitted.
      </p>
      <PendingDetails pending={pending} />
      <div className="action-panel__action">
        <button
          type="button"
          className="button button--primary"
          onClick={() => onRetry(pending)}
          disabled={busy}
        >
          {busy ? (
            <BusyLabel step={step} />
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

interface UnsignedPendingProps {
  pending: PendingAssignment
  busy: boolean
  step: Step
  onSign: (unsigned: PendingAssignment) => void
}

/**
 * La aceptacion esta en Stellar pero falta la prueba de propiedad. Firmarla
 * solo usa signMessage: no hay otra transaccion.
 */
function UnsignedPending({ pending, busy, step, onSign }: UnsignedPendingProps) {
  const wallet = useWallet()

  return (
    <div className="action-panel__submitted">
      <p className="action-panel__submitted-text">
        {step === 'proving'
          ? 'Confirm wallet ownership in Freighter.'
          : 'Assignment is on Stellar but wallet ownership still needs confirmation.'}
      </p>
      <p className="action-panel__hint">
        Freighter asks for a second signature. It proves you control the
        wallet that accepted this task and sends no transaction.
      </p>
      <PendingDetails pending={pending} />
      <OwnershipAction
        developerAddress={pending.developerAddress}
        busy={busy}
        step={step}
        wallet={wallet}
        onSign={() => onSign(pending)}
      />
    </div>
  )
}

interface OwnershipActionProps {
  developerAddress: string
  busy: boolean
  step: Step
  wallet: ReturnType<typeof useWallet>
  onSign: () => void
}

function OwnershipAction({ developerAddress, busy, step, wallet, onSign }: OwnershipActionProps) {
  if (busy) {
    return (
      <div className="action-panel__action">
        <button type="button" className="button button--primary" disabled>
          <BusyLabel step={step} />
        </button>
      </div>
    )
  }

  if (wallet.status === 'unavailable') {
    return (
      <div className="action-panel__action">
        <button
          type="button"
          className="button button--secondary"
          onClick={() => void wallet.refresh()}
        >
          <RotateCcw size={16} aria-hidden="true" />
          Check for Freighter
        </button>
        <span className="action-panel__hint">
          Install the Freighter browser extension to sign the ownership proof.
        </span>
      </div>
    )
  }

  if (wallet.status === 'connecting') {
    return (
      <div className="action-panel__action">
        <button type="button" className="button button--primary" disabled>
          <Loader size={16} aria-hidden="true" />
          Connecting...
        </button>
      </div>
    )
  }

  if (wallet.status === 'wrong-network') {
    return (
      <div className="action-panel__action">
        <button
          type="button"
          className="button button--secondary"
          onClick={() => void wallet.refresh()}
        >
          <RotateCcw size={16} aria-hidden="true" />
          Check network again
        </button>
        <span className="action-panel__hint action-panel__hint--warning">
          Switch Freighter to Testnet
        </span>
      </div>
    )
  }

  if (wallet.status !== 'connected' || wallet.address === null) {
    return (
      <div className="action-panel__action">
        <button
          type="button"
          className="button button--primary"
          onClick={() => void wallet.connect()}
        >
          <Wallet size={16} aria-hidden="true" />
          Connect wallet to sign
        </button>
      </div>
    )
  }

  // Solo la wallet que acepto puede probar la propiedad.
  if (wallet.address !== developerAddress) {
    return (
      <div className="action-panel__blocked">
        <p className="action-panel__blocked-title">
          Switch to the wallet that accepted this task (
          {abbreviateAddress(developerAddress)}).
        </p>
        <div className="action-panel__action">
          <button
            type="button"
            className="button button--secondary"
            onClick={() => void wallet.refresh()}
          >
            <RotateCcw size={16} aria-hidden="true" />
            Refresh wallet
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="action-panel__action">
      <button type="button" className="button button--primary" onClick={onSign}>
        <KeyRound size={16} aria-hidden="true" />
        Sign ownership proof
      </button>
    </div>
  )
}

interface AcceptActionProps {
  bounty: Bounty
  busy: boolean
  step: Step
  username: string
  onUsernameChange: (value: string) => void
  onAccept: (developerAddress: string) => void
}

function AcceptAction({
  bounty,
  busy,
  step,
  username,
  onUsernameChange,
  onAccept,
}: AcceptActionProps) {
  const wallet = useWallet()
  const configurationProblem = fundingConfigurationProblem()

  if (configurationProblem !== null) {
    return (
      <div className="action-panel__action">
        <button type="button" className="button button--primary" disabled>
          Accept task
        </button>
        <span className="action-panel__hint">
          Accepting is disabled: {configurationProblem}
        </span>
      </div>
    )
  }

  if (wallet.status === 'unavailable') {
    return (
      <div className="action-panel__action">
        <button
          type="button"
          className="button button--secondary"
          onClick={() => void wallet.refresh()}
        >
          <RotateCcw size={16} aria-hidden="true" />
          Check for Freighter
        </button>
        <span className="action-panel__hint">
          Install the Freighter browser extension to accept this task.
        </span>
      </div>
    )
  }

  if (wallet.status === 'connecting') {
    return (
      <div className="action-panel__action">
        <button type="button" className="button button--primary" disabled>
          <Loader size={16} aria-hidden="true" />
          Connecting...
        </button>
      </div>
    )
  }

  if (wallet.status === 'wrong-network') {
    return (
      <div className="action-panel__action">
        <button
          type="button"
          className="button button--secondary"
          onClick={() => void wallet.refresh()}
        >
          <RotateCcw size={16} aria-hidden="true" />
          Check network again
        </button>
        <span className="action-panel__hint action-panel__hint--warning">
          Switch Freighter to Testnet
        </span>
      </div>
    )
  }

  if (wallet.status !== 'connected' || wallet.address === null) {
    return (
      <div className="action-panel__action">
        <button
          type="button"
          className="button button--primary"
          onClick={() => void wallet.connect()}
        >
          <Wallet size={16} aria-hidden="true" />
          Connect wallet to accept
        </button>
        {wallet.status === 'error' && wallet.error !== null ? (
          <span className="action-panel__hint">{wallet.error}</span>
        ) : null}
      </div>
    )
  }

  const developerAddress = wallet.address

  // Proteccion de UX: el cliente no deberia aceptar su propia task.
  if (developerAddress === bounty.client_wallet) {
    return (
      <div className="action-panel__blocked">
        <p className="action-panel__blocked-title">
          You're connected with the client wallet.
        </p>
        <p className="action-panel__hint">
          Switch to a developer wallet to accept this task.
        </p>
        <div className="action-panel__action">
          <button
            type="button"
            className="button button--secondary"
            onClick={() => void wallet.refresh()}
          >
            <RotateCcw size={16} aria-hidden="true" />
            Refresh wallet
          </button>
        </div>
      </div>
    )
  }

  const usernameValid = isValidGithubUsername(username)
  const showUsernameError = username.trim() !== '' && !usernameValid

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (usernameValid && !busy) {
      onAccept(developerAddress)
    }
  }

  return (
    <form className="action-panel__form" onSubmit={handleSubmit} noValidate>
      <div className="field">
        <label htmlFor="developer-github">GitHub username</label>
        <input
          id="developer-github"
          type="text"
          value={username}
          onChange={(event) => onUsernameChange(event.target.value)}
          disabled={busy}
          autoComplete="off"
          spellCheck={false}
          maxLength={39}
          aria-invalid={showUsernameError ? true : undefined}
          aria-describedby="developer-github-hint"
          placeholder="octocat"
        />
        <p className="field__hint" id="developer-github-hint">
          This username must author the pull request that will be verified.
        </p>
        {showUsernameError ? (
          <p className="field__error">
            Use 1 to 39 letters, numbers or hyphens.
          </p>
        ) : null}
      </div>

      <div className="action-panel__action">
        <button
          type="submit"
          className="button button--primary"
          disabled={busy || !usernameValid}
        >
          {busy ? (
            <BusyLabel step={step} />
          ) : (
            <>
              <UserCheck size={16} aria-hidden="true" />
              Accept task
            </>
          )}
        </button>
        <button
          type="button"
          className="button button--secondary"
          onClick={() => void wallet.refresh()}
          disabled={busy}
        >
          <RotateCcw size={16} aria-hidden="true" />
          Refresh wallet
        </button>
      </div>

      <p className="action-panel__hint">
        Freighter will ask you to sign twice: first the assignment transaction,
        then a message that proves you own this wallet.
      </p>
    </form>
  )
}
