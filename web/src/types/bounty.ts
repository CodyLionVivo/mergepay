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
