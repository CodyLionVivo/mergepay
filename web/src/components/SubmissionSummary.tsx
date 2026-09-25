import { t, useI18n } from '../i18n'
import { AlertTriangle, ExternalLink, GitPullRequest, RotateCcw } from 'lucide-react'
import type { Loadable } from '../hooks/useSubmittedWork'
import { abbreviateAddress } from '../stellar/walletContext'
import type { Bounty, Submission } from '../types/bounty'
import { abbreviateHash } from '../utils/format'
import { isCanonicalPullRequestUrl } from '../utils/github'
import './ActionPanel.css'

interface SubmissionSummaryProps {
  bounty: Bounty
  /** Leida de GET /submission: sobrevive a un refresh. */
  submission: Loadable<Submission>
  onRetry: () => void
}

/** El PR registrado para la task, tal como lo guardo el backend. */
export function SubmissionSummary({ bounty, submission, onRetry }: SubmissionSummaryProps) {
  useI18n()
  return (
    <section className="action-panel action-panel--done" aria-labelledby="submitted-title">
      <div className="action-panel__head">
        <GitPullRequest size={18} aria-hidden="true" />
        <div>
          <h2 className="action-panel__title" id="submitted-title">{t("Pull request submitted")}</h2>
          <p>{t("MergePay verifies the latest commit of this pull request.")}</p>
        </div>
      </div>

      {submission.status === 'loading' ? (
        <p className="action-panel__hint" role="status">{t("Loading pull request details...")}</p>
      ) : null}

      {submission.status === 'error' ? (
        <div className="action-panel__error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <div className="action-panel__error-body">
            <p>{t("Unable to load the pull request details.")}</p>
            <p className="action-panel__hint">{submission.message}</p>
            <div className="action-panel__action">
              <button type="button" className="button button--secondary" onClick={onRetry}>
                <RotateCcw size={16} aria-hidden="true" />{t("Try again")}</button>
            </div>
          </div>
        </div>
      ) : null}

      {submission.status === 'ready' ? (
        <SubmissionFacts bounty={bounty} submission={submission.value} />
      ) : null}
    </section>
  )
}

function SubmissionFacts({ bounty, submission }: { bounty: Bounty; submission: Submission }) {
  useI18n()
  const label = `PR #${submission.pull_request_number}`

  return (
    <dl className="action-panel__facts">
      <div>
        <dt>{t("Pull request")}</dt>
        <dd>
          {/* La URL ya la valido el backend al registrar el PR; aqui solo se
              enlaza si sigue siendo un PR de GitHub bien formado. */}
          {isCanonicalPullRequestUrl(submission.pull_request_url) ? (
            <a
              className="action-panel__link"
              href={submission.pull_request_url}
              target="_blank"
              rel="noreferrer"
            >
              <code>{t(label)}</code>
              <ExternalLink size={13} aria-hidden="true" />
              <span className="visually-hidden">{t("(opens in a new tab)")}</span>
            </a>
          ) : (
            <code>{t(label)}</code>
          )}
        </dd>
      </div>
      {submission.author !== null ? (
        <div>
          <dt>{t("Author")}</dt>
          <dd>
            <code>{submission.author}</code>
          </dd>
        </div>
      ) : null}
      <div>
        <dt>{t("Head SHA")}</dt>
        <dd>
          <code title={submission.head_sha}>{abbreviateHash(submission.head_sha)}</code>
        </dd>
      </div>
      <div>
        <dt>{t("Head branch")}</dt>
        <dd>
          <code>{submission.head_ref}</code>
        </dd>
      </div>
      {bounty.developer_wallet !== null ? (
        <div>
          <dt>{t("Developer wallet")}</dt>
          <dd>
            <code title={bounty.developer_wallet}>
              {abbreviateAddress(bounty.developer_wallet)}
            </code>
          </dd>
        </div>
      ) : null}
    </dl>
  )
}
