import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import Spinner from '../components/Spinner'

const DOC_TYPES = [
  { value: 'meeting_note', label: 'Meeting note' },
  { value: 'company_info', label: 'Company info' },
  { value: 'rfp', label: 'RFP' },
]

const DOC_LABELS = Object.fromEntries(DOC_TYPES.map((t) => [t.value, t.label]))

export default function DealDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const fileInput = useRef(null)

  const [deal, setDeal] = useState(null)
  const [documents, setDocuments] = useState([])
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)

  const [docType, setDocType] = useState('meeting_note')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)

  const [generating, setGenerating] = useState(false)
  // Distinct from a generic error: the app declining to invent a plan it cannot
  // support is a normal, expected outcome, and it needs its own explanation.
  const [weakContext, setWeakContext] = useState(null)
  const [generateError, setGenerateError] = useState(null)

  useEffect(() => {
    Promise.all([api.getDeal(id), api.listDocuments(id), api.listPlans(id)])
      .then(([d, docs, ps]) => {
        setDeal(d)
        setDocuments(docs)
        setPlans(ps)
      })
      .catch((err) => {
        // A deal that is not yours is indistinguishable from one that does not
        // exist — both are 404. Send them back to the dashboard.
        if (err.status === 404) navigate('/deals', { replace: true })
      })
      .finally(() => setLoading(false))
  }, [id, navigate])

  async function handleUpload(event) {
    const file = event.target.files?.[0]
    if (!file) return

    setUploadError(null)
    setUploading(true)
    try {
      const created = await api.uploadDocument(id, file, docType)
      setDocuments([...documents, created])
      // Uploading new context can turn a refusal into a real answer.
      setWeakContext(null)
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function handleDeleteDocument(doc) {
    try {
      await api.deleteDocument(doc.id)
      setDocuments(documents.filter((d) => d.id !== doc.id))
    } catch (err) {
      setUploadError(err.message)
    }
  }

  async function handleGenerate() {
    setGenerating(true)
    setWeakContext(null)
    setGenerateError(null)
    try {
      const plan = await api.generatePlan(id)
      navigate(`/plans/${plan.id}`)
    } catch (err) {
      if (err.status === 422 && err.payload?.error === 'insufficient_context') {
        setWeakContext(err.payload.message)
      } else {
        setGenerateError(err.message)
      }
    } finally {
      setGenerating(false)
    }
  }

  if (loading) return <Spinner label="Loading deal…" />
  if (!deal) return null

  return (
    <div className="page">
      <Link to="/deals" className="backlink">
        ← All deals
      </Link>

      <div className="page__head">
        <div>
          <span className={`badge badge--${deal.stage}`}>{deal.stage}</span>
          <h1>{deal.name}</h1>
          <p className="muted">
            {deal.company}
            {deal.value ? ` · $${deal.value.toLocaleString()}` : ''}
            {deal.close_date ? ` · closes ${deal.close_date}` : ''}
          </p>
        </div>
      </div>

      <div className="columns">
        {/* ---- Sources ---- */}
        <section className="card">
          <h2>Sources</h2>
          <p className="muted">
            The action plan is built only from these documents. Nothing else.
          </p>

          {uploadError && <div className="alert alert--error">{uploadError}</div>}

          <div className="upload">
            <select value={docType} onChange={(e) => setDocType(e.target.value)}>
              {DOC_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>

            <label className={`btn btn--secondary ${uploading ? 'is-disabled' : ''}`}>
              {uploading ? 'Processing…' : 'Upload file'}
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.txt,.md"
                onChange={handleUpload}
                disabled={uploading}
                hidden
              />
            </label>
          </div>
          <small className="muted">PDF, TXT, or MD. Up to 10 MB.</small>

          {documents.length === 0 ? (
            <div className="empty empty--inline">
              <p className="muted">
                No documents yet. Upload a meeting note or RFP to get started.
              </p>
            </div>
          ) : (
            <ul className="doc-list">
              {documents.map((doc) => (
                <li key={doc.id}>
                  <div>
                    <strong>{doc.filename}</strong>
                    <small className="muted">
                      {DOC_LABELS[doc.doc_type] ?? doc.doc_type} · {doc.chunk_count} passages
                      indexed
                    </small>
                  </div>
                  <button
                    className="btn btn--icon"
                    onClick={() => handleDeleteDocument(doc)}
                    aria-label={`Delete ${doc.filename}`}
                    title="Delete document"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* ---- Action plans ---- */}
        <section className="card">
          <h2>Action plans</h2>
          <p className="muted">
            Generated from this deal&apos;s documents, with every claim traceable to a
            passage you can read.
          </p>

          <button
            className="btn btn--primary btn--block"
            onClick={handleGenerate}
            disabled={generating || documents.length === 0}
          >
            {generating ? 'Reading your documents…' : 'Generate action plan'}
          </button>

          {documents.length === 0 && (
            <small className="muted">Upload a document first.</small>
          )}

          {generating && (
            <p className="muted generating">
              Retrieving the most relevant passages and drafting next steps. This takes a
              few seconds.
            </p>
          )}

          {weakContext && (
            <div className="alert alert--warning">
              <strong>Not enough to go on.</strong>
              <p>{weakContext}</p>
              <small>
                We would rather say this than invent a plan you cannot verify.
              </small>
            </div>
          )}

          {generateError && <div className="alert alert--error">{generateError}</div>}

          {plans.length === 0 ? (
            <div className="empty empty--inline">
              <p className="muted">No plans yet.</p>
            </div>
          ) : (
            <ul className="plan-list">
              {plans.map((plan) => (
                <li key={plan.id}>
                  <Link to={`/plans/${plan.id}`}>
                    <strong>{new Date(plan.generated_at).toLocaleString()}</strong>
                    <span className="muted">{plan.summary}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
