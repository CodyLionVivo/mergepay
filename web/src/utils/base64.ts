/** Una firma ed25519 ocupa exactamente 64 bytes. */
const SIGNATURE_BYTES = 64

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''

  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }

  return btoa(binary)
}

/**
 * Normaliza una firma a base64 estandar, con relleno, o devuelve null.
 *
 * Freighter puede entregarla como string base64 o como Buffer/Uint8Array segun
 * la version. Se decodifica y se vuelve a codificar para que al backend llegue
 * siempre la misma forma canonica, y se exige que sean 64 bytes: un hex u otro
 * formato inesperado se rechaza aqui en vez de acabar como un 403.
 */
export function normalizeSignatureBase64(value: string | Uint8Array): string | null {
  let bytes: Uint8Array

  if (typeof value === 'string') {
    let binary: string

    try {
      binary = atob(value.trim())
    } catch {
      return null
    }

    bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0))
  } else {
    bytes = value
  }

  if (bytes.length !== SIGNATURE_BYTES) {
    return null
  }

  return bytesToBase64(bytes)
}
