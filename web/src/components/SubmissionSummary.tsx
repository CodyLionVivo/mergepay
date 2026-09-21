import { GitPullRequest } from 'lucide-react'
import { abbreviateAddress } from '../stellar/walletContext'
import type { Bounty, Submission } from '../types/bounty'
import { abbreviateHash } from '../utils/format'
import './ActionPanel.css'

interface SubmissionSummaryProps {
  bounty: Bounty
  /**
   * La submission recien creada, si esta visita la registro. No hay endpoint
   * para leerla despues, asi que tras un refresh se usan los datos del bounty.
   */
  submission: Submission | null
}

/** El PR ya registrado. Los checks todavia no se muestran en esta fase. */
export function SubmissionSummary({ bounty, submission }: SubmissionSummaryProps) {
  const pullRequestNumber = submission?.pull_request_number ?? bounty.pull_request_number

  // Al registrar la submission el backend exige que el autor del PR sea el
  // developer asignado, asi que sin la submission a mano coincide con este.
  const author = submission?.author ?? bounty.developer_github

  return (
    <section className="action-panel action-panel--done" aria-labelledby="submitted-title">
      <div className="action-panel__head">
        <GitPullRequest size={18} aria-hidden="true" />
        <div>
          <h2 className="action-panel__title" id="submitted-title">
            Pull request submitted
          </h2>
          <p>The pull request is registered and waiting for verification.</p>
        </div>
      </div>

      <dl className="action-panel__facts">
        {pullRequestNumber !== null ? (
          <div>
            <dt>Pull request</dt>
            <dd>
              <code>PR #{pullRequestNumber}</code>
            </dd>
          </div>
        ) : null}
        {author !== null ? (
          <div>
            <dt>Author</dt>
            <dd>
              <code>{author}</code>
            </dd>
          </div>
        ) : null}
        {submission !== null ? (
          <div>
            <dt>Head commit</dt>
            <dd>
              <code title={submission.head_sha}>{abbreviateHash(submission.head_sha)}</code>
            </dd>
          </div>
        ) : null}
        {bounty.developer_wallet !== null ? (
          <div>
            <dt>Developer wallet</dt>
            <dd>
              <code title={bounty.developer_wallet}>
                {abbreviateAddress(bounty.developer_wallet)}
              </code>
            </dd>
          </div>
        ) : null}
      </dl>
    </section>
  )
}
