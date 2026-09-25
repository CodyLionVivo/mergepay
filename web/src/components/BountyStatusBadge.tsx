import { t, useI18n } from '../i18n'
import {
  AlertCircle,
  CheckCircle2,
  CircleDot,
  CircleSlash,
  Clock,
  FileText,
} from 'lucide-react'
import './BountyStatusBadge.css'

type Tone = 'neutral' | 'info' | 'warning' | 'danger' | 'success' | 'muted'

interface StatusStyle {
  label: string
  tone: Tone
}

const STATUSES: Record<string, StatusStyle> = {
  DRAFT: { label: 'Draft', tone: 'neutral' },
  OPEN_FUNDED: { label: 'Funded', tone: 'info' },
  ASSIGNED: { label: 'Assigned', tone: 'info' },
  SUBMITTED: { label: 'Submitted', tone: 'info' },
  VERIFYING: { label: 'Verifying', tone: 'warning' },
  NEEDS_CHANGES: { label: 'Needs changes', tone: 'danger' },
  ELIGIBLE: { label: 'Eligible · unpaid', tone: 'warning' },
  PAID: { label: 'Paid', tone: 'success' },
  CANCELLED_REFUNDED: { label: 'Cancelled', tone: 'muted' },
  EXPIRED_REFUNDED: { label: 'Refunded', tone: 'muted' },
}

const TONE_ICONS = {
  neutral: FileText,
  info: CircleDot,
  warning: Clock,
  danger: AlertCircle,
  success: CheckCircle2,
  muted: CircleSlash,
}

interface BountyStatusBadgeProps {
  status: string
}

/**
 * Un status que no conocemos se muestra tal cual en vez de romper la UI: el
 * backend puede añadir estados antes que el frontend.
 */
export function BountyStatusBadge({ status }: BountyStatusBadgeProps) {
  useI18n()
  const style = STATUSES[status] ?? { label: status, tone: 'neutral' as const }
  const Icon = TONE_ICONS[style.tone]

  return (
    <span className={`status-badge status-badge--${style.tone}`}>
      <Icon size={12} aria-hidden="true" />
      {t(style.label)}
    </span>
  )
}
