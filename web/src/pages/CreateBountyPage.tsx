import { useState } from 'react'
import { AlertTriangle, Plus, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { ApiError, createBounty } from '../api/client'
import { useAuth } from '../auth/authContext'
import { AuthPrompt } from '../components/AuthPrompt'
import { PageHeader } from '../components/PageHeader'
import { localDateTimeToUnixSeconds } from '../utils/format'
import { xlmToStroops } from '../utils/xlm'
import './CreateBountyPage.css'

type FieldName =
  | 'title'
  | 'description'
  | 'repository'
  | 'baseBranch'
  | 'reward'
  | 'deadline'

type FieldErrors = Partial<Record<FieldName, string>>

interface ValidForm {
  title: string
  description: string
  repoOwner: string
  repoName: string
  baseBranch: string
  amountStroops: number
  deadlineUnix: number
  criteria: string[]
}

export function CreateBountyPage() {
  const navigate = useNavigate()

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [repository, setRepository] = useState('')
  const [baseBranch, setBaseBranch] = useState('main')
  const [reward, setReward] = useState('')
  const [deadline, setDeadline] = useState('')
  const [criteria, setCriteria] = useState([''])

  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [criteriaErrors, setCriteriaErrors] = useState<string[]>([])
  const [submitError, setSubmitError] = useState('')
  const auth = useAuth()
  const authenticated = auth.status === 'authenticated'

  const [submitting, setSubmitting] = useState(false)

  function updateCriterion(index: number, value: string) {
    setCriteria((current) =>
      current.map((entry, position) => (position === index ? value : entry)),
    )
  }

  function addCriterion() {
    setCriteria((current) => [...current, ''])
    setCriteriaErrors((current) => [...current, ''])
  }

  function removeCriterion(index: number) {
    setCriteria((current) => current.filter((_, position) => position !== index))
    setCriteriaErrors((current) =>
      current.filter((_, position) => position !== index),
    )
  }

  /** Valida todo y devuelve el formulario listo para enviar, o null. */
  function validate(): ValidForm | null {
    const errors: FieldErrors = {}

    const trimmedTitle = title.trim()
    const trimmedDescription = description.trim()
    const trimmedRepository = repository.trim()
    const trimmedBranch = baseBranch.trim()

    if (trimmedTitle === '') {
      errors.title = 'Enter a task title.'
    }

    if (trimmedDescription === '') {
      errors.description = 'Describe what needs to be built.'
    }

    const segments = trimmedRepository.split('/')
    const validRepository =
      segments.length === 2 && segments.every((part) => part.trim() !== '')

    if (!validRepository) {
      errors.repository = 'Use the owner/repository format.'
    }

    if (trimmedBranch === '') {
      errors.baseBranch = 'Enter the base branch.'
    }

    const parsedReward = xlmToStroops(reward)

    if (!parsedReward.ok) {
      errors.reward = parsedReward.error
    }

    const deadlineUnix =
      deadline === '' ? null : localDateTimeToUnixSeconds(deadline)

    if (deadlineUnix === null) {
      errors.deadline = 'Choose a deadline.'
    } else if (deadlineUnix <= Math.floor(Date.now() / 1000)) {
      errors.deadline = 'The deadline must be in the future.'
    }

    const trimmedCriteria = criteria.map((entry) => entry.trim())
    const nextCriteriaErrors = trimmedCriteria.map((entry) =>
      entry === '' ? 'Describe this criterion.' : '',
    )

    setFieldErrors(errors)
    setCriteriaErrors(nextCriteriaErrors)

    const hasErrors =
      Object.keys(errors).length > 0 ||
      nextCriteriaErrors.some((message) => message !== '')

    if (hasErrors || !parsedReward.ok || deadlineUnix === null) {
      return null
    }

    return {
      title: trimmedTitle,
      description: trimmedDescription,
      repoOwner: segments[0].trim(),
      repoName: segments[1].trim(),
      baseBranch: trimmedBranch,
      amountStroops: parsedReward.stroops,
      deadlineUnix,
      criteria: trimmedCriteria,
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    // Sin sesion no se envia nada: el client de la task sale de ella.
    if (submitting || !authenticated) {
      return
    }

    const form = validate()

    if (form === null) {
      setSubmitError('')
      return
    }

    setSubmitting(true)
    setSubmitError('')

    try {
      const created = await createBounty({
        title: form.title,
        description: form.description,
        repo_owner: form.repoOwner,
        repo_name: form.repoName,
        base_branch: form.baseBranch,
        amount_stroops: form.amountStroops,
        deadline_unix: form.deadlineUnix,
        criteria: form.criteria.map((entry) => ({
          description: entry,
          required: true,
        })),
      })

      // Sin pantalla de exito: el detalle real es la confirmacion.
      navigate(`/bounties/${created.id}`)
    } catch (error: unknown) {
      setSubmitError(
        error instanceof ApiError
          ? error.message
          : 'Unable to reach the MergePay API. Check your connection and try again.',
      )
      setSubmitting(false)
    }
  }

  return (
    <div className="shell">
      <PageHeader
        eyebrow="New task"
        title="Create a development task"
        description="Define what needs to be built, how it will be verified, and the reward secured for the developer."
      />

      <form className="task-form" onSubmit={handleSubmit} noValidate>
        <section className="panel task-form__section">
          <h2 className="panel__title">Task</h2>
          <p className="panel__hint">What the developer is expected to deliver.</p>

          <div className="field">
            <label htmlFor="task-title">Task title</label>
            <input
              id="task-title"
              type="text"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              aria-invalid={fieldErrors.title ? true : undefined}
              aria-describedby={fieldErrors.title ? 'task-title-error' : undefined}
              placeholder="Fix the OAuth redirect loop on session refresh"
            />
            {fieldErrors.title ? (
              <p className="field__error" id="task-title-error">
                {fieldErrors.title}
              </p>
            ) : null}
          </div>

          <div className="field">
            <label htmlFor="task-description">Description</label>
            <textarea
              id="task-description"
              rows={5}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              aria-invalid={fieldErrors.description ? true : undefined}
              aria-describedby={
                fieldErrors.description ? 'task-description-error' : undefined
              }
              placeholder="Explain the problem, the expected behaviour and anything the developer needs to know."
            />
            {fieldErrors.description ? (
              <p className="field__error" id="task-description-error">
                {fieldErrors.description}
              </p>
            ) : null}
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
                type="text"
                value={repository}
                onChange={(event) => setRepository(event.target.value)}
                aria-invalid={fieldErrors.repository ? true : undefined}
                aria-describedby="task-repo-hint"
                placeholder="owner/repository"
              />
              <p className="field__hint" id="task-repo-hint">
                Use owner/repository
              </p>
              {fieldErrors.repository ? (
                <p className="field__error">{fieldErrors.repository}</p>
              ) : null}
            </div>

            <div className="field">
              <label htmlFor="task-branch">Base branch</label>
              <input
                id="task-branch"
                type="text"
                value={baseBranch}
                onChange={(event) => setBaseBranch(event.target.value)}
                aria-invalid={fieldErrors.baseBranch ? true : undefined}
                placeholder="main"
              />
              {fieldErrors.baseBranch ? (
                <p className="field__error">{fieldErrors.baseBranch}</p>
              ) : null}
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
                type="text"
                inputMode="decimal"
                value={reward}
                onChange={(event) => setReward(event.target.value)}
                aria-invalid={fieldErrors.reward ? true : undefined}
                aria-describedby="task-reward-hint"
                placeholder="250"
              />
              <p className="field__hint" id="task-reward-hint">
                Up to 7 decimal places
              </p>
              {fieldErrors.reward ? (
                <p className="field__error">{fieldErrors.reward}</p>
              ) : null}
            </div>

            <div className="field">
              <label htmlFor="task-deadline">Deadline</label>
              <input
                id="task-deadline"
                type="datetime-local"
                value={deadline}
                onChange={(event) => setDeadline(event.target.value)}
                aria-invalid={fieldErrors.deadline ? true : undefined}
              />
              {fieldErrors.deadline ? (
                <p className="field__error">{fieldErrors.deadline}</p>
              ) : null}
            </div>
          </div>
        </section>

        <fieldset className="panel task-form__section task-form__criteria">
          <legend className="panel__title">Acceptance criteria</legend>
          <p className="panel__hint">
            Each criterion is checked automatically before the reward is
            released.
          </p>

          {criteria.map((entry, index) => (
            <div className="field" key={index}>
              <label htmlFor={`task-criterion-${index}`}>
                Criterion {index + 1}
              </label>
              <div className="criterion-row">
                <input
                  id={`task-criterion-${index}`}
                  type="text"
                  value={entry}
                  onChange={(event) => updateCriterion(index, event.target.value)}
                  aria-invalid={criteriaErrors[index] ? true : undefined}
                  placeholder="The regression suite passes on the head commit"
                />
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => removeCriterion(index)}
                  disabled={criteria.length === 1}
                  aria-label={`Remove criterion ${index + 1}`}
                >
                  <Trash2 size={16} aria-hidden="true" />
                </button>
              </div>
              {criteriaErrors[index] ? (
                <p className="field__error">{criteriaErrors[index]}</p>
              ) : null}
            </div>
          ))}

          <button
            type="button"
            className="button button--secondary task-form__add"
            onClick={addCriterion}
          >
            <Plus size={16} aria-hidden="true" />
            Add criterion
          </button>
        </fieldset>

        {submitError ? (
          <p className="task-form__submit-error" role="alert">
            <AlertTriangle size={16} aria-hidden="true" />
            {submitError}
          </p>
        ) : null}

        {authenticated ? null : (
          <AuthPrompt
            message="Sign in with your Stellar wallet to create and own this task."
            hint="Your answers stay in the form while you sign in."
          />
        )}

        <div className="task-form__footer">
          <button
            type="submit"
            className="button button--primary"
            disabled={submitting || !authenticated}
          >
            {submitting ? 'Creating task...' : 'Create task'}
          </button>
          <p className="task-form__note">
            The task is created as a draft, owned by your wallet. Securing the
            reward on Stellar comes next.
          </p>
        </div>
      </form>
    </div>
  )
}
