import { t, useI18n } from '../i18n'
export function AppLoader() {
  useI18n()
  return <div className="app-loader" role="status"><div className="pyramid" aria-hidden="true"><div className="pyramid__spin">{[1, 2, 3, 4].map(side => <span key={side} className={`pyramid__side pyramid__side--${side}`} />)}<span className="pyramid__shadow" /></div></div><strong>MergePay</strong><p>{t("Restoring your session...")}</p></div>
}
