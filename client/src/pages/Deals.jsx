import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import Spinner from '../components/Spinner'

const STAGES = ['discovery', 'qualification', 'proposal', 'negotiation', 'closed']

const EMPTY_FORM = { name: '', company: '', stage: 'discovery', value: '', close_date: '' }

export default function Deals() {
  const [deals, setDeals] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [fieldErrors, setFieldErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .listDeals()
      .then(setDeals)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  async function handleCreate(event) {
    event.preventDefault()
    setFieldErrors({})
    setSaving(true)
    try {
      const created = await api.createDeal({
        ...form,
        value: form.value === '' ? null : Number(form.value),
        close_date: form.close_date || null,
      })
      setDeals([created, ...deals])
      setForm(EMPTY_FORM)
      setShowForm(false)
    } catch (err) {
      if (err.errors) setFieldErrors(err.errors)
      else setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(deal) {
    if (!confirm(`Delete "${deal.name}"? Its documents and plans go with it.`)) return
    try {
      await api.deleteDeal(deal.id)
      setDeals(deals.filter((d) => d.id !== deal.id))
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) return <Spinner label="Loading your deals…" />

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Your deals</h1>
          <p className="muted">
            {deals.length === 0
              ? 'No deals yet.'
              : `${deals.length} deal${deals.length === 1 ? '' : 's'} in your pipeline.`}
          </p>
        </div>
        <button className="btn btn--primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : 'New deal'}
        </button>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {showForm && (
        <form className="card form-grid" onSubmit={handleCreate}>
          <label className="field">
            <span>Deal name</span>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Platform renewal"
              required
            />
            {fieldErrors.name && <small className="field__error">{fieldErrors.name}</small>}
          </label>

          <label className="field">
            <span>Company</span>
            <input
              value={form.company}
              onChange={(e) => setForm({ ...form, company: e.target.value })}
              placeholder="Acme Corp"
              required
            />
            {fieldErrors.company && <small className="field__error">{fieldErrors.company}</small>}
          </label>

          <label className="field">
            <span>Stage</span>
            <select
              value={form.stage}
              onChange={(e) => setForm({ ...form, stage: e.target.value })}
            >
              {STAGES.map((stage) => (
                <option key={stage} value={stage}>
                  {stage}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Value (USD)</span>
            <input
              type="number"
              value={form.value}
              onChange={(e) => setForm({ ...form, value: e.target.value })}
              placeholder="50000"
            />
          </label>

          <label className="field">
            <span>Expected close</span>
            <input
              type="date"
              value={form.close_date}
              onChange={(e) => setForm({ ...form, close_date: e.target.value })}
            />
          </label>

          <div className="form-grid__actions">
            <button type="submit" className="btn btn--primary" disabled={saving}>
              {saving ? 'Creating…' : 'Create deal'}
            </button>
          </div>
        </form>
      )}

      {deals.length === 0 && !showForm ? (
        <div className="card empty">
          <h2>Start with a deal</h2>
          <p className="muted">
            Create a deal, upload the notes and RFPs you already have, and generate a
            source-backed action plan from them.
          </p>
          <button className="btn btn--primary" onClick={() => setShowForm(true)}>
            Create your first deal
          </button>
        </div>
      ) : (
        <div className="deal-grid">
          {deals.map((deal) => (
            <div key={deal.id} className="card deal-card">
              <div className="deal-card__head">
                <span className={`badge badge--${deal.stage}`}>{deal.stage}</span>
                <button
                  className="btn btn--icon"
                  onClick={() => handleDelete(deal)}
                  aria-label={`Delete ${deal.name}`}
                  title="Delete deal"
                >
                  ×
                </button>
              </div>

              <Link to={`/deals/${deal.id}`} className="deal-card__body">
                <h2>{deal.name}</h2>
                <p className="deal-card__company">{deal.company}</p>

                <dl className="deal-card__meta">
                  <div>
                    <dt>Value</dt>
                    <dd>{deal.value ? `$${deal.value.toLocaleString()}` : '—'}</dd>
                  </div>
                  <div>
                    <dt>Documents</dt>
                    <dd>{deal.document_count}</dd>
                  </div>
                  <div>
                    <dt>Plans</dt>
                    <dd>{deal.action_plan_count}</dd>
                  </div>
                </dl>
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
