# Submission readiness — Stellar Odyssey Perú

Status of the MergePay submission. Everything marked `TODO_BEFORE_SUBMISSION` still has to
be resolved by a human before the entry is sent.

Last reviewed: 2026-09-25.

## Checklist

- [x] README updated — rewritten from the code in this repository
- [x] LICENSE at the repository root — MIT
- [x] Repository is public — `CodyLionVivo/mergepay`, created 2026-09-19
- [ ] Team collaborators verified — **manual check required**, see below
- [ ] Vercel production URL — `TODO_BEFORE_SUBMISSION`
- [x] Stellar contract evidence — `CDACJNKK23RZ2HZ27IXM2LDYFZIV5LU4UKY2I2XASY7ZM633E3OTRGKR`
- [x] Successful payout transaction — `3986f8bfe20cbfe46d63ff62ae0c2301ffdde3b3940444661017fcea856d2f84`
- [x] Contract evidence also in README — "Submission links" section
- [x] GitHub URL in README — <https://github.com/CodyLionVivo/mergepay>
- [ ] Demo video URL — `TODO_BEFORE_SUBMISSION`
- [ ] Pitch video URL — `TODO_BEFORE_SUBMISSION`
- [ ] Submission form completed — do this last, once the items above are closed

## Verified on-chain evidence

Both transactions were confirmed on Stellar Testnet and belong to the same bounty (id 9).
They were read from Horizon and their envelopes decoded, so the contract and the invoked
function are not assumed:

| Item | Value |
| --- | --- |
| Contract | `CDACJNKK23RZ2HZ27IXM2LDYFZIV5LU4UKY2I2XASY7ZM633E3OTRGKR` |
| Funding | `1da21801cb5e1704a6b138f1f7f7872fb7c41d76989848d1c1c92a864db61f07` — `create_bounty`, successful, 2026-09-23T05:07:02Z, ledger 4823287 |
| Payout | `3986f8bfe20cbfe46d63ff62ae0c2301ffdde3b3940444661017fcea856d2f84` — `release_bounty`, successful, 2026-09-23T05:15:02Z, ledger 4823383 |

## Manual checks required

- **Verify every team member is an active GitHub collaborator.** The repository currently
  lists `CodyLionVivo` (admin), `VarBus`, `ZtanQ` and `iconicmiau` (write). There are no
  pending invitations. Confirm that this list matches the team registered for the event —
  this document does not assume who the team is.
- **Deploy and record the production URLs.** The repository has no Vercel or Railway domain
  in it. After deploying, set `CORS_ALLOWED_ORIGINS` on Railway to the Vercel domain and
  `VITE_API_BASE_URL` on Vercel to the Railway domain, then put the web app URL in the
  README.
- **Record the videos** and add both links to the README and to this checklist.

## Last verified project checks

Run in this repository on 2026-09-25:

| Check | Result |
| --- | --- |
| `cargo test` | 16 passed |
| `python -m pytest` (api) | 655 passed |
| `npm run build` (web) | exit 0 |
| `npm run lint` (web) | exit 0 |

## Known repository inconsistencies

Not blockers for the submission, but worth a look:

- `/.env.example` at the repository root is tracked and empty. The real templates are
  `api/.env.example` and `web/.env.example`.
- `/package-lock.json` at the repository root is tracked, although the only Node project
  lives in `web/`.
