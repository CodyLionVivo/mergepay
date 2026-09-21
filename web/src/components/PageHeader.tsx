import type { ReactNode } from 'react'
import './PageHeader.css'

interface PageHeaderProps {
  eyebrow?: string
  title: string
  /** Opcional: el detalle de una task ya lleva su descripcion en Overview. */
  description?: string
  actions?: ReactNode
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        {eyebrow ? <p className="page-header__eyebrow">{eyebrow}</p> : null}
        <h1 className="page-header__title">{title}</h1>
        {description ? (
          <p className="page-header__description">{description}</p>
        ) : null}
      </div>

      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  )
}
