import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  AlertTriangle,
  BadgeCheck,
  Blocks,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  ExternalLink,
  Radio,
  RotateCcw,
  XCircle,
} from 'lucide-react'
import { getOnChainBounty, requestErrorMessage } from '../api/client'
import type { Loadable } from '../hooks/useSubmittedWork'
import {
  stellarExpertContractUrl,
  stellarExpertSearchUrl,
  stellarLabContractUrl,
} from '../stellar/explorer'
import { abbreviateAddress } from '../stellar/walletContext'
import type { Bounty, OnChainBounty, Submission, VerificationRecord } from '../types/bounty'
import { abbreviateHash, formatUnixSeconds } from '../utils/format'
import { isCanonicalPullRequestUrl } from '../utils/github'
import { formatXlm } from '../utils/xlm'
import { CopyButton } from './CopyButton'
import './OnChainEvidencePanel.css'

const LOADING = { status: 'loading' } as const

interface Loaded {
  key: string
  onChain: Loadable<OnChainBounty>
}

/**
 * La lectura se repite cuando cambia el estado de la task (una aceptacion o
 * un payout cambian el contrato) o al reintentar. No hay polling.
 */
function readKey(
  bountyId: number,
  status: string,
  releaseTxHash: string | null,
  token: number,
): string {
  return `${bountyId}:${status}:${releaseTxHash ?? ''}:${token}`
}

interface OnChainEvidencePanelProps {
  bounty: Bounty
  /** El PR registrado, ya cargado por la pagina. Nunca se consulta GitHub aqui. */
  submission: Submission | null
  /** Ultima verificacion, solo para el resumen del settlement. */
  verification: Loadable<VerificationRecord | null>
}

export function OnChainEvidencePanel({
  bounty,
  submission,
  verification,
}: OnChainEvidencePanelProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [token, setToken] = useState(0)

  const bountyId = bounty.id
  const status = bounty.status
  const releaseTxHash = bounty.release_tx_hash

  const key = readKey(bountyId, status, releaseTxHash, token)
  const onChain: Loadable<OnChainBounty> = loaded?.key === key ? loaded.onChain : LOADING

  useEffect(() => {
    const requestKey = readKey(bountyId, status, releaseTxHash, token)
    const controller = new AbortController()

    getOnChainBounty(bountyId, controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) {
          setLoaded({ key: requestKey, onChain: { status: 'ready', value } })
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setLoaded({
            key: requestKey,
            onChain: { status: 'error', message: requestErrorMessage(error) },
          })
        }
      },
    )

    return () => controller.abort()
  }, [bountyId, status, releaseTxHash, token])

  return (
    <section className="evidence-panel" aria-labelledby="onchain-title">
      <div className="evidence-panel__head">
        <Blocks size={20} aria-hidden="true" />
        <div>
          <h2 className="evidence-panel__title" id="onchain-title">
            On-chain proof
          </h2>
          <p className="evidence-panel__subtitle">
            Independent evidence recorded on Stellar Testnet.
          </p>
        </div>
      </div>

      <div className="evidence-panel__badges">
        {onChain.status === 'ready' ? (
          <span className="evidence-badge evidence-badge--live">
            <Radio size={13} aria-hidden="true" />
            Live from Stellar Testnet
          </span>
        ) : null}
        <span className="evidence-badge evidence-badge--testnet">
          <AlertTriangle size={13} aria-hidden="true" />
          Testnet — no real funds
        </span>
      </div>

      {onChain.status === 'loading' ? (
        <div className="evidence-panel__loading">
          <p className="evidence-muted" role="status">
            Reading the contract on Stellar Testnet...
          </p>
          <div className="evidence-skeleton" aria-hidden="true">
            <div className="skeleton skeleton--long" />
            <div className="skeleton skeleton--medium" />
            <div className="skeleton skeleton--short" />
          </div>
        </div>
      ) : null}

      {onChain.status === 'error' ? (
        <>
          <div className="evidence-error" role="alert">
            <AlertTriangle size={16} aria-hidden="true" />
            <div className="evidence-error__body">
              <p className="evidence-error__title">Live contract state unavailable</p>
              <p>MergePay could not read the contract from Stellar Testnet right now.</p>
              <p className="evidence-muted">{onChain.message}</p>
              <div>
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => setToken((current) => current + 1)}
                >
                  <RotateCcw size={16} aria-hidden="true" />
                  Try again
                </button>
              </div>
            </div>
          </div>

          {/* Sin lectura live no se afirma nada del contrato: solo las
              referencias que MergePay ya tiene guardadas. */}
          <div className="evidence-block">
            <h3 className="evidence-block__title">Recorded transaction references</h3>
            <p className="evidence-muted">
              These transaction IDs are stored by MergePay. Live contract state could not
              be independently refreshed.
            </p>
            <TransactionFacts bounty={bounty} />
          </div>
        </>
      ) : null}

      {onChain.status === 'ready' ? (
        <Evidence
          bounty={bounty}
          onChain={onChain.value}
          submission={submission}
          verification={verification}
        />
      ) : null}
    </section>
  )
}

// ─────────────────────────────────────────
// Piezas pequenas reutilizadas en todo el panel.
// ─────────────────────────────────────────

function ExternalAction({ href, context, children }: {
  href: string
  /** Que abre, para lectores de pantalla cuando el texto visible se repite. */
  context?: string
  children: ReactNode
}) {
  return (
    <a className="evidence-link" href={href} target="_blank" rel="noreferrer">
      {children}
      <ExternalLink size={13} aria-hidden="true" />
      <span className="visually-hidden">
        {context ? ` (${context}, opens in a new tab)` : ' (opens in a new tab)'}
      </span>
    </a>
  )
}

/** Valor abreviado en pantalla, completo en title y al copiar. */
function Value({
  value,
  display,
  label,
  href,
}: {
  value: string
  display: string
  label: string
  /** Enlace a StellarExpert, cuando aplica. */
  href?: string
}) {
  return (
    <span className="evidence-value">
      <code title={value}>{display}</code>
      <CopyButton value={value} label={label} />
      {href !== undefined ? (
        <ExternalAction href={href} context={label}>
          View on StellarExpert
        </ExternalAction>
      ) : null}
    </span>
  )
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </div>
  )
}

/** Matches / Mismatch con icono y texto: el color nunca va solo. */
function MatchTag({ matches, matchText, mismatchText }: {
  matches: boolean
  matchText: string
  mismatchText: string
}) {
  const Icon = matches ? CheckCircle2 : XCircle

  return (
    <span className={`evidence-tag evidence-tag--${matches ? 'match' : 'mismatch'}`}>
      <Icon size={13} aria-hidden="true" />
      {matches ? matchText : mismatchText}
    </span>
  )
}

const hasText = (value: string | null): value is string =>
  value !== null && value.trim() !== ''

/**
 * Funding y payout tal como los guarda MergePay. No dependen de la lectura
 * live del contrato, asi que siguen visibles aunque el RPC falle.
 */
function TransactionFacts({ bounty }: { bounty: Bounty }) {
  return (
    <dl className="evidence-facts">
      {hasText(bounty.create_tx_hash) ? (
        <Fact term="Funding transaction">
          <Value
            value={bounty.create_tx_hash}
            display={abbreviateHash(bounty.create_tx_hash)}
            label="funding transaction"
            href={stellarExpertSearchUrl(bounty.create_tx_hash)}
          />
        </Fact>
      ) : null}
      <Fact term="Payout transaction">
        {hasText(bounty.release_tx_hash) ? (
          <Value
            value={bounty.release_tx_hash}
            display={abbreviateHash(bounty.release_tx_hash)}
            label="payout transaction"
            href={stellarExpertSearchUrl(bounty.release_tx_hash)}
          />
        ) : (
          <span className="evidence-muted">No payout transaction yet.</span>
        )}
      </Fact>
    </dl>
  )
}

// ─────────────────────────────────────────
// Contenido con la lectura on-chain ya hecha.
// ─────────────────────────────────────────

const CONTRACT_STATUS_TONES: Record<string, string> = {
  Open: 'info',
  Assigned: 'info',
  Paid: 'success',
  Cancelled: 'muted',
  Refunded: 'muted',
}

function Evidence({
  bounty,
  onChain,
  submission,
  verification,
}: {
  bounty: Bounty
  onChain: OnChainBounty
  submission: Submission | null
  verification: Loadable<VerificationRecord | null>
}) {
  const contractId = onChain.contract_id
  const released = onChain.contract_status === 'Paid' && bounty.release_tx_hash !== null

  const criteriaMatches =
    bounty.criteria_hash !== null &&
    onChain.criteria_hash.toLowerCase() === bounty.criteria_hash.toLowerCase()

  // Cada paso sale de un dato real; ninguno se deduce de otro.
  const steps: { label: string; done: boolean }[] = [
    { label: 'Reward secured', done: bounty.create_tx_hash !== null },
    { label: 'Terms committed', done: hasText(onChain.criteria_hash) },
    { label: 'Developer assigned', done: onChain.developer_wallet !== null },
    { label: 'Code verified', done: onChain.evidence_hash !== null },
    { label: 'Reward released', done: released },
  ]

  return (
    <div className="evidence-panel__content">
      {bounty.status === 'PAID' && released ? (
        <SettlementHero bounty={bounty} onChain={onChain} verification={verification} />
      ) : null}

      <div className="evidence-block evidence-block--wide">
        <h3 className="evidence-block__title">Proof flow</h3>
        <ol className="proof-flow">
          {steps.map((step, index) => {
            const Icon = step.done ? CheckCircle2 : CircleDashed

            return (
              <li
                key={step.label}
                className={`proof-step proof-step--${step.done ? 'done' : 'pending'}`}
              >
                {index > 0 ? (
                  <ChevronRight className="proof-step__arrow" size={14} aria-hidden="true" />
                ) : null}
                <Icon size={16} aria-hidden="true" />
                <span className="proof-step__label">{step.label}</span>
                <span className="proof-step__state">{step.done ? 'Confirmed' : 'Not yet'}</span>
              </li>
            )
          })}
        </ol>
      </div>

      <div className="evidence-block">
        <h3 className="evidence-block__title">Contract state</h3>
        <dl className="evidence-facts">
          <Fact term="Contract">
            {hasText(contractId) ? (
              <Value
                value={contractId}
                display={abbreviateAddress(contractId)}
                label="contract ID"
                href={stellarExpertContractUrl(contractId)}
              />
            ) : (
              'Unknown'
            )}
          </Fact>
          <Fact term="Contract state">
            <span
              className={`contract-status contract-status--${
                CONTRACT_STATUS_TONES[onChain.contract_status] ?? 'info'
              }`}
            >
              {onChain.contract_status}
            </span>
          </Fact>
          <Fact term="Escrow amount">{formatXlm(onChain.amount_stroops)} XLM</Fact>
          <Fact term="Deadline">{formatUnixSeconds(onChain.deadline_unix)}</Fact>
          <Fact term="Client">
            <Value
              value={onChain.client_wallet}
              display={abbreviateAddress(onChain.client_wallet)}
              label="client wallet"
              href={stellarExpertSearchUrl(onChain.client_wallet)}
            />
          </Fact>
          <Fact term="Developer">
            {hasText(onChain.developer_wallet) ? (
              <Value
                value={onChain.developer_wallet}
                display={abbreviateAddress(onChain.developer_wallet)}
                label="developer wallet"
                href={stellarExpertSearchUrl(onChain.developer_wallet)}
              />
            ) : (
              <span className="evidence-muted">Not assigned</span>
            )}
          </Fact>
        </dl>

        {hasText(contractId) ? (
          <div className="evidence-actions">
            <ExternalAction href={stellarExpertContractUrl(contractId)}>
              View contract on StellarExpert
            </ExternalAction>
            <ExternalAction href={stellarLabContractUrl(contractId)}>
              Inspect contract in Stellar Lab
            </ExternalAction>
          </div>
        ) : null}
      </div>

      <div className="evidence-block">
        <h3 className="evidence-block__title">Cryptographic commitments</h3>

        <div className="commitment">
          <div className="commitment__head">
            <span className="commitment__title">Criteria commitment</span>
            <MatchTag
              matches={criteriaMatches}
              matchText="Matches MergePay task"
              mismatchText="MISMATCH"
            />
          </div>
          <Value
            value={onChain.criteria_hash}
            display={abbreviateHash(onChain.criteria_hash)}
            label="criteria commitment"
          />
          <p className="evidence-muted">
            Commits to the acceptance criteria agreed before the task was funded.
          </p>
          {!criteriaMatches ? (
            // Con mismatch se ensenan los dos valores, no solo el del contrato.
            <dl className="evidence-compare">
              <Fact term="On Stellar">
                <code title={onChain.criteria_hash}>{abbreviateHash(onChain.criteria_hash)}</code>
              </Fact>
              <Fact term="MergePay task">
                {bounty.criteria_hash !== null ? (
                  <Value
                    value={bounty.criteria_hash}
                    display={abbreviateHash(bounty.criteria_hash)}
                    label="task criteria hash"
                  />
                ) : (
                  <span className="evidence-muted">Not recorded</span>
                )}
              </Fact>
            </dl>
          ) : null}
        </div>

        <div className="commitment">
          <div className="commitment__head">
            <span className="commitment__title">Evidence commitment</span>
            {onChain.evidence_hash !== null ? (
              <span className="evidence-tag evidence-tag--match">
                <CheckCircle2 size={13} aria-hidden="true" />
                Anchored on Stellar
              </span>
            ) : null}
          </div>
          {onChain.evidence_hash !== null ? (
            <>
              <Value
                value={onChain.evidence_hash}
                display={abbreviateHash(onChain.evidence_hash)}
                label="evidence commitment"
              />
              <p className="evidence-muted">
                Commits to the verified pull request evidence used to release the reward.
              </p>
            </>
          ) : (
            <p className="evidence-muted evidence-pending">
              <CircleDashed size={14} aria-hidden="true" />
              Verification evidence has not been anchored yet.
            </p>
          )}
        </div>
      </div>

      <ConsistencyChecks bounty={bounty} onChain={onChain} criteriaMatches={criteriaMatches} />

      <div className="evidence-block">
        <h3 className="evidence-block__title">Transactions</h3>
        <TransactionFacts bounty={bounty} />
      </div>

      {submission !== null ? (
        <div className="evidence-block evidence-block--wide">
          <h3 className="evidence-block__title">Off-chain verification source</h3>
          <dl className="evidence-facts evidence-facts--row">
            <Fact term="Pull request">
              <code>PR #{submission.pull_request_number}</code>
            </Fact>
            {submission.author !== null ? (
              <Fact term="GitHub author">
                <code>{submission.author}</code>
              </Fact>
            ) : null}
            <Fact term="Head SHA">
              <code title={submission.head_sha}>{abbreviateHash(submission.head_sha)}</code>
            </Fact>
          </dl>
          {isCanonicalPullRequestUrl(submission.pull_request_url) ? (
            <div className="evidence-actions">
              <ExternalAction href={submission.pull_request_url}>Open pull request</ExternalAction>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function SettlementHero({
  bounty,
  onChain,
  verification,
}: {
  bounty: Bounty
  onChain: OnChainBounty
  verification: Loadable<VerificationRecord | null>
}) {
  const githubResult =
    verification.status === 'loading'
      ? 'Loading...'
      : verification.status === 'ready' && verification.value !== null
        ? verification.value.result.status
        : 'Unavailable'

  return (
    <div className="evidence-hero evidence-block--wide">
      <h3 className="evidence-hero__title">
        <BadgeCheck size={20} aria-hidden="true" />
        Settlement independently verifiable
      </h3>

      <dl className="evidence-facts evidence-facts--row">
        <Fact term="GitHub">{githubResult}</Fact>
        <Fact term="Stellar contract">{onChain.contract_status}</Fact>
        <Fact term="Reward">{formatXlm(onChain.amount_stroops)} XLM</Fact>
        {hasText(onChain.developer_wallet) ? (
          <Fact term="Developer">
            <Value
              value={onChain.developer_wallet}
              display={abbreviateAddress(onChain.developer_wallet)}
              label="developer wallet"
            />
          </Fact>
        ) : null}
        {onChain.evidence_hash !== null ? (
          <Fact term="Evidence commitment">
            <Value
              value={onChain.evidence_hash}
              display={abbreviateHash(onChain.evidence_hash)}
              label="evidence commitment"
            />
          </Fact>
        ) : null}
        {hasText(bounty.release_tx_hash) ? (
          <Fact term="Payout transaction">
            <Value
              value={bounty.release_tx_hash}
              display={abbreviateHash(bounty.release_tx_hash)}
              label="payout transaction"
            />
          </Fact>
        ) : null}
      </dl>

      <div className="evidence-actions">
        {hasText(bounty.release_tx_hash) ? (
          <ExternalAction href={stellarExpertSearchUrl(bounty.release_tx_hash)}>
            View payout on StellarExpert
          </ExternalAction>
        ) : null}
        {hasText(onChain.contract_id) ? (
          <ExternalAction href={stellarExpertContractUrl(onChain.contract_id)}>
            View contract on StellarExpert
          </ExternalAction>
        ) : null}
      </div>
    </div>
  )
}

interface Consistency {
  label: string
  matches: boolean
  task: string
  contract: string
}

/**
 * Igualdad simple entre la task y el contrato. Solo transparencia: no cambia
 * estados ni decide nada sobre el payout.
 */
function ConsistencyChecks({
  bounty,
  onChain,
  criteriaMatches,
}: {
  bounty: Bounty
  onChain: OnChainBounty
  criteriaMatches: boolean
}) {
  const address = (value: string | null) =>
    value === null ? 'Not recorded' : abbreviateAddress(value)

  const rows: Consistency[] = [
    {
      label: 'Amount',
      matches: onChain.amount_stroops === bounty.amount_stroops,
      task: `${formatXlm(bounty.amount_stroops)} XLM`,
      contract: `${formatXlm(onChain.amount_stroops)} XLM`,
    },
    {
      label: 'Client',
      matches: onChain.client_wallet === bounty.client_wallet,
      task: address(bounty.client_wallet),
      contract: address(onChain.client_wallet),
    },
  ]

  if (bounty.developer_wallet !== null) {
    rows.push({
      label: 'Developer',
      matches: onChain.developer_wallet === bounty.developer_wallet,
      task: address(bounty.developer_wallet),
      contract: onChain.developer_wallet === null ? 'Not assigned' : address(onChain.developer_wallet),
    })
  }

  rows.push(
    {
      label: 'Criteria',
      matches: criteriaMatches,
      task: bounty.criteria_hash === null ? 'Not recorded' : abbreviateHash(bounty.criteria_hash),
      contract: abbreviateHash(onChain.criteria_hash),
    },
    {
      label: 'Deadline',
      matches: onChain.deadline_unix === bounty.deadline_unix,
      task: formatUnixSeconds(bounty.deadline_unix),
      contract: formatUnixSeconds(onChain.deadline_unix),
    },
  )

  return (
    <div className="evidence-block">
      <h3 className="evidence-block__title">Task ↔ contract</h3>
      <p className="evidence-muted">
        Field-by-field comparison between this MergePay task and the contract.
      </p>
      <ul className="consistency-list">
        {rows.map((row) => (
          <ConsistencyRow key={row.label} row={row} />
        ))}
      </ul>
    </div>
  )
}

function ConsistencyRow({ row }: { row: Consistency }) {
  const Icon: LucideIcon = row.matches ? CheckCircle2 : XCircle

  return (
    <li className={`consistency-row consistency-row--${row.matches ? 'match' : 'mismatch'}`}>
      <Icon size={15} aria-hidden="true" />
      <div className="consistency-row__body">
        <span>{row.label}</span>
        {!row.matches ? (
          <span className="consistency-row__detail">
            Task {row.task} · Contract {row.contract}
          </span>
        ) : null}
      </div>
      <span className="consistency-row__state">{row.matches ? 'Matches' : 'Mismatch'}</span>
    </li>
  )
}
