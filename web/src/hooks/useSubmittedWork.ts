import { useEffect, useState } from 'react'
import { findLatestVerification, getSubmission, requestErrorMessage } from '../api/client'
import type { Submission, VerificationRecord } from '../types/bounty'

/** Un dato que se carga aparte del bounty y falla sin tumbar la pagina. */
export type Loadable<T> =
  | { status: 'loading' }
  | { status: 'ready'; value: T }
  | { status: 'error'; message: string }

const LOADING = { status: 'loading' } as const

interface Records {
  bountyId: number
  token: number
  submission: Loadable<Submission>
  /** null: aun no se ha ejecutado ninguna verificacion. */
  verification: Loadable<VerificationRecord | null>
}

function toLoadable<T>(outcome: PromiseSettledResult<T>): Loadable<T> {
  return outcome.status === 'fulfilled'
    ? { status: 'ready', value: outcome.value }
    : { status: 'error', message: requestErrorMessage(outcome.reason) }
}

/**
 * Submission y ultima verificacion de un bounty con PR registrado.
 *
 * Todo sale del backend, asi que un refresh reconstruye el estado completo sin
 * depender de nada guardado en esta visita. Como en la pagina, "loading" se
 * deriva en render comparando lo guardado con el bounty y el intento actuales.
 */
export function useSubmittedWork(bountyId: number | null, enabled: boolean) {
  const [records, setRecords] = useState<Records | null>(null)
  const [token, setToken] = useState(0)

  const settled =
    enabled &&
    records !== null &&
    records.bountyId === bountyId &&
    records.token === token

  useEffect(() => {
    if (!enabled || bountyId === null) {
      return
    }

    const controller = new AbortController()

    void Promise.allSettled([
      getSubmission(bountyId, controller.signal),
      findLatestVerification(bountyId, controller.signal),
    ]).then(([submission, verification]) => {
      if (controller.signal.aborted) {
        return
      }

      setRecords({
        bountyId,
        token,
        submission: toLoadable(submission),
        verification: toLoadable(verification),
      })
    })

    return () => controller.abort()
  }, [bountyId, enabled, token])

  function patch(update: Partial<Pick<Records, 'submission' | 'verification'>>) {
    setRecords((current) => (current === null ? current : { ...current, ...update }))
  }

  return {
    submission: settled ? records.submission : LOADING,
    verification: settled ? records.verification : LOADING,
    reload: () => setToken((current) => current + 1),
    setSubmission: (value: Submission) => patch({ submission: { status: 'ready', value } }),
    setVerification: (value: VerificationRecord) =>
      patch({ verification: { status: 'ready', value } }),
  }
}
