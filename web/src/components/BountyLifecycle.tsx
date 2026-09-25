import { Check } from 'lucide-react'

const STAGES = ['Funded', 'Assigned', 'Submitted', 'Verified', 'Paid']
const COMPLETED: Record<string, number> = {
  DRAFT: 0, OPEN_FUNDED: 1, ASSIGNED: 2, SUBMITTED: 3,
  VERIFYING: 3, NEEDS_CHANGES: 3, ELIGIBLE: 4, PAID: 5,
}

/** Only backend states establish completed milestones; eligible never means paid. */
export function BountyLifecycle({ status }: { status: string }) {
  const completed = COMPLETED[status]
  if (completed === undefined) return null
  return (
    <ol className="bounty-lifecycle" aria-label="Bounty progress">
      {STAGES.map((label, index) => (
        <li key={label} className={index < completed ? 'is-complete' : ''}
          aria-current={index === completed ? 'step' : undefined}>
          <span className="bounty-lifecycle__marker">
            {index < completed ? <Check size={13} aria-hidden="true" /> : index + 1}
          </span>
          <span>{label}<span className="visually-hidden">{index < completed ? ', complete' : ', not complete'}</span></span>
        </li>
      ))}
    </ol>
  )
}
