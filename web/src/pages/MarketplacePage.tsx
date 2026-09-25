import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, ListChecks, Plus, RotateCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, getBounties } from '../api/client'
import { BountyStatusBadge } from '../components/BountyStatusBadge'
import type { Bounty } from '../types/bounty'
import { formatUnixSeconds } from '../utils/format'
import { formatXlm } from '../utils/xlm'
import './MarketplacePage.css'

type LoadState = 'loading' | 'error' | 'ready'

const SKELETON_CARDS = [0, 1, 2]

interface LoadResult {
  token: number
  state: 'error' | 'ready'
  bounties: Bounty[]
  errorDetail: string
}

export function MarketplacePage() {
  const [result, setResult] = useState<LoadResult | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  // El estado de carga se deriva en render: mientras el resultado guardado no
  // corresponda al intento actual, seguimos cargando.
  const settled = result !== null && result.token === reloadToken
  const state: LoadState = settled ? result.state : 'loading'
  const bounties = settled ? result.bounties : []
  const errorDetail = settled ? result.errorDetail : ''

  useEffect(() => {
    const controller = new AbortController()

    getBounties(controller.signal)
      .then((data) => {
        setResult({
          token: reloadToken,
          state: 'ready',
          bounties: data,
          errorDetail: '',
        })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return
        }

        setResult({
          token: reloadToken,
          state: 'error',
          bounties: [],
          errorDetail: error instanceof ApiError ? error.message : 'We could not reach MergePay. Check your connection and try again.',
        })
      })

    return () => controller.abort()
  }, [reloadToken])

  return (
    <div className="shell">
      <section className="hero">
        <p className="hero__eyebrow">Automated rewards for verified code</p>
        <h1 className="hero__title">Get paid when the code passes.</h1>
        <p className="hero__lede">
          Development tasks with rewards secured upfront and released when the
          agreed checks pass.
        </p>

        <div className="hero__actions">
          <a className="button button--primary" href="#open-tasks">
            Explore bounties
            <ArrowRight size={16} aria-hidden="true" />
          </a>
          <Link className="button button--secondary" to="/bounties/new">
            Create bounty
          </Link>
        </div>
      </section>

      <p className="marketplace-network">Stellar Testnet - Rewards shown in XLM display units</p>
      <section className="tasks" id="open-tasks" aria-labelledby="open-tasks-title">
        <div className="tasks__head">
          <h2 className="tasks__title" id="open-tasks-title">
            Available bounties
          </h2>
          {state === 'ready' && bounties.length > 0 ? (
            <p className="tasks__note">
              {bounties.length === 1 ? '1 task' : `${bounties.length} tasks`}
            </p>
          ) : null}
        </div>

        {state === 'loading' ? (
          <ul className="tasks__grid" aria-hidden="true">
            {SKELETON_CARDS.map((slot) => (
              <li key={slot}>
                <div className="task-card card task-card--skeleton">
                  <div className="skeleton skeleton--short" />
                  <div className="skeleton skeleton--long" />
                  <div className="skeleton skeleton--medium" />
                  <div className="task-card__meta">
                    <div className="skeleton skeleton--short" />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : null}

        {state === 'loading' ? (
          <p className="visually-hidden" role="status">
            Loading tasks
          </p>
        ) : null}

        {state === 'error' ? (
          <div className="tasks__state panel" role="alert">
            <AlertTriangle
              className="tasks__state-icon tasks__state-icon--error"
              size={22}
              aria-hidden="true"
            />
            <h3 className="tasks__state-title">Unable to load tasks.</h3>
            {errorDetail ? (
              <p className="tasks__state-text">{errorDetail}</p>
            ) : null}
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setReloadToken((token) => token + 1)}
            >
              <RotateCcw size={16} aria-hidden="true" />
              Try again
            </button>
          </div>
        ) : null}

        {state === 'ready' && bounties.length === 0 ? (
          <div className="tasks__state panel">
            <h3 className="tasks__state-title">No available bounties</h3>
            <p className="tasks__state-text">
              Fund a bounty to make it available here. Drafts and assigned work are not publicly listed.
            </p>
            <Link className="button button--primary" to="/bounties/new">
              <Plus size={16} aria-hidden="true" />
              Create bounty
            </Link>
          </div>
        ) : null}

        {state === 'ready' && bounties.length > 0 ? (
          <ul className="tasks__grid">
            {bounties.map((bounty) => (
              <li key={bounty.id}>
                <Link to={`/bounties/${bounty.id}`} className="task-card card">
                  <BountyStatusBadge status={bounty.status} />

                  <h3 className="task-card__title">{bounty.title}</h3>
                  <p className="task-card__description">{bounty.description}</p>

                  <p className="task-card__repo">
                    <code>
                      {bounty.repo_owner}/{bounty.repo_name}
                    </code>
                  </p>

                  <dl className="task-card__meta">
                    <div className="task-card__metric">
                      <dt>Reward</dt>
                      <dd className="task-card__reward">
                        {formatXlm(bounty.amount_stroops)} XLM
                      </dd>
                    </div>
                    <div className="task-card__metric">
                      <dt>Criteria</dt>
                      <dd>
                        <ListChecks size={14} aria-hidden="true" />
                        {bounty.criteria.length}
                      </dd>
                    </div>
                  </dl>
                  <p className="task-card__deadline">Deadline - {formatUnixSeconds(bounty.deadline_unix)}</p>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  )
}
