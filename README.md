# MergePay

**MergePay is a marketplace for verifiable software bounties: the reward is locked in a
Soroban escrow before the work starts, and it is released automatically once the agreed
GitHub checks pass.**

> **Stellar Testnet only. No real funds are used.** Every amount, wallet and transaction in
> this project lives on Stellar Testnet.

---

## Stellar Odyssey Perú

**Track: AI Agents & Automated Workflows — Automated Workflows focus.**

MergePay does not implement AI agents yet. What it implements today is the automated
workflow underneath them:

- **GitHub provides the external software-delivery data** — pull request metadata, changed
  files and check runs from GitHub Actions.
- **MergePay verifies that workflow deterministically** — the same inputs always produce
  the same PASS / FAIL / PENDING result.
- **Stellar performs the settlement automatically** — a PASS result triggers
  `release_bounty` on the escrow contract, with no manual approval step from the client.

There is no AI in the payout path. Nothing in this repository decides, diagnoses or
generates anything with a model.

---

## Submission links

> ⚠️ **Do not submit while `TODO_BEFORE_SUBMISSION` values remain unresolved.**

| Item | Value |
| --- | --- |
| Repository | <https://github.com/CodyLionVivo/mergepay> |
| Web app | `TODO_BEFORE_SUBMISSION` |
| Stellar Testnet escrow contract | [`CDACJNKK23RZ2HZ27IXM2LDYFZIV5LU4UKY2I2XASY7ZM633E3OTRGKR`](https://stellar.expert/explorer/testnet/contract/CDACJNKK23RZ2HZ27IXM2LDYFZIV5LU4UKY2I2XASY7ZM633E3OTRGKR) |
| Funding transaction (`create_bounty`) | [`1da21801cb5e1704a6b138f1f7f7872fb7c41d76989848d1c1c92a864db61f07`](https://stellar.expert/explorer/testnet/tx/1da21801cb5e1704a6b138f1f7f7872fb7c41d76989848d1c1c92a864db61f07) |
| Successful payout transaction (`release_bounty`) | [`3986f8bfe20cbfe46d63ff62ae0c2301ffdde3b3940444661017fcea856d2f84`](https://stellar.expert/explorer/testnet/tx/3986f8bfe20cbfe46d63ff62ae0c2301ffdde3b3940444661017fcea856d2f84) |
| Demo video | `TODO_BEFORE_SUBMISSION` |
| Pitch video | `TODO_BEFORE_SUBMISSION` |

Both transactions belong to the same bounty and were confirmed on Stellar Testnet: the
funding call escrowed the reward, and the payout call released it to the developer after
the GitHub checks passed.

---

## Problem

A small team can outsource a well-defined software task, but everything around the money
is coordinated by hand:

- the scope and the acceptance criteria are agreed in chat and can drift afterwards;
- the developer has no assurance that the reward exists before starting;
- the client has no assurance that the delivery meets what was agreed;
- someone has to review, decide and then remember to pay;
- the final payment is a manual step at the end of a manual process.

MergePay targets the part of that problem that can be checked mechanically: whether a
specific pull request satisfies a specific, previously agreed set of automated checks — and
what happens to the money when it does.

---

## Solution

```text
task specification → funded Stellar escrow → developer assignment →
GitHub pull request → deterministic verification → automatic Stellar settlement
```

The acceptance criteria are hashed and committed on-chain **before** the escrow is funded,
so the terms cannot be rewritten afterwards. When the verifier returns PASS, MergePay
anchors an evidence hash and calls `release_bounty`.

**After the agreed checks pass, the client does not perform any additional manual approval.**
There is no "approve payment" or "release funds" button anywhere in the product: the client
and the developer can both trigger a verification run, but neither of them decides the
outcome.

---

## End-to-end flow

```text
  CLIENT                     MERGEPAY                 GITHUB              STELLAR TESTNET
    │                           │                        │                       │
    │ create task (criteria)    │                        │                       │
    ├──────────────────────────►│ criteria_hash          │                       │
    │                           │                        │                       │
    │ fund escrow (Freighter)   │                        │                       │
    ├───────────────────────────┼────────────────────────┼──► create_bounty ─────┤
    │                           │◄── verify escrow on-chain ────────────────────┤
    │                           │    status: OPEN_FUNDED │                       │
    │                           │                        │                       │
 DEVELOPER                      │                        │                       │
    │ accept task (Freighter)   │                        │                       │
    ├───────────────────────────┼────────────────────────┼──► accept_bounty ─────┤
    │ + SEP-53 ownership proof  │                        │                       │
    │                           │    status: ASSIGNED    │                       │
    │                           │                        │                       │
    │ open pull request         │                        │                       │
    ├───────────────────────────┼───────────────────────►│                       │
    │ register PR               │                        │ Actions run:          │
    ├──────────────────────────►│                        │  build                │
    │                           │                        │  regression-tests     │
    │ run verification          │                        │  acceptance-tests     │
    ├──────────────────────────►│─── read PR + checks ──►│                       │
    │                           │◄───────────────────────┤                       │
    │                           │ deterministic verdict  │                       │
    │                           │                        │                       │
    │                    PASS ──┤ evidence_hash          │                       │
    │                           ├────────────────────────┼──► release_bounty ────┤
    │                           │                        │    reward → developer │
    │                           │    status: PAID        │                       │
```

FAIL leaves the task in `NEEDS_CHANGES` (push to the same pull request and check again) and
PENDING leaves it in `VERIFYING` (checks still running). Neither state moves any funds.

---

## Architecture

```text
┌──────────────────────────────┐        ┌───────────────────────────────┐
│  Browser (Vercel)            │        │  Backend (Railway)            │
│  React + Vite + TypeScript   │  HTTPS │  FastAPI                      │
│  Freighter (wallet)          │◄──────►│  Bearer sessions (SEP-53)     │
│  Stellar SDK (build tx)      │        │  verifier + evidence hashing  │
└───────┬──────────────────────┘        └────┬──────────────┬───────────┘
        │ sign + submit                      │              │
        │                                    │ REST         │ Soroban RPC
        ▼                                    ▼              ▼
┌──────────────────────────────┐   ┌──────────────┐  ┌─────────────────────┐
│  Stellar Testnet             │   │  GitHub API  │  │  PostgreSQL (prod)  │
│  Soroban escrow contract     │   │  PRs, files, │  │  SQLite (local)     │
│  create/accept/release       │   │  check runs  │  │  tasks, sessions    │
└──────────────────────────────┘   └──────────────┘  └─────────────────────┘
```

The browser signs everything that costs money: the client signs `create_bounty`, the
developer signs `accept_bounty`. The backend never holds a user's private key. The only key
the backend holds is the **verifier** key, which can call exactly one contract function,
`release_bounty`, and only with an evidence hash it computed itself.

---

## Main components

| Component | Path | Responsibility |
| --- | --- | --- |
| Soroban escrow | `contracts/escrow/` | Holds the reward and enforces the bounty lifecycle |
| FastAPI app | `api/app/` | HTTP API, sessions, task lifecycle |
| GitHub client | `api/app/github_client.py` | Reads pull requests, changed files and check runs |
| GitHub verifier | `api/app/github_verifier.py` | Deterministic PASS / FAIL / PENDING verdict |
| Verification service | `api/app/verification_service.py` | Persists verifications and triggers the payout |
| Stellar client | `api/app/stellar_client.py` | Reads the contract and signs `release_bounty` |
| Evidence service | `api/app/evidence_service.py` | Read-only on-chain view of a bounty |
| Hashing | `api/app/hashing.py` | `criteria_hash` and `evidence_hash` |
| Auth | `api/app/auth_service.py`, `api/app/auth_dependencies.py` | SEP-53 challenges, sessions, per-task authorization |
| React frontend | `web/src/` | Marketplace, task lifecycle, on-chain proof panel |
| Freighter / escrow bridge | `web/src/stellar/` | Builds and submits the user-signed transactions |

---

## Stellar integration

The escrow contract (`contracts/escrow/src/lib.rs`) is constructed with a **verifier
address** and a **token contract address**, and exposes:

| Function | Who signs | What it does |
| --- | --- | --- |
| `create_bounty(id, client, amount, criteria_hash, deadline)` | client | Transfers the reward into the contract and stores the bounty as `Open` |
| `accept_bounty(id, developer)` | developer | Binds the developer address, `Open → Assigned` |
| `release_bounty(id, evidence_hash)` | verifier | Transfers the reward to the developer, stores the evidence hash, `Assigned → Paid` |
| `cancel_open_bounty(id)` | client | Refunds an `Open` bounty before the deadline, `Open → Cancelled` |
| `refund_expired(id)` | client | Refunds after the deadline, `→ Refunded` |
| `get_bounty(id)` | — | Read-only bounty state |

On-chain bounty state: `client`, `developer`, `amount`, `criteria_hash`, `evidence_hash`,
`deadline`, `status` (`Open`, `Assigned`, `Paid`, `Cancelled`, `Refunded`).

**`criteria_hash`** is a 32-byte digest of the acceptance criteria, computed by MergePay
before funding. It is committed when the escrow is created, so the criteria that were agreed
cannot be swapped later without the mismatch being visible.

**`evidence_hash`** is a 32-byte digest of the verified delivery — task, repository, base
commit, developer, pull request and verification result. It is written by `release_bounty`,
so every paid bounty carries a commitment to the exact evidence that justified the payment.

**The verifier address** is the only account that can call `release_bounty`
(`verifier.require_auth()` inside the contract). It cannot create bounties, reassign them or
change the amount. `release_bounty` also refuses to pay after the deadline and refuses any
bounty that is not `Assigned`.

---

## Deterministic GitHub verification

`api/app/github_verifier.py` takes a pull request inspection plus its check runs and returns
a verdict. It performs no network calls of its own and keeps no state, so **the same inputs
always produce the same result.**

Structural rules, all evaluated on every run:

| Rule | Checks that |
| --- | --- |
| Repository | the PR lives in the task's `owner/name` |
| Base branch | the PR targets the agreed branch |
| Base commit | the PR is based on the commit recorded when the task was funded |
| Developer | the PR author is the assigned developer's GitHub account |
| Pull request is open | the PR has not been closed |
| Pull request is not draft | the PR is ready for review |
| Protected files | the PR does not touch the files that define the verification itself |

Protected paths (exact): `.github/workflows/mergepay-ci.yml`, `requirements.txt`.
Protected prefixes: `tests/regression/`, `tests/acceptance/`. Renames are detected in both
directions, so a protected file cannot be moved out of the way.

Required GitHub checks, which must exist for the head commit of the pull request:

- `build`
- `regression-tests`
- `acceptance-tests`

Verdict:

- **PASS** — every structural rule holds and all three required checks completed
  successfully. The bounty becomes eligible and the payout runs immediately.
- **FAIL** — at least one structural rule is broken or a required check finished without
  success. The task returns to `NEEDS_CHANGES`.
- **PENDING** — a required check is missing or still running. The task waits in `VERIFYING`.

This verdict is the only thing that determines payout eligibility. A duplicated required
check name is rejected rather than guessed.

---

## Authentication, authorization and privacy

**Authentication.** There are no passwords and no email. The identity is a Stellar account,
and the proof is a signature:

1. the browser asks for a challenge for its address;
2. the backend returns a message that contains the wallet, a single-use challenge id and its
   expiry;
3. Freighter signs that exact message with **SEP-53** (a signed message, not a transaction:
   no fees, no ledger entry);
4. the backend verifies the signature against the address and issues a session token.

Challenges are single-use and expire in 5 minutes; sessions expire in 8 hours. **Only the
SHA-256 of the session token is stored** — the token itself exists in the response and in the
browser's `sessionStorage`, never in the database.

**Authorization is per task, not global.** There is no role column: the same wallet can be
the client of one task and the developer of another. Permissions are derived from the task
itself (`client_wallet`, `developer_wallet`) and are re-checked against the contract state
for the operations that move money.

**Privacy.** MergePay serves task data according to its lifecycle:

| Status | Who can read it |
| --- | --- |
| `DRAFT` | the client only |
| `OPEN_FUNDED` | anyone — this is the public marketplace listing |
| `ASSIGNED` and later | the client and the assigned developer only |

A task that exists but is not visible answers exactly like one that does not exist
(`404 Bounty not found`), so a third party cannot confirm a private task even with its id.

**This application-level privacy does not make Stellar private.** The escrow, the amounts,
the wallets and every transaction remain publicly auditable on Stellar Testnet, by design.

---

## On-chain proof

Every funded task has an **On-chain proof** panel that reads the contract live through the
backend and shows:

- contract id and contract state (`Open` / `Assigned` / `Paid` / `Cancelled` / `Refunded`);
- escrow amount and deadline;
- client wallet and developer wallet;
- the criteria commitment, compared field by field against what MergePay stores;
- the evidence commitment, once `release_bounty` has anchored it;
- the funding transaction and the payout transaction;
- external links to StellarExpert and Stellar Lab, so the same data can be checked outside
  MergePay.

The panel distinguishes two different things on purpose:

- **MergePay recorded references** — transaction ids stored by MergePay (funding, payout).
  They remain visible even if the Stellar RPC is unreachable, clearly labelled as stored
  references.
- **Live on-chain state** — what the contract returns right now. If it cannot be read, the
  panel says so instead of asserting a contract state it did not verify.

---

## Technology

| Layer | Stack |
| --- | --- |
| Smart contract | Rust, `soroban-sdk` 27, Stellar CLI |
| Backend | Python 3.13, FastAPI 0.141, SQLAlchemy 2.0, `stellar-sdk` 16.1, httpx, psycopg 3 |
| Database | PostgreSQL (production), SQLite (local) |
| Frontend | React 19, TypeScript, Vite 8, `@stellar/stellar-sdk` 16.3, `@stellar/freighter-api` 6, EN/ES interface |
| Deployment | Vercel (frontend), Railway (backend + PostgreSQL) |
| Network | Stellar Testnet |

---

## Run locally

### Smart contract

```sh
rustup target add wasm32v1-none
stellar contract build
cargo test
```

Rust 1.84+ is required for the `wasm32v1-none` target.

### Backend

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

`.env.example` has no secrets. To run the full payout flow you need to fill in
`STELLAR_CONTRACT_ID` and `STELLAR_VERIFIER_SECRET` with your own deployed contract and its
verifier account — never commit them. Without them the app still runs; only the Stellar
calls are disabled.

### Frontend

```powershell
cd web
npm install
Copy-Item .env.example .env.local
npm run dev
```

Leave `VITE_API_BASE_URL=/api` for local development: Vite proxies `/api` to the backend on
`127.0.0.1:8000`. Set `VITE_STELLAR_CONTRACT_ID` to the same contract the backend uses.

**Freighter must be installed and switched to Testnet.** The app refuses to build a
transaction on any other network, and it never asks for a secret key or a seed phrase.

---

## Tests

```sh
cargo test                 # escrow contract, host-side
stellar contract build     # compiles the contract to WASM
```

```sh
cd api && python -m pytest        # backend
```

```sh
cd web && npm run build && npm run lint   # frontend typecheck, build and lint
```

Last verified run in this repository (2026-09-25): `cargo test` → 16 passed;
`python -m pytest` → 655 passed; `npm run build` and `npm run lint` → exit 0.

---

## What was built during Stellar Odyssey Perú

The repository was created during the event window: the first commit is
`8719014 chore: initialize MergePay monorepo`, dated **2026-09-19**, and the GitHub
repository was created the same day. Every commit in `main` is from 2026-09-19 onwards, so
there is no pre-event code in this project.

Built during the window:

- the Soroban escrow contract and its full lifecycle, with host tests;
- the FastAPI backend: tasks, submissions, verifications, sessions;
- the GitHub reader and the deterministic verifier;
- `criteria_hash` and `evidence_hash`;
- the automatic payout after a PASS result;
- the React frontend: marketplace, task creation, funding, assignment, PR submission and
  verification;
- Freighter integration for client funding and developer assignment;
- the on-chain proof panel;
- wallet authentication with SEP-53 and per-task authorization;
- task privacy after assignment;
- PostgreSQL support and deployment configuration for Vercel and Railway.

---

## Current MVP limitations

- **Stellar Testnet only. No real funds, no Mainnet deployment.**
- No AI agents are implemented. Nothing is decided, diagnosed or generated by a model, and
  no AI takes part in the payout path.
- No dispute resolution: if a delivery fails the agreed checks, the task simply stays open
  for another attempt until the deadline.
- No partial payouts: `release_bounty` transfers the full amount or nothing.
- No platform fee and no revenue logic.
- No organization or team dashboard, and no "my tasks" view — private tasks are reached by
  their link.
- `cancel_open_bounty` and `refund_expired` exist and are tested in the contract, but are
  not exposed yet through the API or the interface.
- The contract does not manage storage TTL and does not emit events.
- The GitHub account declared by a developer is bound to their wallet by a SEP-53 signature,
  but MergePay does not prove ownership of that GitHub account; the verifier only requires
  that the pull request author matches it.
- Database schema is created with `create_all()`; there are no migrations yet.

---

## Repository layout

```text
mergepay/
├── contracts/escrow/     Soroban escrow contract (Rust)
├── api/                  FastAPI backend
│   ├── app/              application code
│   ├── tests/            backend test suite
│   └── .env.example      backend configuration template
├── web/                  React + Vite frontend
│   ├── src/              application code
│   ├── .env.example      frontend configuration template
│   └── vercel.json       SPA routing for Vercel
├── docs/                 submission and project documents
├── Cargo.toml            Rust workspace
├── README.md
└── LICENSE
```

---

## License

[MIT](LICENSE) — Copyright (c) 2026 MergePay contributors.
