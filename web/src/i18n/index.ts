import { useSyncExternalStore } from 'react'
import { en } from './en'
import { es } from './es'

export type Language = 'en' | 'es'
const listeners = new Set<() => void>()
function readLanguage(): Language {
  try { return localStorage.getItem('mergepay.language') === 'es' ? 'es' : 'en' } catch { return 'en' }
}
let language = readLanguage()
document.documentElement.lang = language
export function getLanguage() { return language }
export function setLanguage(next: Language) {
  language = next
  document.documentElement.lang = next
  try { localStorage.setItem('mergepay.language', next) } catch { /* Private browsing can disable storage. */ }
  listeners.forEach(listener => listener())
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
/** English source keys keep copy readable; unknown server diagnostics remain intact. */
export function t(key: string, values?: Record<string, string | number>): string {
  const dictionary: Record<string, string> = language === 'es' ? es : en
  const text = dictionary[key] ?? key
  return values ? text.replace(/\{(\w+)\}/g, (match, name: string) => String(values[name] ?? match)) : text
}
/** Subscribe without remounting components, so forms and transaction state survive. */
export function useI18n() {
  const locale = useSyncExternalStore(subscribe, getLanguage, () => 'en' as const)
  return { language: locale, setLanguage, t }
}
