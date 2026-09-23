import { useState } from 'react'
import type { FormEvent } from 'react'
import { AlertTriangle, GitPullRequest, Loader, RotateCcw, Send, Wallet } from 'lucide-react'
import { ApiError, createSubmission } from '../api/client'
import { useAuth } from '../auth/authContext'
import { submissionIssue } from '../auth/taskAccess'
import { AuthPrompt } from './AuthPrompt'
import { abbreviateAddress, useWallet } from '../stellar/walletContext'
import type { Bounty, Submission } from '../types/bounty'
import { isCanonicalPullRequestUrl } from '../utils/github'
import './ActionPanel.css'

interface SubmissionError {
  message: string
  reasons: string[]
}

function toSubmissionError(error: unknown): SubmissionError {
  if (error instanceof ApiError) {
    return { message: error.message, reasons: error.reasons }
  }

  return {
    message:
      error instanceof Error && error.message
        ? error.message
        : 'Unable to reach the MergePay API. Check your connection and try again.',
    reasons: [],
  }
}

interface SubmissionPanelProps {
  bounty: Bounty
  onSubmitted: (submission: Submission) => Promise<void>
}

export function SubmissionPanel({ bounty, onSubmitted }: SubmissionPanelProps) {
  return (
    <section className="action-panel" aria-labelledby="submission-title">
      <div className="action-panel__head">
        <GitPullRequest size={18} aria-hidden="true" />
        <div>
          <h2 className="action-panel__title" id="submission-title">
            Submit your work
          </h2>
          <p>
            Open a pull request against the base branch, then register it here
            so MergePay can check it against the agreed criteria.
          </p>
        </div>
      </div>

      <dl className="action-panel__facts">
        <div>
          <dt>Assigned wallet</dt>
          <dd>
            {bounty.developer_wallet !== null ? (
              <code title={bounty.developer_wallet}>
                {abbreviateAddress(bounty.developer_wallet)}
              </code>
            ) : (
              'Unknown'
            )}
          </dd>
        </div>
        <div>
          <dt>GitHub developer</dt>
          <dd>
            {bounty.developer_github !== null ? (
              <code>{bounty.developer_github}</code>
            ) : (
              'Unknown'
            )}
          </dd>
        </div>
      </dl>

      <SubmissionAction bounty={bounty} onSubmitted={onSubmitted} />
    </section>
  )
}

function SubmissionAction({ bounty, onSubmitted }: SubmissionPanelProps) {
  const wallet = useWallet()
  const auth = useAuth()

  const accessIssue =
    wallet.status === 'connected' && wallet.address !== null
      ? submissionIssue(auth, wallet.address, bounty)
      : null

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
          Install the Freighter browser extension to submit your work.
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
          Connect wallet to submit
        </button>
        {wallet.status === 'error' && wallet.error !== null ? (
          <span className="action-panel__hint">{wallet.error}</span>
        ) : null}
      </div>
    )
  }

  // El backend exige sesion del developer asignado; la UI no deja ni
  // intentarlo con otra wallet.
  if (accessIssue !== null) {
    return <AuthPrompt message={accessIssue.message} hint={accessIssue.hint} />
  }

  return <PullRequestForm bounty={bounty} onSubmitted={onSubmitted} />
}

function PullRequestForm({ bounty, onSubmitted }: SubmissionPanelProps) {
  const [url, setUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<SubmissionError | null>(null)

  const urlValid = isCanonicalPullRequestUrl(url)
  const showUrlError = url.trim() !== '' && !urlValid

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (submitting || !urlValid) {
      return
    }

    setSubmitting(true)
    setError(null)

    let submission: Submission

    try {
      submission = await createSubmission(bounty.id, url.trim())
    } catch (caught) {
      setError(toSubmissionError(caught))
      setSubmitting(false)
      return
    }

    // Registrado: la pagina refresca el bounty y este panel desaparece. El
    // boton sigue deshabilitado mientras tanto para evitar un doble envio.
    await onSubmitted(submission)
  }

  return (
    <form className="action-panel__form" onSubmit={handleSubmit} noValidate>
      <div className="field">
        <label htmlFor="pull-request-url">Pull request URL</label>
        <input
          id="pull-request-url"
          type="url"
          inputMode="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          disabled={submitting}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={showUrlError ? true : undefined}
          aria-describedby="pull-request-url-hint"
          placeholder="https://github.com/owner/repository/pull/123"
        />
        <p className="field__hint" id="pull-request-url-hint">
          The pull request must be authored by{' '}
          {bounty.developer_github !== null ? (
            <code>{bounty.developer_github}</code>
          ) : (
            'the assigned developer'
          )}
          .
        </p>
        {showUrlError ? (
          <p className="field__error">
            Use https://github.com/owner/repository/pull/number, with no query or
            fragment.
          </p>
        ) : null}
      </div>

      <div className="action-panel__action">
        <button
          type="submit"
          className="button button--primary"
          disabled={submitting || !urlValid}
        >
          {submitting ? (
            <>
              <Loader size={16} aria-hidden="true" />
              Checking pull request...
            </>
          ) : (
            <>
              <Send size={16} aria-hidden="true" />
              Submit pull request
            </>
          )}
        </button>
      </div>

      {error !== null ? (
        <div className="action-panel__error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <div>
            <p>{error.message}</p>
            {error.reasons.length > 0 ? (
              <ul className="action-panel__reasons">
                {error.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      ) : null}

      {submitting ? (
        <p className="visually-hidden" role="status">
          Checking pull request...
        </p>
      ) : null}
    </form>
  )
}
