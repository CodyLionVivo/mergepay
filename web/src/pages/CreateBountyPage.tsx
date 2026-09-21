import { PageHeader } from '../components/PageHeader'
import './CreateBountyPage.css'

const CRITERIA_SLOTS = [1, 2, 3]

export function CreateBountyPage() {
  return (
    <div className="shell">
      <PageHeader
        eyebrow="New task"
        title="Create a development task"
        description="Define what needs to be built, how it will be verified, and the reward secured for the developer."
      />

      {/* Maqueta: los campos aun no estan conectados a POST /bounties. */}
      <form className="task-form" onSubmit={(event) => event.preventDefault()}>
        <section className="panel task-form__section">
          <h2 className="panel__title">Task</h2>
          <p className="panel__hint">What the developer is expected to deliver.</p>

          <div className="field">
            <label htmlFor="task-title">Task title</label>
            <input
              id="task-title"
              name="title"
              type="text"
              placeholder="Fix the OAuth redirect loop on session refresh"
            />
          </div>

          <div className="field">
            <label htmlFor="task-description">Description</label>
            <textarea
              id="task-description"
              name="description"
              rows={5}
              placeholder="Explain the problem, the expected behaviour and anything the developer needs to know."
            />
          </div>
        </section>

        <section className="panel task-form__section">
          <h2 className="panel__title">Repository</h2>
          <p className="panel__hint">Where the pull request will be opened.</p>

          <div className="field-row">
            <div className="field">
              <label htmlFor="task-repo">GitHub repository</label>
              <input
                id="task-repo"
                name="repository"
                type="text"
                placeholder="owner/repo"
              />
            </div>

            <div className="field">
              <label htmlFor="task-branch">Base branch</label>
              <input
                id="task-branch"
                name="baseBranch"
                type="text"
                placeholder="main"
              />
            </div>
          </div>
        </section>

        <section className="panel task-form__section">
          <h2 className="panel__title">Reward</h2>
          <p className="panel__hint">
            Secured upfront and released automatically once every criterion
            passes.
          </p>

          <div className="field-row">
            <div className="field">
              <label htmlFor="task-reward">Reward (XLM)</label>
              <input
                id="task-reward"
                name="reward"
                type="number"
                min="0"
                step="0.0000001"
                placeholder="250"
              />
            </div>

            <div className="field">
              <label htmlFor="task-deadline">Deadline</label>
              <input id="task-deadline" name="deadline" type="date" />
            </div>
          </div>
        </section>

        <fieldset className="panel task-form__section task-form__criteria">
          <legend className="panel__title">Acceptance criteria</legend>
          <p className="panel__hint">
            Each criterion is checked automatically before the reward is
            released.
          </p>

          {CRITERIA_SLOTS.map((slot) => (
            <div className="field" key={slot}>
              <label htmlFor={`task-criterion-${slot}`}>Criterion {slot}</label>
              <input
                id={`task-criterion-${slot}`}
                name={`criterion-${slot}`}
                type="text"
                placeholder="The regression suite passes on the head commit"
              />
            </div>
          ))}
        </fieldset>

        <div className="task-form__footer">
          <button type="button" className="button button--primary">
            Continue
          </button>
          <p className="task-form__note">
            Not connected yet. Submitting tasks arrives with the marketplace
            API.
          </p>
        </div>
      </form>
    </div>
  )
}
