// In development VITE_API_URL is unset and requests go to /api, which Vite
// proxies to Flask. In production it points at the deployed API service.
//
// Render's blueprint injects another service's *host*, not its URL, so this can
// arrive as a bare "sales-enablement-api.onrender.com". fetch() would treat that
// as a relative path and quietly request the wrong origin, so add the scheme.
function normalizeBaseUrl(value) {
  if (!value) return ''
  const trimmed = value.replace(/\/$/, '')
  return /^https?:\/\//.test(trimmed) ? trimmed : `https://${trimmed}`
}

const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_URL)

export class ApiError extends Error {
  constructor(status, payload) {
    super(payload?.message || payload?.error || `Request failed (${status})`)
    this.status = status
    this.payload = payload
    // Field-level validation messages, e.g. { email: "..." }
    this.errors = payload?.errors ?? null
  }
}

async function request(path, { method = 'GET', body, isFormData = false } = {}) {
  const options = {
    method,
    // Without this the session cookie is neither sent nor stored, and every
    // protected route 401s.
    credentials: 'include',
    headers: {},
  }

  if (body !== undefined) {
    if (isFormData) {
      // Let the browser set Content-Type so it can add the multipart boundary.
      options.body = body
    } else {
      options.headers['Content-Type'] = 'application/json'
      options.body = JSON.stringify(body)
    }
  }

  const response = await fetch(`${BASE_URL}${path}`, options)

  if (response.status === 204) return null

  const payload = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, payload)
  return payload
}

export const api = {
  // Auth
  signup: (data) => request('/api/signup', { method: 'POST', body: data }),
  login: (data) => request('/api/login', { method: 'POST', body: data }),
  logout: () => request('/api/logout', { method: 'DELETE' }),
  me: () => request('/api/me'),

  // Deals
  listDeals: () => request('/api/deals'),
  createDeal: (data) => request('/api/deals', { method: 'POST', body: data }),
  getDeal: (id) => request(`/api/deals/${id}`),
  updateDeal: (id, data) => request(`/api/deals/${id}`, { method: 'PATCH', body: data }),
  deleteDeal: (id) => request(`/api/deals/${id}`, { method: 'DELETE' }),

  // Documents
  listDocuments: (dealId) => request(`/api/deals/${dealId}/documents`),
  uploadDocument: (dealId, file, docType) => {
    const form = new FormData()
    form.append('file', file)
    form.append('doc_type', docType)
    return request(`/api/deals/${dealId}/documents`, {
      method: 'POST',
      body: form,
      isFormData: true,
    })
  },
  deleteDocument: (id) => request(`/api/documents/${id}`, { method: 'DELETE' }),

  // Action plans
  generatePlan: (dealId) =>
    request(`/api/deals/${dealId}/action-plans`, { method: 'POST' }),
  listPlans: (dealId) => request(`/api/deals/${dealId}/action-plans`),
  getPlan: (id) => request(`/api/action-plans/${id}`),
  deletePlan: (id) => request(`/api/action-plans/${id}`, { method: 'DELETE' }),

  // Action items
  createItem: (planId, data) =>
    request(`/api/action-plans/${planId}/items`, { method: 'POST', body: data }),
  updateItem: (id, data) =>
    request(`/api/action-items/${id}`, { method: 'PATCH', body: data }),
  deleteItem: (id) => request(`/api/action-items/${id}`, { method: 'DELETE' }),

  // Decks
  generateDeck: (planId) =>
    request(`/api/action-plans/${planId}/deck`, { method: 'POST' }),
  listDecks: (planId) => request(`/api/action-plans/${planId}/decks`),
  deleteDeck: (id) => request(`/api/decks/${id}`, { method: 'DELETE' }),

  // Fetches the .pptx with credentials and triggers a browser download. The
  // bytes come through our own ownership-checked route, never a Presenton URL.
  downloadDeck: async (deckId, filename) => {
    const response = await fetch(`${BASE_URL}/api/decks/${deckId}/download`, {
      credentials: 'include',
    })
    if (!response.ok) throw new ApiError(response.status, null)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename || 'action-plan.pptx'
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  },
}
