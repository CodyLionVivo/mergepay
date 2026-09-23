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
      ? `Copied the ${label}.`
      : state === 'failed'
        ? `Could not copy the ${label}. Select and copy it manually.`
        : ''

  return (
    <span className="copy-control">
      <button
        type="button"
        className={`copy-button copy-button--${state}`}
        onClick={() => void copy()}
        title={`Copy the full ${label}`}
      >
        <Icon size={13} aria-hidden="true" />
        {TEXT[state]}
        <span className="visually-hidden"> {label}</span>
      </button>
      <span className="visually-hidden" aria-live="polite">
        {announcement}
      </span>
    </span>
  )
}
