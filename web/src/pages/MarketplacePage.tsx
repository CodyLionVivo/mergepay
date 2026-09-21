import { ArrowRight, CircleDot, GitPullRequest, ListChecks, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import './MarketplacePage.css'

/**
 * Contenido de maquetacion. NO viene del backend: existe solo para fijar el
 * layout de las cards y se borra cuando se conecte GET /bounties.
 */
const DEMO_TASKS = [
  {
    id: 1,
    title: 'Fix the OAuth redirect loop on session refresh',
    repo: 'acme/dashboard',
    reward: 250,
    criteria: 3,
    status: 'open',
    statusLabel: 'Open',
  },
  {
    id: 2,
    title: 'Add cursor pagination to the public bounties endpoint',
    repo: 'acme/api',
    reward: 400,
    criteria: 4,
    status: 'review',
    statusLabel: 'In review',
  },
  {
    id: 3,
    title: 'Migrate the CI matrix to Node 22',
    repo: 'acme/infra',
    reward: 150,
    criteria: 2,
    status: 'verified',
    statusLabel: 'Verified',
  },
] as const

const STATUS_ICONS = {
  open: CircleDot,
  review: GitPullRequest,
  verified: ShieldCheck,
}

export function MarketplacePage() {
  return (
    <div className="shell">
      <section className="hero">
        <p className="hero__eyebrow">Automated rewards for verified code</p>
        <h1 className="hero__title">Build. Verify. Get paid.</h1>
        <p className="hero__lede">
          Development tasks with rewards secured upfront and released when the
          agreed checks pass.
        </p>

        <div className="hero__actions">
          <a className="button button--primary" href="#open-tasks">
            Explore tasks
            <ArrowRight size={16} aria-hidden="true" />
          </a>
          <Link className="button button--secondary" to="/bounties/new">
            Create a task
          </Link>
        </div>
      </section>

      <section className="tasks" id="open-tasks" aria-labelledby="open-tasks-title">
        <div className="tasks__head">
          <h2 className="tasks__title" id="open-tasks-title">
            Open tasks
          </h2>
          <p className="tasks__note">
            Example layout. Live tasks appear once the marketplace endpoint is
            connected.
          </p>
        </div>

        <ul className="tasks__grid">
          {DEMO_TASKS.map((task) => {
            const StatusIcon = STATUS_ICONS[task.status]

            return (
              <li key={task.id}>
                <Link to={`/bounties/${task.id}`} className="task-card card">
                  <span className={`badge badge--${task.status}`}>
                    <StatusIcon size={12} aria-hidden="true" />
                    {task.statusLabel}
                  </span>

                  <h3 className="task-card__title">{task.title}</h3>

                  <p className="task-card__repo">
                    <code>{task.repo}</code>
                  </p>

                  <dl className="task-card__meta">
                    <div className="task-card__metric">
                      <dt>Reward</dt>
                      <dd className="task-card__reward">{task.reward} XLM</dd>
                    </div>
                    <div className="task-card__metric">
                      <dt>Criteria</dt>
                      <dd>
                        <ListChecks size={14} aria-hidden="true" />
                        {task.criteria}
                      </dd>
                    </div>
                  </dl>
                </Link>
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}
