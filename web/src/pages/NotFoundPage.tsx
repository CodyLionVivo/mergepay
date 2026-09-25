import { t, useI18n } from '../i18n'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'

export function NotFoundPage() {
  useI18n()
  return (
    <div className="shell">
      <PageHeader
        eyebrow={t("404")}
        title={t("This page does not exist")}
        description={t("The task you are looking for may have been removed, or the link is incorrect.")}
        actions={
          <Link className="button button--primary" to="/">{t("Back to tasks")}</Link>
        }
      />
    </div>
  )
}
