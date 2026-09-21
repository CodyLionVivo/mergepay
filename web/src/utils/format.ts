const DATE_TIME = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

/** `deadline_unix` llega en segundos y se muestra en la zona del navegador. */
export function formatUnixSeconds(seconds: number): string {
  return DATE_TIME.format(new Date(seconds * 1000))
}

/** Convierte el valor de un `datetime-local` (hora local) a segundos unix. */
export function localDateTimeToUnixSeconds(value: string): number | null {
  const parsed = new Date(value)

  if (Number.isNaN(parsed.getTime())) {
    return null
  }

  return Math.floor(parsed.getTime() / 1000)
}

/** Hash largo a forma corta, conservando principio y final. */
export function abbreviateHash(value: string): string {
  if (value.length <= 16) {
    return value
  }

  return `${value.slice(0, 8)}…${value.slice(-4)}`
}
