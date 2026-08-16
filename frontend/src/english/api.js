import { request } from '../platform/http.js'

export const englishApi = {
  stats: () => request('/api/english/stats'),
  audioSettings: () => request('/api/english/audio/settings'),
  updateAudioSettings: payload => request('/api/english/audio/settings', {
    method: 'PUT',
    body: JSON.stringify(payload)
  }),
  applyAudioSettings: () => request('/api/english/audio/settings/apply', { method: 'POST' }),
  createAudioPreview: payload => request('/api/english/audio/previews', {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  heatmap: (params = {}) => {
    const search = new URLSearchParams()
    if (params?.days) search.set('days', params.days)
    const suffix = search.toString()
    return request(`/api/english/heatmap${suffix ? `?${suffix}` : ''}`)
  },
  flowQueue: (params = {}) => {
    const search = new URLSearchParams()
    if (params?.limit) search.set('limit', params.limit)
    const suffix = search.toString()
    return request(`/api/english/flow/queue${suffix ? `?${suffix}` : ''}`)
  },
  sentences: (params = {}) => {
    const search = new URLSearchParams()
    if (params?.page) search.set('page', params.page)
    if (params?.pageSize) search.set('page_size', params.pageSize)
    if (params?.search) search.set('search', params.search)
    if (params?.sort) search.set('sort', params.sort)
    if (params?.includeDeleted) search.set('include_deleted', 'true')
    if (params?.resume) search.set('resume', 'true')
    if (params?.roundQueue) search.set('round_queue', 'true')
    const suffix = search.toString()
    return request(`/api/english/sentences${suffix ? `?${suffix}` : ''}`)
  },
  sentence: sentenceId => request(`/api/english/sentences/${sentenceId}`),
  createSentence: payload => request('/api/english/sentences', {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  createSentencesBulk: items => request('/api/english/sentences/bulk', {
    method: 'POST',
    body: JSON.stringify({ items })
  }),
  translateText: payload => request('/api/english/translate', {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  passages: (params = {}) => {
    const search = new URLSearchParams()
    if (params?.page) search.set('page', params.page)
    if (params?.pageSize) search.set('page_size', params.pageSize)
    if (params?.status) search.set('status', params.status)
    if (params?.passageType) search.set('passage_type', params.passageType)
    if (params?.examType) search.set('exam_type', params.examType)
    if (params?.year) search.set('year', params.year)
    if (params?.search) search.set('search', params.search)
    if (params?.includeDeleted) search.set('include_deleted', 'true')
    const suffix = search.toString()
    return request(`/api/english/passages${suffix ? `?${suffix}` : ''}`)
  },
  todayPassage: () => request('/api/english/passages/today'),
  createPassage: payload => request('/api/english/passages', {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  updatePassage: (passageId, payload) => request(`/api/english/passages/${passageId}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  }),
  deletePassage: passageId => request(`/api/english/passages/${passageId}`, { method: 'DELETE' }),
  syncPassageSentences: (passageId, payload = {}) => request(`/api/english/passages/${passageId}/sync-sentences`, {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  completePassage: passageId => request(`/api/english/passages/${passageId}/complete`, { method: 'POST' }),
  updateSentence: (sentenceId, payload) => request(`/api/english/sentences/${sentenceId}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  }),
  updateSentenceAudioSettings: (sentenceId, payload) => request(`/api/english/sentences/${sentenceId}/audio-settings`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  }),
  deleteSentence: sentenceId => request(`/api/english/sentences/${sentenceId}`, { method: 'DELETE' }),
  reviewSentence: (sentenceId, payload = {}) => request(`/api/english/sentences/${sentenceId}/review`, {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  playWord: (sentenceId, word) => request(`/api/english/sentences/${sentenceId}/words/${encodeURIComponent(word)}/play`, { method: 'POST' }),
  toggleFocusWord: (sentenceId, payload) => request(`/api/english/sentences/${sentenceId}/focus-word`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}
