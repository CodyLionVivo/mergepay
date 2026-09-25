import { t, useI18n } from '../i18n'
import { useId } from 'react'

/** Mount only after a confirmed funding or payout response, never for PASS/ELIGIBLE. */
export function TransactionSuccess({ kind }: { kind: 'funding' | 'payout' }) {
  useI18n()
  const gradient = useId()
  return <div className="transaction-success" role="status">
    <svg viewBox="0 0 160 140" aria-hidden="true"><defs><linearGradient id={gradient}><stop stopColor="#8b5cf6" /><stop offset="1" stopColor="#22d3ee" /></linearGradient></defs><path className="transaction-success__orbit" d="M80 8 137 40V102L80 133 23 102V40Z" fill="none" stroke={`url(#${gradient})`} /><path d="M80 25 122 49V93L80 117 38 93V49Z" fill="#8b5cf61a" stroke={`url(#${gradient})`} /><path className="transaction-success__check" d="m58 70 15 15 30-32" fill="none" stroke="#67e8f9" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" /></svg>
    <div><h3>{kind === 'funding' ? t("Reward secured") : t("Reward released")}</h3><p>{kind === 'funding' ? t("Funding is confirmed. The bounty is ready for developers.") : t("Payment has been confirmed on Stellar.")}</p></div>
  </div>
}
