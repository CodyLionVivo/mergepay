# MergePay

MergePay connects verifiable software delivery with programmable rewards on Stellar.

A client funds a bounty on-chain before any work starts. A developer claims it. When an
off-chain verifier confirms the work meets the agreed criteria, the contract releases the
locked reward to the developer. The money is escrowed by the contract for the whole
lifecycle — neither side has to trust the other to hold it.

## Status

Early. The Soroban escrow contract is implemented and tested; everything else is a
placeholder.

| Component                | Path         | State                                           |
| ------------------------ | ------------ | ----------------------------------------------- |
| Escrow contract          | `contracts/` | Working — builds to WASM, 16 host tests passing |
| FastAPI backend          | `api/`       | Empty directory                                 |
| React frontend           | `web/`       | Empty directory                                 |
| Architecture & decisions | `docs/`      | Empty directory                                 |

The verifier is currently just an address the contract trusts. The service that inspects a
merged PR and decides whether the criteria were met does not exist yet.

## Requirements

- **Rust 1.84+** with the `wasm32v1-none` target (`rustup target add wasm32v1-none`).
  Rust 1.82 and 1.83 cannot build Soroban contracts.
- **Stellar CLI** (`stellar`) — install with `cargo install --locked stellar-cli`.

Verified on Rust 1.98.1 and Stellar CLI 28.0.0.

## Build and test

From the repo root:

```sh
stellar contract build     # compiles every cdylib member to WASM
cargo test                 # host-side unit tests (not on-chain)
```

The artifact lands at `target/wasm32v1-none/release/escrow.wasm` (~6.7 KB).

Do not substitute `cargo build --target wasm32v1-none` — `stellar contract build` applies
the flags and metadata the network expects.

`contracts/escrow/Makefile` wraps the same commands (`make build`, `make test`, `make fmt`).

## How the escrow works

Three roles, one bounty:

- **Client** — funds the bounty and defines the acceptance criteria.
- **Developer** — claims an open bounty and does the work.
- **Verifier** — a single address fixed at deploy time, the only one that can authorize
  payout. Intended to be the MergePay backend.

The lifecycle is a one-way path. Every terminal state returns the escrowed tokens to
someone — the contract never keeps them:

```text
                create_bounty              accept_bounty            release_bounty
  (no bounty) ──────────────────▶ Open ──────────────────▶ Assigned ──────────────────▶ Paid
              client auth +       │       developer auth   │        verifier auth
              tokens locked       │                        │        tokens → developer
                                  │                        │
            cancel_open_bounty    │                        │
       Cancelled ◀────────────────┤                        │
       tokens → client            │                        │
        (before deadline)         │                        │
                                  │    refund_expired      │
                       Refunded ◀─┴────────────────────────┘
                       tokens → client
                        (after deadline)
```

- `create_bounty` pulls `amount` from the client into the contract. The bounty is not open
  until the transfer succeeds, so an open bounty is always fully funded.
- `accept_bounty` records the developer. First claimer wins — there is no application or
  approval step.
- `release_bounty` transfers the full amount to the assigned developer and stores the
  32-byte `evidence_hash` (the off-chain proof the verifier acted on) on the bounty record.
- `cancel_open_bounty` lets the client walk away *before* the deadline, but only while
  nobody has claimed the work. Once a developer is assigned, the client is committed until
  the deadline passes.
- `refund_expired` releases the tokens back to the client *after* the deadline, from either
  `Open` or `Assigned`. This is what keeps funds from being trapped when the verifier never
  authorizes a payout.

The `criteria_hash` and `evidence_hash` are opaque 32-byte digests. The contract never
interprets them; it only anchors them on-chain so the terms and the proof of delivery
cannot be rewritten after the fact.

The deadline splits the lifecycle cleanly, with no ambiguity at the boundary timestamp
itself. `accept_bounty`, `release_bounty` and `cancel_open_bounty` are valid while
`timestamp <= deadline`; `refund_expired` is valid only once `timestamp > deadline`. At
exactly the deadline the bounty is still live, so the refund path and the delivery path can
never both be open at once.

## Contract API

Deployed with a constructor: `__constructor(verifier: Address, token: Address)`. The
verifier and the payment token are fixed for the life of the contract.

| Function             | Auth                          | Signature                                                                            | Effect                                                                     |
| -------------------- | ----------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| `create_bounty`      | client                        | `(id: u64, client: Address, amount: i128, criteria_hash: BytesN<32>, deadline: u64)` | Transfers `amount` into the contract, stores the bounty as `Open`          |
| `accept_bounty`      | developer                     | `(id: u64, developer: Address)`                                                      | `Open` → `Assigned`                                                        |
| `release_bounty`     | verifier                      | `(id: u64, evidence_hash: BytesN<32>)`                                               | Pays the developer, `Assigned` → `Paid`                                    |
| `cancel_open_bounty` | client (stored on the bounty) | `(id: u64)`                                                                          | Refunds the client, `Open` → `Cancelled`. Rejected past the deadline       |
| `refund_expired`     | client (stored on the bounty) | `(id: u64)`                                                                          | Refunds the client, `Open`/`Assigned` → `Refunded`. Only past the deadline |
| `get_bounty`         | none                          | `(id: u64) -> Bounty`                                                                | Reads the bounty record                                                    |

`amount` is in the token's smallest unit — for XLM, stroops (7 decimals), so 10 XLM is
`100_000_000`. `deadline` is a Unix timestamp in seconds. `id` is chosen by the caller, not
assigned by the contract; `create_bounty` rejects an id that already exists, so ids have to
be coordinated off-chain.

Errors:

| Code | Error                 | Raised when                                                              |
| ---- | --------------------- | ------------------------------------------------------------------------ |
| 1    | `InvalidAmount`       | `amount <= 0`                                                            |
| 2    | `BountyAlreadyExists` | `id` is already taken                                                    |
| 3    | `BountyNotFound`      | no bounty with that `id`                                                 |
| 4    | `InvalidStatus`       | the call does not match the bounty's current state                       |
| 5    | `DeadlinePassed`      | the deadline is in the past (on create: `deadline` is not in the future) |
| 6    | `DeadlineNotReached`  | `refund_expired` was called at or before the deadline                    |

## Deploy to testnet

Create a funded identity, then deploy against the native XLM Stellar Asset Contract:

```sh
stellar keys generate --global deployer --network testnet --fund

stellar contract id asset --asset native --network testnet   # → the XLM SAC address

stellar contract deploy \
  --wasm target/wasm32v1-none/release/escrow.wasm \
  --source-account deployer \
  --network testnet \
  --alias mergepay-escrow \
  -- \
  --verifier <verifier-address> \
  --token <token-contract-address>
```

Then invoke it — for example, funding a 10 XLM bounty:

```sh
stellar contract invoke \
  --id mergepay-escrow \
  --source-account client \
  --network testnet \
  -- create_bounty \
  --id 1 \
  --client <client-address> \
  --amount 100000000 \
  --criteria_hash <64-hex-chars> \
  --deadline 1767225600
```

`stellar contract invoke --id mergepay-escrow -- --help` prints the generated CLI for every
function on the deployed contract.

## Known gaps

The lifecycle is complete — every state has an exit and no path traps funds — but this is
still v1:

- **No dispute handling.** The verifier's decision is final and the verifier address cannot
  be rotated after deploy. A developer who delivers work the verifier never approves gets
  nothing, and the client recovers the full amount at the deadline.
- **No partial payouts.** A bounty pays out entirely or not at all.
- **No storage TTL management.** Nothing calls `extend_ttl`, so persistent bounty entries can
  expire and be archived on a live network.
- **No events.** Nothing is emitted, so indexers have to poll `get_bounty`.
- **No fees.** MergePay takes no cut; the full amount moves between client and developer.

## Repository layout

```text
contracts/escrow/    Soroban escrow contract (#![no_std])
  src/lib.rs         contract implementation
  src/test.rs        host-side unit tests
  Makefile           build/test/fmt shortcuts
api/                 FastAPI backend (not started)
web/                 React frontend (not started)
docs/                architecture and product decisions (not started)
Cargo.toml           workspace root; contract crates inherit soroban-sdk from here
AGENTS.md            build/deploy notes for coding agents
```

Each contract is a workspace member under `contracts/<name>/`. Build or test just one with
`stellar contract build --package <name>` / `cargo test -p <name>`.

## Further reading

- [Soroban smart contracts overview](https://developers.stellar.org/docs/build/smart-contracts/overview)
- [soroban-examples](https://github.com/stellar/soroban-examples)
