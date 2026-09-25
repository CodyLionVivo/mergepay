import { Globe2 } from 'lucide-react'
import { useI18n } from './index'

export function LanguageSelector() {
  const { language, setLanguage, t } = useI18n()
  return <label className="language-selector"><Globe2 size={15} aria-hidden="true" /><span className="visually-hidden">{t('Language')}</span><select value={language} onChange={event => setLanguage(event.target.value === 'es' ? 'es' : 'en')}><option value="en" lang="en">EN</option><option value="es" lang="es">ES</option></select></label>
}
