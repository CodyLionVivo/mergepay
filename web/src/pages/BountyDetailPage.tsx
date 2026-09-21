import { Info } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import './BountyDetailPage.css'

const SECTIONS = [
  {
    id: 'overview',
    title: 'Overview',
    hint: 'Description and repository the task belongs to.',
    lines: ['long', 'long', 'medium'],
  },
  {
    id: 'reward',
    title: 'Reward',
    hint: 'Amount secured and its settlement state.',
    lines: ['short', 'medium'],
  },
  {
    id: 'criteria',
    title: 'Acceptance criteria',
    hint: 'Every criterion agreed before the work started.',
    lines: ['long', 'medium', 'long'],
  },
  {
    id: 'verification',
    title: 'GitHub verification',
    hint: 'Pull request checks that gate the reward.',
    lines: ['medium', 'long'],
  },
  {
    id: 'activity',
    title: 'Activity',
    hint: 'Submissions, verifications and settlement events.',
    lines: ['short', 'long', 'medium'],
  },
] as const

export function BountyDetailPage() {
  const { id } = useParams<{ id: string }>()

  return (
    <div className="shell">
      <PageHeader
        eyebrow="Task detail"
        title={`Task #${id}`}
        description="Everything agreed for this task, from the acceptance criteria to the on-chain settlement."
      />

      <p className="detail-notice" role="note">
        <Info size={16} aria-hidden="true" />
        Task data will load here.
      </p>

      <div className="detail-sections">
        {SECTIONS.map((section) => (
          <section
            className="panel"
            key={section.id}
            aria-labelledby={`${section.id}-title`}
          >
            <h2 className="panel__title" id={`${section.id}-title`}>
              {section.title}
            </h2>
            <p className="panel__hint">{section.hint}</p>

            <div className="detail-skeleton" aria-hidden="true">
              {section.lines.map((line, index) => (
                <div
                  className={`skeleton skeleton--${line}`}
                  key={`${section.id}-${index}`}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
