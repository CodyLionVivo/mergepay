import { useEffect, useState } from 'react'
import { AlertTriangle, CircleDashed, Info, RotateCcw } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getBounty } from '../api/client'
import { BountyStatusBadge } from '../components/BountyStatusBadge'
import { PageHeader } from '../components/PageHeader'
import type { Bounty } from '../types/bounty'
import { abbreviateHash, formatUnixSeconds } from '../utils/format'
import { formatXlm } from '../utils/xlm'
import './BountyDetailPage.css'

type LoadState = 'loading' | 'not-found' | 'error' | 'ready'

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

  return (
    <div className="shell">
      <PageHeader
        eyebrow={`Task #${bounty.id}`}
        title={bounty.title}
        actions={<BountyStatusBadge status={bounty.status} />}
      />

      {bounty.status === 'DRAFT' ? (
        <section className="detail-notice" aria-labelledby="draft-title">
          <Info size={18} aria-hidden="true" />
          <div className="detail-notice__body">
            <h2 className="detail-notice__title" id="draft-title">
              Draft task
            </h2>
            <p>
              Draft tasks are created in MergePay but their reward has not been
              secured on Stellar yet.
            </p>
            <div className="detail-notice__action">
              <button type="button" className="button button--primary" disabled>
                Secure reward
              </button>
              <span className="detail-notice__hint">
                Wallet funding is added in the next step.
              </span>
            </div>
          </div>
        </section>
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
