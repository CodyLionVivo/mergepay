import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'

export function NotFoundPage() {
  return (
    <div className="shell">
      <PageHeader
        eyebrow="404"
        title="This page does not exist"
        description="The task you are looking for may have been removed, or the link is incorrect."
        actions={
          <Link className="button button--primary" to="/">
            Back to tasks
          </Link>
        }
      />
    </div>
  )
}
