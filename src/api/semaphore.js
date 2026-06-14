// Lightweight client for the Semaphore UI REST API.
// All requests go through the Vite dev proxy (same-origin "/api") which forwards
// the Authorization: Bearer <token> header to the configured Semaphore instance.

const BASE = '/api'

class SemaphoreError extends Error {
  constructor (message, status) {
    super(message)
    this.name = 'SemaphoreError'
    this.status = status
  }
}

async function request (path, token, options = {}) {
  const headers = {
    Accept: 'application/json',
    ...(options.headers || {}),
  }
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body) headers['Content-Type'] = 'application/json'

  let res
  try {
    res = await fetch(`${BASE}${path}`, { ...options, headers })
  } catch (err) {
    throw new SemaphoreError(`Network error: ${err.message}`, 0)
  }

  if (res.status === 401) {
    throw new SemaphoreError('Unauthorized — check your API token.', 401)
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new SemaphoreError(
      `Request failed (${res.status})${text ? `: ${text}` : ''}`,
      res.status,
    )
  }

  if (res.status === 204) return null
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) return res.json()
  return res.text()
}

export const semaphore = {
  ping () {
    return request('/ping', null)
  },
  getUser (token) {
    return request('/user', token)
  },
  getProjects (token) {
    return request('/projects', token)
  },
  getTemplates (token, projectId) {
    return request(`/project/${projectId}/templates`, token)
  },
  getTasks (token, projectId, limit = 25) {
    return request(`/project/${projectId}/tasks?limit=${limit}`, token)
  },
  runTask (token, projectId, templateId) {
    return request(`/project/${projectId}/tasks`, token, {
      method: 'POST',
      body: JSON.stringify({ template_id: templateId }),
    })
  },
}

export { SemaphoreError }
