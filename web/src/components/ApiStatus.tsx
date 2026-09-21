import { useEffect, useState } from 'react'
import { AlertTriangle, CircleDashed, ShieldCheck } from 'lucide-react'
import { getHealth } from '../api/client'
import './ApiStatus.css'

type Status = 'checking' | 'healthy' | 'error'

const LABELS: Record<Status, string> = {
  checking: 'Checking API',
  healthy: 'API Connected',
  error: 'API Offline',
}

const ICONS = {
  checking: CircleDashed,
  healthy: ShieldCheck,
  error: AlertTriangle,
}

/**
 * Comprueba el backend una sola vez al montar. Sin polling, y un fallo aqui
 * nunca tumba la aplicacion: solo cambia esta etiqueta.
 */
export function ApiStatus() {
  const [status, setStatus] = useState<Status>('checking')

  useEffect(() => {
    const controller = new AbortController()

    getHealth(controller.signal)
      .then((health) => {
        setStatus(health.status === 'healthy' ? 'healthy' : 'error')
      })
      .catch(() => {
        // El abort del cleanup no es un fallo del backend.
        if (!controller.signal.aborted) {
          setStatus('error')
        }
      })

    return () => controller.abort()
  }, [])

  const Icon = ICONS[status]

  return (
    <p className={`api-status api-status--${status}`} role="status">
      <Icon className="api-status__icon" size={14} aria-hidden="true" />
      {LABELS[status]}
    </p>
  )
}
