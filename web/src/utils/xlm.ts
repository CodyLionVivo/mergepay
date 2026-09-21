/**
 * Conversion entre XLM y stroops.
 *
 * La conversion se hace sobre los digitos de la cadena, no con aritmetica de
 * coma flotante: `parseFloat("0.0000001") * 10_000_000` no da exactamente 1 y
 * aqui cada stroop cuenta.
 */

export const STROOPS_PER_XLM = 10_000_000

const DECIMAL_PLACES = 7

/** Decimal positivo sin signo ni exponente. */
const AMOUNT_PATTERN = /^\d+(?:\.\d+)?$/

const GROUPED = new Intl.NumberFormat('en-US')

export type XlmParseResult =
  | { ok: true; stroops: number }
  | { ok: false; error: string }

export function xlmToStroops(input: string): XlmParseResult {
  const trimmed = input.trim()

  if (trimmed === '') {
    return { ok: false, error: 'Enter a reward amount.' }
  }

  if (!AMOUNT_PATTERN.test(trimmed)) {
    return {
      ok: false,
      error: 'Enter a positive amount in XLM, for example 10.5.',
    }
  }

  const [whole, fraction = ''] = trimmed.split('.')

  if (fraction.length > DECIMAL_PLACES) {
    return { ok: false, error: 'XLM supports at most 7 decimal places.' }
  }

  // Los digitos se concatenan y la fraccion se rellena hasta 7 posiciones, de
  // modo que el resultado es exacto.
  const stroops = Number(`${whole}${fraction.padEnd(DECIMAL_PLACES, '0')}`)

  if (!Number.isSafeInteger(stroops)) {
    return { ok: false, error: 'That reward is too large.' }
  }

  if (stroops <= 0) {
    return { ok: false, error: 'The reward must be greater than zero.' }
  }

  return { ok: true, stroops }
}

/** Stroops a XLM legible, sin decimales de relleno. */
export function formatXlm(amountStroops: number): string {
  const negative = amountStroops < 0
  const absolute = Math.abs(amountStroops)

  const whole = Math.floor(absolute / STROOPS_PER_XLM)
  const fraction = absolute % STROOPS_PER_XLM

  const fractionText =
    fraction === 0
      ? ''
      : `.${String(fraction).padStart(DECIMAL_PLACES, '0').replace(/0+$/, '')}`

  return `${negative ? '-' : ''}${GROUPED.format(whole)}${fractionText}`
}
