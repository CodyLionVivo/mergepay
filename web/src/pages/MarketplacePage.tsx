import { t, useI18n } from '../i18n'
import { useEffect, useState } from 'react'
import { AlertTriangle, Plus, RotateCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, getBounties } from '../api/client'
import { BountyCarousel } from '../components/BountyCarousel'
import { ProductFlowCarousel } from '../components/ProductFlowCarousel'
import { MergePayCard } from '../components/MergePayCard'
import type { Bounty } from '../types/bounty'
import './MarketplacePage.css'
import './MarketplaceBoard.css'

type LoadState = 'loading' | 'error' | 'ready'

const SKELETON_CARDS = [0, 1, 2]

interface LoadResult {
  token: number
  state: 'error' | 'ready'
  bounties: Bounty[]
  errorDetail: string
}

export function MarketplacePage() {
  useI18n()
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
        <p className="hero__eyebrow">{t("The developer bounty marketplace")}</p>
        <h1 className="hero__title">{t("Good code. Clear rewards.")}</h1>
        <p className="hero__lede">{t("Find your next contribution. Build through GitHub with rewards funded upfront on Stellar.")}</p>

        <div className="hero__actions">
          <Link className="button button--primary" to="/bounties/new">{t("Create bounty")}</Link>
        </div>
      </section>

      <p className="marketplace-network">{t("Stellar Testnet - Rewards shown in XLM display units")}</p>
      <div className="marketplace-board">
      <section className="tasks" id="open-tasks" aria-labelledby="open-tasks-title">
        <div className="tasks__head">
          <h2 className="tasks__title" id="open-tasks-title">{t("Available bounties")}</h2>
          {state === 'ready' && bounties.length > 0 ? (
            <p className="tasks__note">
              {t(bounties.length === 1 ? '{count} task' : '{count} tasks', { count: bounties.length })}
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
          <p className="visually-hidden" role="status">{t("Loading tasks")}</p>
        ) : null}

        {state === 'error' ? (
          <div className="tasks__state panel" role="alert">
            <AlertTriangle
              className="tasks__state-icon tasks__state-icon--error"
              size={22}
              aria-hidden="true"
            />
            <h3 className="tasks__state-title">{t("Unable to load bounties")}</h3>
            <p className="tasks__state-text">{t("MergePay couldn’t reach the service.")}</p>
            {errorDetail ? <details className="error-details"><summary>{t("Technical details")}</summary><p>{t(errorDetail)}</p></details> : null}
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setReloadToken((token) => token + 1)}
            >
              <RotateCcw size={16} aria-hidden="true" />{t("Try again")}</button>
          </div>
        ) : null}

        {state === 'ready' && bounties.length === 0 ? (
          <div className="tasks__state panel">
            <h3 className="tasks__state-title">{t("No available bounties")}</h3>
            <p className="tasks__state-text">{t("Fund a bounty to make it available here. Drafts and assigned work are not publicly listed.")}</p>
            <Link className="button button--primary" to="/bounties/new">
              <Plus size={16} aria-hidden="true" />{t("Create bounty")}</Link>
          </div>
        ) : null}

        {state === 'ready' && bounties.length > 0 ? (
          <BountyCarousel bounties={bounties} />
        ) : null}
      </section>
      <MergePayCard />
      </div>
      <ProductFlowCarousel />
    </div>
  )
}
