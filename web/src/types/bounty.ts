export interface Criterion {
  id: number
  bounty_id: number
  description: string
  required: boolean
  position: number
}

export interface Bounty {
  id: number
  title: string
  description: string

  repo_owner: string
  repo_name: string
  base_branch: string
  base_sha: string | null

  client_wallet: string | null
  developer_wallet: string | null
  developer_github: string | null

  amount_stroops: number
  deadline_unix: number

  criteria_hash: string | null

  github_issue_number: number | null
  pull_request_number: number | null

  create_tx_hash: string | null
  release_tx_hash: string | null

  status: string

  created_at: string
  updated_at: string

  criteria: Criterion[]
}

export interface CriterionCreate {
  description: string
  required: boolean
}

export interface BountyCreate {
  title: string
  description: string
  repo_owner: string
  repo_name: string
  base_branch: string
  amount_stroops: number
  deadline_unix: number
  criteria: CriterionCreate[]
}

export interface Submission {
  id: number
  bounty_id: number
  pull_request_url: string
  pull_request_number: number
  author: string | null
  head_ref: string
  head_sha: string
  created_at: string
  updated_at: string
}

/** Un required check tal como lo evaluo el backend. */
export interface RequiredCheckResult {
  name: string
  /** Status del check run en GitHub, o "missing" si no existe. */
  status: string
  conclusion: string | null
  passed: boolean
}

export type VerificationStatus = 'PASS' | 'FAIL' | 'PENDING'

export interface PullRequestVerificationResult {
  status: VerificationStatus
  eligible_for_payout: boolean

  repository_valid: boolean
  base_branch_valid: boolean
  base_sha_valid: boolean
  developer_valid: boolean
  pr_open: boolean
  pr_not_draft: boolean
  protected_files_valid: boolean

  protected_files_modified: string[]

  checks: RequiredCheckResult[]

  reasons: string[]

  head_sha: string
}

export interface VerificationRecord {
  id: number
  bounty_id: number
  submission_id: number
  created_at: string
  result: PullRequestVerificationResult
}
