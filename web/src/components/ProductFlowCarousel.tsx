import { t, useI18n } from '../i18n'
import { FileText, GitBranch, ScanLine, ShieldCheck, ArrowUpRight } from 'lucide-react'

const concepts = [
  { Icon: FileText, title: 'Define the task', detail: 'Clear requirements. A shared definition of done.' },
  { Icon: ShieldCheck, title: 'Secure the reward', detail: 'Fund the escrow before developers start.' },
  { Icon: GitBranch, title: 'Build through GitHub', detail: 'Your repository. Your workflow. One pull request.' },
  { Icon: ScanLine, title: 'Verify automatically', detail: 'Required GitHub checks establish eligibility.' },
  { Icon: ArrowUpRight, title: 'Release payment', detail: 'Eligible work triggers a Stellar payout attempt.' },
]
export function ProductFlowCarousel() {
  useI18n()
  return <section className="product-flow" aria-labelledby="flow-title"><div className="section-heading"><div><p className="hero__eyebrow">{t("From issue to impact")}</p><h2 id="flow-title">{t("A better way to ship together.")}</h2></div><p>{t("Code verified. Payment confirmed. Two distinct milestones.")}</p></div><ol className="product-flow__track" tabIndex={0} aria-label={t("How MergePay works")}>{concepts.map(({ Icon, title, detail }, index) => <li key={t(title)}><div className="product-flow__top"><Icon size={21} aria-hidden="true" /><span>0{index + 1}</span></div><h3>{title}</h3><p>{t(detail)}</p></li>)}</ol></section>
}
