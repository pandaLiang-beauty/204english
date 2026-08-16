import { request } from './http'


export const platformApi = {
  me: () => request('/api/auth/me'),
  login: password => request('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => request('/api/auth/logout', { method: 'POST' })
}
