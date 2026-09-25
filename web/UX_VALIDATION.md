# MergePay UI refactor validation

- Real Vite production build and oxlint scripts pass. There is no npm test script.
- Isolated headless Chrome exercised the live development app at 320, 375, 430,
  768, 1024, and 1440 pixels. Marketplace, all four wizard steps, and Spanish
  reward/review screens had no horizontal document overflow.
- Checked mobile navigation, validation, adding acceptance criteria, returning to
  completed steps, keyboard activation of the escrow flip, language persistence
  after reload, and form retention across language changes. No runtime exceptions.
- Reduced-motion mode disabled CSS animations. Screenshots of mobile and desktop
  marketplace/reward screens were inspected.
- The real API was unavailable during this pass. Offline/retry presentation was
  exercised without introducing mock marketplace data. Populated marketplace,
  authenticated task details, Freighter signatures, funding, and settlement still
  need an integrated pass with the running backend and a testnet wallet.
- Vite reports a large-bundle warning (main bundle above
  500 kB). No warning threshold was increased or suppressed.

## State boundaries

- The initial loader waits for passive wallet inspection and stored-session
  validation, without an artificial delay or a signature request.
- Wallet connection and session authentication remain separate UI states.
- Reward configuration previews always say not funded.
- Funding success requires the funding endpoint response, a funding hash, and
  the backend OPEN_FUNDED state. No local button click establishes funding.
- Payout success requires backend PAID and a recorded release transaction.
  PASS and ELIGIBLE never render the payout success animation.
- API calls, token handling, signature payloads, transaction recovery, GitHub
  checks, access rules, backend code, and Soroban contracts are preserved.
