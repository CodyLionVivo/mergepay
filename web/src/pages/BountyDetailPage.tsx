import { t, useI18n } from '../i18n'
import { useEffect, useState } from 'react'
import { AlertTriangle, CircleDashed, RotateCcw } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getBounty } from '../api/client'
import { useAuth } from '../auth/authContext'
import { BountyLifecycle } from '../components/BountyLifecycle'
import { CopyButton } from '../components/CopyButton'
import { BountyStatusBadge } from '../components/BountyStatusBadge'
import { AssignmentPanel } from '../components/AssignmentPanel'
import { FundingPanel } from '../components/FundingPanel'
import { OnChainEvidencePanel } from '../components/OnChainEvidencePanel'
import { EscrowCard } from '../components/EscrowCard'
import { TransactionSuccess } from '../components/TransactionSuccess'
import { PageHeader } from '../components/PageHeader'
import { SubmissionPanel } from '../components/SubmissionPanel'
import { SubmissionSummary } from '../components/SubmissionSummary'
import { VerificationPanel } from '../components/VerificationPanel'
import { useSubmittedWork } from '../hooks/useSubmittedWork'
import type { Bounty, Submission } from '../types/bounty'
import { abbreviateHash, formatUnixSeconds } from '../utils/format'
import { formatXlm } from '../utils/xlm'
import './BountyDetailPage.css'

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
  /** Con que sesion se leyo: al cambiar, la task se vuelve a pedir. */
  identity: string
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
  useI18n()
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
  useI18n()
  const { id } = useParams<{ id: string }>()
  const bountyId = parseBountyId(id)

  const [result, setResult] = useState<LoadResult | null>(null)
  const [fundingConfirmed, setFundingConfirmed] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)

  const auth = useAuth()

  // Una task puede ser privada, asi que lo leido depende de quien pregunta.
  // Mientras se restaura la sesion guardada no se pide nada: preguntar como
  // anonimo daria un 404 que desapareceria al instante.
  const identity =
    auth.status === 'authenticated' && auth.wallet !== null ? auth.wallet : 'anonymous'
  const restoringSession = auth.status === 'checking'

  // Igual que en el marketplace: "loading" se deriva en render comparando el
  // resultado guardado con la task y el intento actuales.
  const settled =
    result !== null &&
    result.token === reloadToken &&
    result.bountyId === bountyId &&
    result.identity === identity

  const state: LoadState = settled ? result.state : 'loading'
  const bounty = settled ? result.bounty : null
  const errorDetail = settled ? result.errorDetail : ''

  // Con el PR registrado, submission y ultima verificacion se leen del
  // backend: un refresh reconstruye el estado sin depender de esta visita.
  const work = useSubmittedWork(
    bountyId,
    bounty !== null && SUBMITTED_STATUSES.has(bounty.status),
  )

  useEffect(() => {
    if (bountyId === null || restoringSession) {
      return
    }

    const controller = new AbortController()

    getBounty(bountyId, controller.signal)
      .then((data) => {
        setResult({
          token: reloadToken,
          bountyId,
          identity,
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
          identity,
          state: notFound ? 'not-found' : 'error',
          bounty: null,
          errorDetail:
            !notFound && error instanceof ApiError ? error.message : '',
        })
      })

    return () => controller.abort()
  }, [bountyId, reloadToken, identity, restoringSession])

  if (bountyId === null) {
    return (
      <div className="shell">
        <NoticePanel tone="muted" title={t("That task link is not valid")}>
          <p className="detail-state__text">{t("Task identifiers are positive numbers, for example /bounties/1.")}</p>
          <Link className="button button--secondary" to="/">{t("Back to tasks")}</Link>
        </NoticePanel>
      </div>
    )
  }

  if (state === 'loading') {
    return (
      <div className="shell">
        <p className="visually-hidden" role="status">{t("Loading task")}</p>
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
        <NoticePanel tone="muted" title={t("Task not found")}>
          <p className="detail-state__text">{t("It may have been removed or this link is unavailable.")}</p>
          <Link className="button button--secondary" to="/">{t("Back to tasks")}</Link>
        </NoticePanel>
      </div>
    )
  }

  if (state === 'error' || bounty === null) {
    return (
      <div className="shell">
        <NoticePanel tone="error" title={t("Unable to load this task.")}>
          {errorDetail ? (
            <p className="detail-state__text">{t(errorDetail)}</p>
          ) : null}
          <button
            type="button"
            className="button button--secondary"
            onClick={() => setReloadToken((token) => token + 1)}
          >
            <RotateCcw size={16} aria-hidden="true" />{t("Try again")}</button>
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

  /**
   * POST /submission devuelve la submission, no el bounty: hay que releerlo.
   * Con el bounty ya en SUBMITTED, la submission se carga de GET /submission.
   */
  async function handleSubmitted(submission: Submission) {
    try {
      replaceBounty(await getBounty(submission.bounty_id))
    } catch {
      // Si el refresco silencioso falla, recarga completa: muestra el loading
      // y, si el backend sigue caido, el estado de error con "Try again".
      setReloadToken((token) => token + 1)
    }
  }

  return (
    <div className="shell bounty-detail">
      <Link className="back-link" to="/">{t("Back to bounties")}</Link>
      <PageHeader eyebrow={`Bounty #${bounty.id}`} title={bounty.title} actions={<BountyStatusBadge status={bounty.status} />} />
      <BountyLifecycle status={bounty.status} />
      {fundingConfirmed && bounty.create_tx_hash && bounty.status === 'OPEN_FUNDED' ? <TransactionSuccess kind="funding" /> : null}
      <div className="bounty-layout">
        <aside className="bounty-sidebar" aria-label={t("Reward and next action")}>
          <EscrowCard amount={formatXlm(bounty.amount_stroops)} state={bounty.status === 'PAID' && bounty.release_tx_hash ? 'released' : bounty.status.endsWith('_REFUNDED') ? 'refunded' : bounty.create_tx_hash ? 'funded' : 'pending'} wallet={bounty.client_wallet} transaction={bounty.release_tx_hash || bounty.create_tx_hash} />
          <section className="reward-summary panel">
            <p className="hero__eyebrow">{t("Reward")}</p>
            <p className="detail-amount">{formatXlm(bounty.amount_stroops)} <span>{t("XLM units")}</span></p>
            <p className="reward-summary__state">{bounty.status === 'PAID' ? t("Payment confirmed by MergePay") : bounty.status === 'ELIGIBLE' ? t("Verified - payment not confirmed") : bounty.status === 'DRAFT' ? t("Draft - funding required") : ['CANCELLED_REFUNDED', 'EXPIRED_REFUNDED'].includes(bounty.status) ? t("Reward returned") : t("Funding recorded - not paid")}</p>
            <dl className="detail-list"><div><dt>{t("Deadline")}</dt><dd>{formatUnixSeconds(bounty.deadline_unix)}</dd></div>
              {bounty.developer_github ? <div><dt>{t("Assigned developer")}</dt><dd>{bounty.developer_github}</dd></div> : null}
            </dl>
            <details className="reward-note"><summary>{t("Testnet reward information")}</summary><p>{t("Amounts use 7-decimal XLM display units. The API does not identify the configured escrow token. Confirm the deployment uses native XLM before funding.")}</p></details>
          </section>
          {bounty.status === 'DRAFT' ? <FundingPanel bounty={bounty} onFunded={(updated) => { replaceBounty(updated); setFundingConfirmed(Boolean(updated.create_tx_hash)) }} /> : null}
          {bounty.status === 'OPEN_FUNDED' ? <AssignmentPanel bounty={bounty} onAssigned={replaceBounty} /> : null}
          {bounty.status === 'ASSIGNED' ? <SubmissionPanel bounty={bounty} onSubmitted={handleSubmitted} /> : null}
          {SUBMITTED_STATUSES.has(bounty.status) ? <a className="button button--secondary" href="#verification">{t("View verification & payment")}</a> : null}
        </aside>
        <div className="bounty-content">
          <section className="bounty-section"><h2>{t("About this bounty")}</h2><p className="detail-body">{bounty.description}</p>
            <dl className="repository-summary"><div><dt>{t("Repository")}</dt><dd><code>{bounty.repo_owner}/{bounty.repo_name}</code></dd></div><div><dt>{t("Base branch")}</dt><dd><code>{bounty.base_branch}</code></dd></div></dl>
          </section>
          <section className="bounty-section"><h2>{t("Acceptance criteria")}</h2><p className="panel__hint">{t("Agreed requirements, not individual pass results. Verification checks are shown separately below.")}</p>
            <ol className="criteria-list">{orderedCriteria.map((criterion) => <li key={criterion.id}><CircleDashed size={16} aria-hidden="true" /><span>{criterion.description}{!criterion.required ? <small>{t("- Optional")}</small> : null}</span></li>)}</ol>
          </section>
          {SUBMITTED_STATUSES.has(bounty.status) ? <>
            <SubmissionSummary bounty={bounty} submission={work.submission} onRetry={work.reload} />
            <div id="verification"><VerificationPanel bounty={bounty} latestVerification={work.verification} onBountyUpdated={replaceBounty} onVerificationUpdated={work.setVerification} onSubmissionUpdated={work.setSubmission} onReload={work.reload} /></div>
          </> : <section className="bounty-section"><h2>{t("Pull request & verification")}</h2><p className="detail-empty">{bounty.status === 'ASSIGNED' ? t("Submit your open pull request using the action panel. Then run verification to check its latest commit.") : t("After a developer accepts this bounty, their pull request and verification results appear here.")}</p></section>}
          <details className="technical-disclosure"><summary>{t("Technical details & on-chain evidence")}</summary>
            <dl className="detail-list"><div><dt>{t("Base commit")}</dt><dd>{bounty.base_sha ? <><code>{abbreviateHash(bounty.base_sha)}</code><CopyButton value={bounty.base_sha} label={t("base commit")} /></> : t("Recorded when funding is confirmed")}</dd></div><div><dt>{t("Criteria commitment")}</dt><dd>{bounty.criteria_hash ? <><code>{abbreviateHash(bounty.criteria_hash)}</code><CopyButton value={bounty.criteria_hash} label={t("criteria commitment")} /></> : t("Not recorded")}</dd></div></dl>
            {bounty.create_tx_hash !== null ? <OnChainEvidencePanel bounty={bounty} submission={SUBMITTED_STATUSES.has(bounty.status) && work.submission.status === 'ready' ? work.submission.value : null} verification={work.verification} /> : <p className="detail-empty">{t("No funding transaction recorded yet.")}</p>}
          </details>
        </div>
      </div>
    </div>
  )
}
