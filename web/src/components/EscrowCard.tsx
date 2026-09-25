import { t, useI18n } from '../i18n'
import { useId, useState } from 'react'
import { ArrowUpRight, Clock, RotateCw, ShieldCheck } from 'lucide-react'
import { Brand } from './Brand'
import { abbreviateAddress } from '../stellar/walletContext'
import { stellarExpertSearchUrl } from '../stellar/explorer'
import './EscrowCard.css'

interface EscrowCardProps {
  amount: string
  state: 'preview' | 'pending' | 'funded' | 'released' | 'refunded'
  wallet?: string | null
  transaction?: string | null
}
const labels = { preview: 'Not funded', pending: 'Pending funding', funded: 'Funded', released: 'Released', refunded: 'Refunded' }

/** Presentation only: the caller supplies a state established by backend evidence. */
export function EscrowCard({ amount, state, wallet, transaction }: EscrowCardProps) {
  useI18n()
  const [flipped, setFlipped] = useState(false)
  const id = useId()
  const StatusIcon = state === 'funded' || state === 'released' ? ShieldCheck : Clock
  return <section className="escrow" aria-label={t("Reward escrow")}>
    <div className={`escrow__inner${flipped ? ' is-flipped' : ''}`} id={id}>
      <div className="escrow__face" inert={flipped} aria-hidden={flipped}>
        <Brand />
        <div><p className="escrow__eyebrow">{t("Reward · XLM display units")}</p><p className="escrow__amount">{amount || '—'} <small>XLM</small></p></div>
        <div className="escrow__bottom"><span><StatusIcon size={15} aria-hidden="true" />{t(labels[state])}</span>{wallet ? <code title={wallet}>{abbreviateAddress(wallet)}</code> : null}</div>
      </div>
      <div className="escrow__face escrow__face--back" inert={!flipped} aria-hidden={!flipped}>
        <h3>{t("Escrow details")}</h3>
        <dl><div><dt>{t("Network")}</dt><dd>Stellar Testnet</dd></div><div><dt>{t("Funding state")}</dt><dd>{t(labels[state])}</dd></div></dl>
        {transaction ? <a href={stellarExpertSearchUrl(transaction)} target="_blank" rel="noreferrer">{t("View transaction")}<ArrowUpRight size={16} aria-hidden="true" /><span className="visually-hidden">{t("(opens in a new tab)")}</span></a> : <p>{t("Funds are secured only after confirmation on Stellar.")}</p>}
      </div>
    </div>
    <button type="button" className="escrow__toggle" aria-controls={id} aria-pressed={flipped} onClick={() => setFlipped(!flipped)}><RotateCw size={14} aria-hidden="true" />{flipped ? t("Show reward") : t("View escrow details")}</button>
  </section>
}
