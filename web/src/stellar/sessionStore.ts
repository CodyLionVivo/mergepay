/**
 * Acceso a sessionStorage que nunca lanza.
 *
 * El navegador puede bloquear el storage (modo privado estricto, cookies
 * desactivadas). En ese caso las lecturas devuelven null y las escrituras no
 * hacen nada: la app sigue funcionando en memoria, solo que sin sobrevivir a
 * un refresh.
 */

export function readSessionItem(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeSessionItem(key: string, value: string): void {
  try {
    window.sessionStorage.setItem(key, value)
  } catch {
    // Storage no disponible: el dato queda solo en memoria.
    return
  }
}

export function removeSessionItem(key: string): void {
  try {
    window.sessionStorage.removeItem(key)
  } catch {
    // Storage no disponible: no habia nada guardado que borrar.
    return
  }
}
