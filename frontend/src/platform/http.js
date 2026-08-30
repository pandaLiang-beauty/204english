export async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const writeHeaders = method === 'GET' || method === 'HEAD' ? {} : { 'X-Study-Write': '1' }
  const isForm = typeof FormData !== 'undefined' && options.body instanceof FormData
  const response = await fetch(path, {
    ...options,
    credentials: 'include',
    headers: {
      ...(isForm ? {} : { 'Content-Type': 'application/json' }),
      ...writeHeaders,
      ...(options.headers || {})
    }
  })
  if (!response.ok) {
    const text = await response.text()
    let message = text
    try {
      const data = JSON.parse(text)
      if (typeof data?.detail === 'string') message = data.detail
    } catch {
      // Keep the raw response text when it is not JSON.
    }
    throw new Error(message || `HTTP ${response.status}`)
  }
  return response.json()
}
