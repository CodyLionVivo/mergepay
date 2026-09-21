/**
 * Validaciones de GitHub en el navegador, alineadas con las del backend.
 *
 * Solo comprueban el formato. Que la cuenta exista, o que pertenezca a quien la
 * declara, no se verifica en ningun sitio de MergePay.
 */

/** Letras, numeros y guion, de 1 a 39 caracteres, igual que el backend. */
const USERNAME_PATTERN = /^[A-Za-z0-9-]{1,39}$/

/** https://github.com/{owner}/{repo}/pull/{n}, sin query ni fragmento. */
const PULL_REQUEST_URL_PATTERN =
  /^https:\/\/github\.com\/[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+\/pull\/[1-9][0-9]*$/

export function isValidGithubUsername(value: string): boolean {
  return USERNAME_PATTERN.test(value.trim())
}

export function isCanonicalPullRequestUrl(value: string): boolean {
  return PULL_REQUEST_URL_PATTERN.test(value.trim())
}
