import { request } from './http'


export const platformApi = {
  me: (options = {}) => request('/api/auth/me', options),
  login: password => request('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => request('/api/auth/logout', { method: 'POST' })
}
