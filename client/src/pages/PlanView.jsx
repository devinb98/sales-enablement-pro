import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import Spinner from '../components/Spinner'

const DOC_LABELS = {
  meeting_note: 'Meeting note',
  company_info: 'Company info',
  rfp: 'RFP',
}

/**
 * The citation chips. This is the component that makes the AI trustworthy: a
 * number the rep can click to read the exact sentence in their own document
 * that produced the recommendation.
 */
function Sources({ sourceIds, citations, onFocus }) {
  if (!sourceIds?.length) {
    return <span className="chip chip--none" title="No supporting source">uncited</span>
  }

  return (
    <span className="chips">
      {sourceIds.map((n) => {
        const citation = citations.find((c) => c.source_number === n)
        if (!citation) return null
        return (
          <button
            key={n}
            className="chip"
            onClick={() => onFocus(n)}
            title={`${citation.filename} — click to read the passage`}
          >
            {n}
          </button>
        )
      })}
    </span>
  )
}

export default function PlanView() {
  const { id } = useParams()
  const navigate = useNavigate()

  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(true)
  const [openCitation, setOpenCitation] = useState(null)
  const [newItem, setNewItem] = useState('')
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    api
      .getPlan(id)
      .then(setPlan)
      .catch((err) => {
        if (err.status === 404) navigate('/deals', { replace: true })
      })
      .finally(() => setLoading(false))
  }, [id, navigate])

  function focusCitation(sourceNumber) {
    setOpenCitation(sourceNumber)
    document
      .getElementById(`citation-${sourceNumber}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  async function toggleItem(item) {
    const next = item.status === 'done' ? 'open' : 'done'
    // Optimistic: a checkbox that lags behind the click feels broken.
    setPlan({
      ...plan,
      items: plan.items.map((i) => (i.id === item.id ? { ...i, status: next } : i)),
    })
    try {
      await api.updateItem(item.id, { status: next })
    } catch {
      // Put it back if the server disagreed.
      setPlan({
        ...plan,
        items: plan.items.map((i) => (i.id === item.id ? { ...i, status: item.status } : i)),
      })
    }
  }

  async function deleteItem(item) {
    const previous = plan.items
    setPlan({ ...plan, items: plan.items.filter((i) => i.id !== item.id) })
    try {
      await api.deleteItem(item.id)
    } catch {
      setPlan({ ...plan, items: previous })
    }
  }

  async function addItem(event) {
    event.preventDefault()
    if (!newItem.trim()) return
    setAdding(true)
    try {
      const created = await api.createItem(plan.id, { title: newItem.trim() })
      setPlan({ ...plan, items: [...plan.items, created] })
      setNewItem('')
    } finally {
      setAdding(false)
    }
  }

  if (loading) return <Spinner label="Loading plan…" />
  if (!plan) return null

  const done = plan.items.filter((i) => i.status === 'done').length

  return (
    <div className="page">
      <Link to={`/deals/${plan.deal_id}`} className="backlink">
        ← Back to deal
      </Link>

      <div className="page__head">
        <div>
          <h1>Action plan</h1>
          <p className="muted">
            Generated {new Date(plan.generated_at).toLocaleString()} · {plan.model_used}
          </p>
        </div>
      </div>

      <section className="card">
        <h2>Where this deal stands</h2>
        <p className="summary">{plan.summary}</p>
      </section>

      <section className="card">
        <h2>Next steps</h2>
        <ol className="steps">
          {plan.next_steps.map((step, index) => (
            <li key={index}>
              <span>{step.step}</span>
              <Sources
                sourceIds={step.source_ids}
                citations={plan.citations}
                onFocus={focusCitation}
              />
            </li>
          ))}
        </ol>
      </section>

      <section className="card">
        <div className="card__head">
          <h2>Action items</h2>
          <span className="muted">
            {done}/{plan.items.length} done
          </span>
        </div>

        <ul className="items">
          {plan.items.map((item) => (
            <li key={item.id} className={item.status === 'done' ? 'is-done' : ''}>
              <input
                type="checkbox"
                checked={item.status === 'done'}
                onChange={() => toggleItem(item)}
                aria-label={`Mark "${item.title}" as ${
                  item.status === 'done' ? 'open' : 'done'
                }`}
              />

              <div className="items__body">
                <div className="items__title">
                  <strong>{item.title}</strong>
                  <span className={`badge badge--${item.priority}`}>{item.priority}</span>
                  {item.is_user_created && <span className="badge badge--yours">yours</span>}
                </div>

                {item.detail && <p className="muted">{item.detail}</p>}

                {!item.is_user_created && (
                  <Sources
                    sourceIds={item.source_ids}
                    citations={plan.citations}
                    onFocus={focusCitation}
                  />
                )}
              </div>

              <button
                className="btn btn--icon"
                onClick={() => deleteItem(item)}
                aria-label={`Delete ${item.title}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>

        <form className="items__add" onSubmit={addItem}>
          <input
            value={newItem}
            onChange={(e) => setNewItem(e.target.value)}
            placeholder="Add your own action item…"
          />
          <button className="btn btn--secondary" disabled={adding || !newItem.trim()}>
            Add
          </button>
        </form>
      </section>

      <section className="card">
        <h2>Sources</h2>
        <p className="muted">
          Every numbered claim above comes from one of these passages in your own
          documents. Click a number to jump here.
        </p>

        <ul className="citations">
          {plan.citations.map((citation) => (
            <li
              key={citation.id}
              id={`citation-${citation.source_number}`}
              className={openCitation === citation.source_number ? 'is-focused' : ''}
            >
              <div className="citations__head">
                <span className="chip chip--static">{citation.source_number}</span>
                <div>
                  <strong>{citation.filename}</strong>
                  <small className="muted">
                    {DOC_LABELS[citation.doc_type] ?? citation.doc_type} · relevance{' '}
                    {citation.relevance_score?.toFixed(2)}
                  </small>
                </div>
              </div>
              <blockquote>{citation.quote}</blockquote>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
