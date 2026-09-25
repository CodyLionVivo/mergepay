import { useRef } from 'react'
import { ArrowLeft, ArrowRight, GitBranch, Clock } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import { BountyStatusBadge } from './BountyStatusBadge'
import type { Bounty } from '../types/bounty'
import { formatUnixSeconds } from '../utils/format'
import { formatXlm } from '../utils/xlm'

function BountyCard({ bounty }: { bounty: Bounty }) {
  const { t } = useI18n()
  const repository = `${bounty.repo_owner}/${bounty.repo_name}`

  return (
    <Link to={`/bounties/${bounty.id}`} className="task-card card">
      <div className="task-card__top">
        <BountyStatusBadge status={bounty.status} />
        <ArrowRight size={17} aria-hidden="true" />
      </div>
      <h3 className="task-card__title">{bounty.title}</h3>
      <p className="task-card__description">{bounty.description}</p>
      <p className="task-card__repo">
        <GitBranch size={14} aria-hidden="true" />
        <span title={repository}>{repository}</span>
      </p>
      <div className="task-card__value">
        <span>{t('Reward')}</span>
        <strong>{formatXlm(bounty.amount_stroops)} <small>XLM</small></strong>
      </div>
      {bounty.deadline_unix ? (
        <p className="task-card__deadline">
          <Clock size={13} aria-hidden="true" />
          {formatUnixSeconds(bounty.deadline_unix)}
        </p>
      ) : null}
    </Link>
  )
}

export function BountyCarousel({ bounties }: { bounties: Bounty[] }) {
  const { t } = useI18n()
  const track = useRef<HTMLUListElement>(null)

  function scroll(direction: number) {
    const element = track.current
    if (!element) return
    element.scrollBy({
      left: direction * element.clientWidth * .85,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
    })
  }

  return (
    <div className="bounty-carousel">
      {bounties.length > 1 ? (
        <div className="carousel-controls">
          <button className="icon-button" type="button" aria-label={t('Previous bounties')} onClick={() => scroll(-1)}>
            <ArrowLeft size={18} aria-hidden="true" />
          </button>
          <button className="icon-button" type="button" aria-label={t('Next bounties')} onClick={() => scroll(1)}>
            <ArrowRight size={18} aria-hidden="true" />
          </button>
        </div>
      ) : null}
      <ul ref={track} className="bounty-track" aria-label={t('Available bounties')} tabIndex={0}>
        {bounties.map(bounty => <li key={bounty.id}><BountyCard bounty={bounty} /></li>)}
      </ul>
    </div>
  )
}
