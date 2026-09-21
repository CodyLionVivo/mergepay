import { useEffect, useState } from 'react'
import { AlertTriangle, CircleDashed, RotateCcw, ShieldCheck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getBounty } from '../api/client'
import { BountyStatusBadge } from '../components/BountyStatusBadge'
import { AssignmentPanel } from '../components/AssignmentPanel'
import { FundingPanel } from '../components/FundingPanel'
import { PageHeader } from '../components/PageHeader'
import { SubmissionPanel } from '../components/SubmissionPanel'
import { SubmissionSummary } from '../components/SubmissionSummary'
import { abbreviateAddress } from '../stellar/walletContext'
import type { Bounty, Submission } from '../types/bounty'
import { abbreviateHash, formatUnixSeconds } from '../utils/format'
import { formatXlm } from '../utils/xlm'
import './BountyDetailPage.css'

/** Escrow ya creado y confirmado por MergePay, aun sin liberar. */
function FundedSummary({ bounty }: { bounty: Bounty }) {
  return (
    <section className="detail-notice detail-notice--success" aria-labelledby="funded-title">
      <ShieldCheck size={18} aria-hidden="true" />
      <div className="detail-notice__body">
        <h2 className="detail-notice__title" id="funded-title">
          Reward secured on Stellar Testnet.
        </h2>
        <dl className="funded-facts">
          <div>
            <dt>Reward</dt>
            <dd>{formatXlm(bounty.amount_stroops)} XLM</dd>
          </div>
          {bounty.client_wallet !== null ? (
            <div>
              <dt>Client wallet</dt>
              <dd>
                <code title={bounty.client_wallet}>
                  {abbreviateAddress(bounty.client_wallet)}
                </code>
              </dd>
            </div>
          ) : null}
          {bounty.create_tx_hash !== null ? (
            <div>
              <dt>Funding transaction</dt>
              <dd>
                <code title={bounty.create_tx_hash}>
                  {abbreviateHash(bounty.create_tx_hash)}
                </code>
              </dd>
            </div>
          ) : null}
          {bounty.base_sha !== null ? (
            <div>
              <dt>Base commit</dt>
              <dd>
                <code title={bounty.base_sha}>{abbreviateHash(bounty.base_sha)}</code>
              </dd>
            </div>
          ) : null}
        </dl>
      </div>
    </section>
  )
}

type LoadState = 'loading' | 'not-found' | 'error' | 'ready'

/** Estados en los que el PR ya esta registrado. */
const SUBMITTED_STATUSES = new Set([
  'SUBMITTED',
  'VERIFYING',
  'NEEDS_CHANGES',
  'ELIGIBLE',
  'PAID',
])

interface LoadResult {
  token: number
  bountyId: number
  state: 'not-found' | 'error' | 'ready'
  bounty: Bounty | null
  errorDetail: string
}

/** El id de la ruta solo vale si es un entero positivo. */
function parseBountyId(raw: string | undefined): number | null {
  if (raw === undefined || !/^\d+$/.test(raw)) {
    return null
  }

  const value = Number(raw)

  return Number.isSafeInteger(value) && value > 0 ? value : null
}

function NoticePanel({
  tone,
  title,
  children,
}: {
  tone: 'error' | 'muted'
  title: string
  children?: React.ReactNode
}) {
  return (
    <div className={`detail-state panel detail-state--${tone}`} role="alert">
      <AlertTriangle
        className="detail-state__icon"
        size={22}
        aria-hidden="true"
      />
      <h2 className="detail-state__title">{title}</h2>
      {children}
    </div>
  )
}

export function BountyDetailPage() {
  const { id } = useParams<{ id: string }>()
  const bountyId = parseBountyId(id)

  const [result, setResult] = useState<LoadResult | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  // La submission recien creada en esta visita. No hay endpoint para
  // leerla despues, asi que es lo unico que da el head SHA en el resumen.
  const [lastSubmission, setLastSubmission] = useState<Submission | null>(null)

  // Igual que en el marketplace: "loading" se deriva en render comparando el
  // resultado guardado con la task y el intento actuales.
  const settled =
    result !== null &&
    result.token === reloadToken &&
    result.bountyId === bountyId

  const state: LoadState = settled ? result.state : 'loading'
  const bounty = settled ? result.bounty : null
  const errorDetail = settled ? result.errorDetail : ''

  useEffect(() => {
    if (bountyId === null) {
      return
    }

    const controller = new AbortController()

    getBounty(bountyId, controller.signal)
      .then((data) => {
        setResult({
          token: reloadToken,
          bountyId,
          state: 'ready',
          bounty: data,
          errorDetail: '',
        })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return
        }

        const notFound = error instanceof ApiError && error.status === 404

        setResult({
          token: reloadToken,
          bountyId,
          state: notFound ? 'not-found' : 'error',
          bounty: null,
          errorDetail:
            !notFound && error instanceof ApiError ? error.message : '',
        })
      })

    return () => controller.abort()
  }, [bountyId, reloadToken])

  if (bountyId === null) {
    return (
      <div className="shell">
        <NoticePanel tone="muted" title="That task link is not valid">
          <p className="detail-state__text">
            Task identifiers are positive numbers, for example /bounties/1.
          </p>
          <Link className="button button--secondary" to="/">
            Back to tasks
          </Link>
        </NoticePanel>
      </div>
    )
  }

  if (state === 'loading') {
    return (
      <div className="shell">
        <p className="visually-hidden" role="status">
          Loading task
        </p>
        <div className="detail-skeleton-header" aria-hidden="true">
          <div className="skeleton skeleton--short" />
          <div className="skeleton skeleton--medium" />
        </div>
        <div className="detail-sections">
          {[0, 1, 2, 3].map((slot) => (
            <div className="panel" key={slot}>
              <div className="detail-skeleton" aria-hidden="true">
                <div className="skeleton skeleton--short" />
                <div className="skeleton skeleton--long" />
                <div className="skeleton skeleton--medium" />
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (state === 'not-found') {
    return (
      <div className="shell">
        <NoticePanel tone="muted" title={`Task #${bountyId} was not found`}>
          <p className="detail-state__text">
            It may have been removed, or the link points to a task that never
            existed.
          </p>
          <Link className="button button--secondary" to="/">
            Back to tasks
          </Link>
        </NoticePanel>
      </div>
    )
  }

  if (state === 'error' || bounty === null) {
    return (
      <div className="shell">
        <NoticePanel tone="error" title="Unable to load this task.">
          {errorDetail ? (
            <p className="detail-state__text">{errorDetail}</p>
          ) : null}
          <button
            type="button"
            className="button button--secondary"
            onClick={() => setReloadToken((token) => token + 1)}
          >
            <RotateCcw size={16} aria-hidden="true" />
            Try again
          </button>
        </NoticePanel>
      </div>
    )
  }

  const orderedCriteria = [...bounty.criteria].sort(
    (left, right) => left.position - right.position,
  )

  /** POST /funded y POST /assigned ya devuelven el bounty actualizado. */
  function replaceBounty(updated: Bounty) {
    setResult((current) =>
      current === null ? current : { ...current, bounty: updated },
    )
  }

  /** POST /submission devuelve la submission, no el bounty: hay que releerlo. */
  async function handleSubmitted(submission: Submission) {
    setLastSubmission(submission)

    try {
      replaceBounty(await getBounty(submission.bounty_id))
    } catch {
      // Si el refresco silencioso falla, recarga completa: muestra el loading
      // y, si el backend sigue caido, el estado de error con "Try again".
      setReloadToken((token) => token + 1)
    }
  }

  return (
    <div className="shell">
      <PageHeader
        eyebrow={`Task #${bounty.id}`}
        title={bounty.title}
        actions={<BountyStatusBadge status={bounty.status} />}
      />

      {bounty.status === 'DRAFT' ? (
        <FundingPanel bounty={bounty} onFunded={replaceBounty} />
      ) : null}

      {bounty.status === 'OPEN_FUNDED' ? (
        <AssignmentPanel bounty={bounty} onAssigned={replaceBounty} />
      ) : null}

      {bounty.status === 'ASSIGNED' ? (
        <SubmissionPanel bounty={bounty} onSubmitted={handleSubmitted} />
      ) : null}

      {SUBMITTED_STATUSES.has(bounty.status) ? (
        <SubmissionSummary
          bounty={bounty}
          submission={lastSubmission?.bounty_id === bounty.id ? lastSubmission : null}
        />
      ) : null}

      {bounty.create_tx_hash !== null && bounty.release_tx_hash === null ? (
        <FundedSummary bounty={bounty} />
      ) : null}

      <div className="detail-sections">
        <section className="panel detail-section--wide">
          <h2 className="panel__title">Overview</h2>
          <p className="detail-body">{bounty.description}</p>
        </section>

        <section className="panel">
          <h2 className="panel__title">Repository</h2>
          <dl className="detail-list">
            <div>
              <dt>Repository</dt>
              <dd>
                <code>
                  {bounty.repo_owner}/{bounty.repo_name}
                </code>
              </dd>
            </div>
            <div>
              <dt>Base branch</dt>
              <dd>
                <code>{bounty.base_branch}</code>
              </dd>
            </div>
            {bounty.base_sha ? (
              <div>
                <dt>Base commit</dt>
                <dd>
                  <code title={bounty.base_sha}>
                    {abbreviateHash(bounty.base_sha)}
                  </code>
                </dd>
              </div>
            ) : null}
          </dl>
        </section>

        <section className="panel">
          <h2 className="panel__title">Reward</h2>
          <p className="detail-amount">
            {formatXlm(bounty.amount_stroops)} <span>XLM</span>
          </p>
          <dl className="detail-list">
            <div>
              <dt>Deadline</dt>
              <dd>{formatUnixSeconds(bounty.deadline_unix)}</dd>
            </div>
          </dl>
        </section>

        <section className="panel detail-section--wide">
          <h2 className="panel__title">Acceptance criteria</h2>
          <p className="panel__hint">
            Requirements agreed upfront. They are evaluated once a pull request
            is submitted.
          </p>
          <ol className="criteria-list">
            {orderedCriteria.map((criterion) => (
              <li key={criterion.id}>
                <CircleDashed size={16} aria-hidden="true" />
                <span>{criterion.description}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className="panel">
          <h2 className="panel__title">Criteria commitment</h2>
          <p className="panel__hint">
            The digest anchored on-chain so the terms cannot change later.
          </p>
          {bounty.criteria_hash ? (
            <p className="detail-body">
              <code title={bounty.criteria_hash}>
                {abbreviateHash(bounty.criteria_hash)}
              </code>
            </p>
          ) : (
            <p className="detail-empty">Not committed yet</p>
          )}
        </section>

        <section className="panel">
          <h2 className="panel__title">GitHub verification</h2>
          {bounty.pull_request_number === null ? (
            <p className="detail-empty">Waiting for a pull request.</p>
          ) : (
            <p className="detail-body">
              Pull request <code>#{bounty.pull_request_number}</code>
            </p>
          )}
        </section>

        <section className="panel">
          <h2 className="panel__title">Settlement</h2>
          {bounty.release_tx_hash === null ? (
            <p className="detail-empty">No payout transaction yet.</p>
          ) : (
            <p className="detail-body">
              <code title={bounty.release_tx_hash}>
                {abbreviateHash(bounty.release_tx_hash)}
              </code>
            </p>
          )}
        </section>
      </div>
    </div>
  )
}
