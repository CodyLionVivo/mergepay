import { t, useI18n } from '../i18n'
import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, Copy } from 'lucide-react'
import './CopyButton.css'

type CopyState = 'idle' | 'copied' | 'failed'

const RESET_AFTER_MS = 2000

const TEXT: Record<CopyState, string> = {
  idle: 'Copy',
  copied: 'Copied',
  failed: 'Copy failed',
}

const ICONS = { idle: Copy, copied: Check, failed: AlertTriangle }

interface CopyButtonProps {
  /** El valor completo, aunque en pantalla se muestre abreviado. */
  value: string
  /** Que se copia, para lectores de pantalla: "contract ID", "payout transaction"... */
  label: string
}

/** Copia solo al pulsar. Si la Clipboard API falla, lo dice y no rompe nada. */
export function CopyButton({ value, label }: CopyButtonProps) {
  useI18n()
  const [state, setState] = useState<CopyState>('idle')
  const resetTimer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(resetTimer.current), [])

  async function copy() {
    let next: CopyState = 'copied'

    try {
      // Sin Clipboard API (contexto inseguro, permiso denegado) esto lanza.
      await navigator.clipboard.writeText(value)
    } catch {
      next = 'failed'
    }

    setState(next)
    window.clearTimeout(resetTimer.current)
    resetTimer.current = window.setTimeout(() => setState('idle'), RESET_AFTER_MS)
  }

  const Icon = ICONS[state]

  const announcement =
    state === 'copied'
      ? t('Copied {label}.', { label: t(label) })
      : state === 'failed'
        ? t('Could not copy {label}. Select and copy it manually.', { label: t(label) })
        : ''

  return (
    <span className="copy-control">
      <button
        type="button"
        className={`copy-button copy-button--${state}`}
        onClick={() => void copy()}
        title={t("Copy {label}", { label: t(label) })}
      >
        <Icon size={13} aria-hidden="true" />
        {t(TEXT[state])}
        <span className="visually-hidden"> {t(label)}</span>
      </button>
      <span className="visually-hidden" aria-live="polite">
        {announcement}
      </span>
    </span>
  )
}
