import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  AlertTriangle,
  BadgeCheck,
  CheckCircle2,
  CircleDashed,
  Clock,
  Loader,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import {
  ApiError,
  findLatestVerification,
  getBounty,
  getSubmission,
  requestErrorMessage,
  verifyBounty,
} from '../api/client'
import { useAuth } from '../auth/authContext'
import { verificationIssue } from '../auth/taskAccess'
import type { Loadable } from '../hooks/useSubmittedWork'
import { AuthPrompt } from './AuthPrompt'
import { abbreviateAddress } from '../stellar/walletContext'
import type {
  Bounty,
  PullRequestVerificationResult,
  RequiredCheckResult,
  Submission,
  VerificationRecord,
} from '../types/bounty'
import { abbreviateHash } from '../utils/format'
import { formatXlm } from '../utils/xlm'
import './ActionPanel.css'
import './VerificationPanel.css'

/**
 * Con estos codigos POST /verify puede haber guardado ya un PASS (y el bounty
 * en ELIGIBLE) antes de fallar: 502 si Stellar rechazo el payout, 503 si no
 * esta configurado. Por eso tras ellos se relee el estado del backend.
 */
const REREAD_AFTER_STATUSES = new Set([502, 503])

type Tone = 'info' | 'success' | 'warning' | 'danger'

type View = 'ready' | 'pass' | 'fail' | 'pending' | 'eligible' | 'paid'

type Running = 'verify' | 'refresh' | null

/**
 * Que narrativa toca. El bounty manda sobre ELIGIBLE y PAID; en el resto, el
 * resultado de la ultima verificacion. Nunca se deduce nada de los checks.
 */
function pickView(bountyStatus: string, latest: VerificationRecord | null): View {
  if (bountyStatus === 'PAID') {
    return 'paid'
  }

  if (bountyStatus === 'ELIGIBLE') {
    return 'eligible'
  }

  if (latest === null) {
    return 'ready'
  }

  switch (latest.result.status) {
    case 'PASS':
      return 'pass'
    case 'FAIL':
      return 'fail'
    default:
      return 'pending'
  }
}

interface VerificationPanelProps {
  bounty: Bounty
  latestVerification: Loadable<VerificationRecord | null>
  onBountyUpdated: (bounty: Bounty) => void
  onVerificationUpdated: (record: VerificationRecord) => void
  onSubmissionUpdated: (submission: Submission) => void
  /** Vuelve a pedir submission y verificacion tras un error de carga. */
  onReload: () => void
}

export function VerificationPanel({
  bounty,
  latestVerification,
  onBountyUpdated,
  onVerificationUpdated,
  onSubmissionUpdated,
  onReload,
}: VerificationPanelProps) {
  const auth = useAuth()

  const [running, setRunning] = useState<Running>(null)
  const [error, setError] = useState<string | null>(null)

  // El state tarda un render en deshabilitar los botones; la ref corta un
  // segundo request antes de que eso ocurra.
  const inFlight = useRef(false)

  async function exclusive(kind: Exclude<Running, null>, task: () => Promise<void>) {
    if (inFlight.current) {
      return
    }

    inFlight.current = true
    setRunning(kind)
    setError(null)

    try {
      await task()
    } finally {
      inFlight.current = false
      setRunning(null)
    }
  }

  /**
   * Tras un 200: el bounty puede haber pasado a PAID y el PR a otro commit.
   * Resultado y bounty se publican en el mismo render, para no mostrar un
   * PASS junto a un bounty que aun no refleja el payout.
   */
  async function publishVerification(record: VerificationRecord) {
    const [freshBounty, freshSubmission] = await Promise.allSettled([
      getBounty(bounty.id),
      getSubmission(bounty.id),
    ])

    onVerificationUpdated(record)

    if (freshSubmission.status === 'fulfilled') {
      onSubmissionUpdated(freshSubmission.value)
    }

    if (freshBounty.status === 'fulfilled') {
      onBountyUpdated(freshBounty.value)
    } else {
      setError('The verification finished, but the task status could not be refreshed.')
    }
  }

  /** Tras un 502/503: best-effort, lo que se pueda releer se muestra. */
  async function rereadAfterFailure() {
    const [freshBounty, freshVerification] = await Promise.allSettled([
      getBounty(bounty.id),
      findLatestVerification(bounty.id),
    ])

    if (freshBounty.status === 'fulfilled') {
      onBountyUpdated(freshBounty.value)
    }

    if (freshVerification.status === 'fulfilled' && freshVerification.value !== null) {
      onVerificationUpdated(freshVerification.value)
    }
  }

  function runVerification() {
    void exclusive('verify', async () => {
      let record: VerificationRecord

      try {
        record = await verifyBounty(bounty.id)
      } catch (caught) {
        if (caught instanceof ApiError && REREAD_AFTER_STATUSES.has(caught.status)) {
          await rereadAfterFailure()
        }

        // El ultimo resultado conocido se conserva: solo se anade el error.
        setError(requestErrorMessage(caught))
        return
      }

      await publishVerification(record)
    })
  }

  function refreshStatus() {
    void exclusive('refresh', async () => {
      try {
        onBountyUpdated(await getBounty(bounty.id))
      } catch (caught) {
        setError(requestErrorMessage(caught))
      }
    })
  }

  if (latestVerification.status === 'loading') {
    return (
      <PanelFrame tone="info" Icon={ShieldCheck} title="Verification" busy>
        <p className="action-panel__hint" role="status">
          Loading the latest verification...
        </p>
      </PanelFrame>
    )
  }

  if (latestVerification.status === 'error') {
    return (
      <PanelFrame tone="info" Icon={ShieldCheck} title="Verification">
        <div className="action-panel__error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <div className="action-panel__error-body">
            <p>Unable to load the latest verification.</p>
            <p className="action-panel__hint">{latestVerification.message}</p>
            <div className="action-panel__action">
              <button type="button" className="button button--secondary" onClick={onReload}>
                <RotateCcw size={16} aria-hidden="true" />
                Try again
              </button>
            </div>
          </div>
        </div>
      </PanelFrame>
    )
  }

  const latest = latestVerification.value
  const view = pickView(bounty.status, latest)
  const busy = running !== null

  const runningLabel =
    running === 'refresh'
      ? 'Refreshing task status...'
      : view === 'eligible'
        ? 'Retrying settlement...'
        : 'Checking GitHub...'

  // Los resultados siguen siendo publicos; solo la accion queda restringida.
  const accessIssue = verificationIssue(auth, bounty)

  function gatedAction(children: ReactNode) {
    if (accessIssue !== null) {
      return <AuthPrompt message={accessIssue.message} hint={accessIssue.hint} />
    }

    return <div className="action-panel__action">{children}</div>
  }

  function verifyButton(label: string, Icon: LucideIcon, primary: boolean) {
    return (
      <button
        type="button"
        className={`button ${primary ? 'button--primary' : 'button--secondary'}`}
        onClick={runVerification}
        disabled={busy}
      >
        {running === 'verify' ? (
          <>
            <Loader size={16} aria-hidden="true" />
            {runningLabel}
          </>
        ) : (
          <>
            <Icon size={16} aria-hidden="true" />
            {label}
          </>
        )}
      </button>
    )
  }

  const feedback = (
    <>
      {error !== null ? (
        <div className="action-panel__error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <p>{error}</p>
        </div>
      ) : null}
      {busy ? (
        <p className="visually-hidden" role="status">
          {runningLabel}
        </p>
      ) : null}
    </>
  )

  const details = latest !== null ? <VerificationDetails record={latest} /> : null

  if (view === 'paid') {
    return (
      <PanelFrame tone="success" Icon={BadgeCheck} title="Payout completed" highlight>
        <p className="verification-panel__lead">
          The pull request passed verification and the secured reward was released
          automatically on Stellar Testnet.
        </p>

        <p className="action-panel__network">
          <AlertTriangle size={14} aria-hidden="true" />
          Stellar Testnet — no real funds
        </p>

        <dl className="action-panel__facts">
          <div>
            <dt>Reward</dt>
            <dd>{formatXlm(bounty.amount_stroops)} XLM</dd>
          </div>
          {bounty.developer_wallet !== null ? (
            <div>
              <dt>Developer</dt>
              <dd>
                <code title={bounty.developer_wallet}>
                  {abbreviateAddress(bounty.developer_wallet)}
                </code>
              </dd>
            </div>
          ) : null}
          {bounty.release_tx_hash !== null ? (
            <div>
              <dt>Payout transaction</dt>
              <dd>
                <code title={bounty.release_tx_hash}>
                  {abbreviateHash(bounty.release_tx_hash)}
                </code>
              </dd>
            </div>
          ) : null}
          {latest !== null ? (
            <>
              <div>
                <dt>Verification</dt>
                <dd>{latest.result.status}</dd>
              </div>
              <div>
                <dt>Head commit</dt>
                <dd>
                  <code title={latest.result.head_sha}>
                    {abbreviateHash(latest.result.head_sha)}
                  </code>
                </dd>
              </div>
            </>
          ) : null}
        </dl>

        {details}
      </PanelFrame>
    )
  }

  if (view === 'eligible') {
    return (
      <PanelFrame tone="success" Icon={ShieldCheck} title="Code verified">
        {latest?.result.eligible_for_payout ? <EligibleTag /> : null}

        <p className="verification-panel__notice">
          <AlertTriangle size={16} aria-hidden="true" />
          All agreed checks passed, but the Stellar payout has not been confirmed.
        </p>

        {gatedAction(
          <>
            {verifyButton('Retry settlement', RotateCcw, true)}
            <span className="action-panel__hint">
              MergePay checks the pull request again before retrying the payout.
            </span>
          </>,
        )}

        {feedback}
        {details}
      </PanelFrame>
    )
  }

  if (view === 'ready') {
    return (
      <PanelFrame tone="info" Icon={ShieldCheck} title="Ready for verification">
        <p className="verification-panel__lead">
          MergePay will inspect the pull request and the required GitHub checks. A
          passing result releases the secured reward automatically.
        </p>

        {gatedAction(
          <>
            {verifyButton('Run verification', PlayCircle, true)}
            <span className="action-panel__hint">
              No manual payment approval is required after a passing verification.
            </span>
          </>,
        )}

        {feedback}
      </PanelFrame>
    )
  }

  if (view === 'pass') {
    // PASS ya guardado pero el bounty leido aun no dice ELIGIBLE ni PAID: solo
    // pasa si fallo el refresco posterior, asi que se ofrece releerlo.
    return (
      <PanelFrame tone="success" Icon={ShieldCheck} title="Code verified">
        <p className="verification-panel__lead">All required checks passed.</p>
        {latest?.result.eligible_for_payout ? <EligibleTag /> : null}

        <div className="action-panel__action">
          <button
            type="button"
            className="button button--secondary"
            onClick={refreshStatus}
            disabled={busy}
          >
            {running === 'refresh' ? (
              <>
                <Loader size={16} aria-hidden="true" />
                {runningLabel}
              </>
            ) : (
              <>
                <RefreshCw size={16} aria-hidden="true" />
                Refresh payout status
              </>
            )}
          </button>
        </div>

        {feedback}
        {details}
      </PanelFrame>
    )
  }

  if (view === 'fail') {
    return (
      <PanelFrame tone="danger" Icon={XCircle} title="Changes required">
        <p className="verification-panel__lead">
          The pull request does not currently satisfy the agreed verification rules.
        </p>

        {latest !== null && latest.result.reasons.length > 0 ? (
          <ul className="action-panel__reasons">
            {latest.result.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}

        {gatedAction(
          <>
            {verifyButton('Check again', RotateCcw, true)}
            <span className="action-panel__hint">
              Push fixes to the same pull request, then check again. No new
              submission is needed.
            </span>
          </>,
        )}

        {feedback}
        {details}
      </PanelFrame>
    )
  }

  return (
    <PanelFrame tone="warning" Icon={Clock} title="Checks still running">
      <p className="verification-panel__lead">
        One or more required GitHub checks are not complete yet.
      </p>

      {gatedAction(verifyButton('Check again', RotateCcw, true))}

      {feedback}
      {details}
    </PanelFrame>
  )
}

function PanelFrame({
  tone,
  Icon,
  title,
  busy = false,
  highlight = false,
  children,
}: {
  tone: Tone
  Icon: LucideIcon
  title: string
  busy?: boolean
  highlight?: boolean
  children: ReactNode
}) {
  const classes = [
    'action-panel',
    'verification-panel',
    `verification-panel--${tone}`,
    highlight ? 'verification-panel--highlight' : '',
  ]

  return (
    <section
      className={classes.filter(Boolean).join(' ')}
      aria-labelledby="verification-title"
      aria-busy={busy || undefined}
    >
      <div className="action-panel__head">
        <Icon size={highlight ? 22 : 18} aria-hidden="true" />
        <h2 className="action-panel__title" id="verification-title">
          {title}
        </h2>
      </div>
      {children}
    </section>
  )
}

function EligibleTag() {
  return (
    <p className="verification-tag verification-tag--success">
      <CheckCircle2 size={14} aria-hidden="true" />
      Eligible for automatic payout
    </p>
  )
}

// ─────────────────────────────────────────
// Detalle del resultado: checks y reglas.
// ─────────────────────────────────────────

type ItemTone = 'success' | 'muted' | 'warning' | 'danger'

interface ItemState {
  tone: ItemTone
  label: string
  Icon: LucideIcon
}

const CONCLUSION_LABELS: Record<string, string> = {
  failure: 'Failed',
  cancelled: 'Cancelled',
  timed_out: 'Timed out',
  action_required: 'Action required',
  startup_failure: 'Startup failed',
  skipped: 'Skipped',
  neutral: 'Neutral',
  stale: 'Stale',
}

/** "some_value" → "Some value", para conclusiones que no estan en la tabla. */
function humanize(value: string): string {
  const spaced = value.replace(/_/g, ' ')

  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Solo presentacion: `passed` lo decidio el backend. */
function describeCheck(check: RequiredCheckResult): ItemState {
  if (check.passed) {
    return { tone: 'success', label: 'Passed', Icon: CheckCircle2 }
  }

  if (check.status === 'missing') {
    return { tone: 'muted', label: 'Missing', Icon: CircleDashed }
  }

  if (check.status !== 'completed') {
    return { tone: 'warning', label: 'Pending', Icon: Clock }
  }

  const label =
    check.conclusion === null
      ? 'No conclusion'
      : (CONCLUSION_LABELS[check.conclusion] ?? humanize(check.conclusion))

  return { tone: 'danger', label, Icon: XCircle }
}

const PASSED_RULE: ItemState = { tone: 'success', label: 'Passed', Icon: CheckCircle2 }
const FAILED_RULE: ItemState = { tone: 'danger', label: 'Failed', Icon: XCircle }

const RULES: { key: keyof PullRequestVerificationResult; label: string }[] = [
  { key: 'repository_valid', label: 'Repository matches' },
  { key: 'base_branch_valid', label: 'Base branch matches' },
  { key: 'base_sha_valid', label: 'Base commit matches' },
  { key: 'developer_valid', label: 'Developer matches PR author' },
  { key: 'pr_open', label: 'Pull request is open' },
  { key: 'pr_not_draft', label: 'Pull request is not draft' },
  { key: 'protected_files_valid', label: 'Protected files unchanged' },
]

const CHECKED_AT = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

function formatCheckedAt(value: string): string {
  // El backend guarda UTC sin zona; sin la Z el navegador lo leeria como local.
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value)
  const parsed = new Date(hasZone ? value : `${value}Z`)

  return Number.isNaN(parsed.getTime()) ? value : CHECKED_AT.format(parsed)
}

function VerificationDetails({ record }: { record: VerificationRecord }) {
  const { result } = record

  return (
    <div className="verification-details">
      <p className="verification-details__meta">
        Commit <code title={result.head_sha}>{abbreviateHash(result.head_sha)}</code>
        {' · '}
        Checked {formatCheckedAt(record.created_at)}
      </p>

      <div className="verification-details__group">
        <h3 className="verification-details__title">Required checks</h3>
        <ul className="verification-list">
          {result.checks.map((check) => {
            const state = describeCheck(check)

            return (
              <VerificationItem key={check.name} state={state}>
                <code>{check.name}</code>
                <span className="verification-item__detail">
                  status: {check.status}
                  {check.conclusion !== null ? ` · conclusion: ${check.conclusion}` : ''}
                </span>
              </VerificationItem>
            )
          })}
        </ul>
      </div>

      <div className="verification-details__group">
        <h3 className="verification-details__title">Verification rules</h3>
        <ul className="verification-list">
          {RULES.map((rule) => (
            <VerificationItem
              key={rule.key}
              state={result[rule.key] === true ? PASSED_RULE : FAILED_RULE}
            >
              <span>{rule.label}</span>
              {rule.key === 'protected_files_valid' &&
              !result.protected_files_valid &&
              result.protected_files_modified.length > 0 ? (
                <ul className="verification-item__files">
                  {result.protected_files_modified.map((path) => (
                    <li key={path}>
                      <code>{path}</code>
                    </li>
                  ))}
                </ul>
              ) : null}
            </VerificationItem>
          ))}
        </ul>
      </div>
    </div>
  )
}

function VerificationItem({
  state,
  children,
}: {
  state: ItemState
  children: ReactNode
}) {
  const { Icon } = state

  return (
    <li className={`verification-item verification-item--${state.tone}`}>
      <Icon size={16} aria-hidden="true" />
      <div className="verification-item__body">{children}</div>
      <span className="verification-item__state">{state.label}</span>
    </li>
  )
}
