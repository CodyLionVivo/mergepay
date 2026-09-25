import { t, useI18n } from '../i18n'
import {
  FileText,
  GitBranch,
  ScanLine,
  ShieldCheck,
  ArrowUpRight,
} from 'lucide-react'

import './ProductFlowCarousel.css'

const concepts = [
  {
    Icon: FileText,
    title: 'Define the task',
    detail: 'Clear requirements. A shared definition of done.',
  },
  {
    Icon: ShieldCheck,
    title: 'Secure the reward',
    detail: 'Fund the escrow before developers start.',
  },
  {
    Icon: GitBranch,
    title: 'Build through GitHub',
    detail: 'Your repository. Your workflow. One pull request.',
  },
  {
    Icon: ScanLine,
    title: 'Verify automatically',
    detail: 'Required GitHub checks establish eligibility.',
  },
  {
    Icon: ArrowUpRight,
    title: 'Release payment',
    detail: 'Eligible work triggers a Stellar payout attempt.',
  },
]

function FlowGroup({
  ariaHidden = false,
}: {
  ariaHidden?: boolean
}) {
  return (
    <ol
      className="product-flow__group"
      aria-hidden={ariaHidden || undefined}
    >
      {concepts.map(({ Icon, title, detail }, index) => (
        <li
          className="product-flow__card"
          key={`${title}-${index}`}
        >
          <div className="product-flow__top">
            <Icon
              className="product-flow__icon"
              size={21}
              aria-hidden="true"
            />

            <span className="product-flow__number">
              {String(index + 1).padStart(2, '0')}
            </span>
          </div>

          <h3 className="product-flow__title">
            {t(title)}
          </h3>

          <p className="product-flow__description">
            {t(detail)}
          </p>
        </li>
      ))}
    </ol>
  )
}

export function ProductFlowCarousel() {
  useI18n()

  return (
    <section
      className="product-flow"
      aria-labelledby="flow-title"
    >
      <div className="product-flow__heading">
        <div>
          <p className="hero__eyebrow">
            {t('From issue to impact')}
          </p>

          <h2 id="flow-title">
            {t('A better way to ship together.')}
          </h2>
        </div>

        <p className="product-flow__summary">
          {t(
            'Code verified. Payment confirmed. Two distinct milestones.',
          )}
        </p>
      </div>

      <div
        className="product-flow__viewport"
        aria-label={t('How MergePay works')}
      >
        <div className="product-flow__marquee">
          <FlowGroup />
          <FlowGroup ariaHidden />
        </div>
      </div>
    </section>
  )
}