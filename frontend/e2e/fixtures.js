// All browser writes stay in this fixture. The test server cannot reach the live backend.
const texts = [
  ['True understanding comes not from memorizing isolated facts, but from recognizing the **connections** between them.', '真正的理解并非来自记住孤立的事实，而是来自认识它们之间的联系。', 'connections', '联系；句中指不同知识之间的关联'],
  ['The ability to **adapt** to a changing environment is one of the most important skills we can develop.', '适应不断变化的环境，是我们能够培养的最重要的能力之一。', 'adapt', '适应；句中指根据环境变化作出调整'],
  ['What seems like a small step today may have a **profound** effect on the way we think tomorrow.', '今天看似微小的一步，可能对我们明天的思考方式产生深远影响。', 'profound', '深刻的；句中指影响深远'],
  ['Reading gives us the opportunity to **encounter** ideas that we might never discover on our own.', '阅读让我们有机会接触到仅凭自己可能永远无法发现的想法。', 'encounter', '遇到；句中指接触新的想法']
]
const extraWords = [
  { isolated: '孤立的', recognizing: '认识到；识别' },
  { environment: '环境', develop: '培养；发展' },
  { effect: '影响', seems: '似乎' },
  { opportunity: '机会', discover: '发现' }
]

function sentence(index) {
  const [text, translation, word, meaning] = texts[index % texts.length]
  const words = { [word]: meaning, ...extraWords[index % extraWords.length] }
  return {
    id: index + 1, text, sentence_translation: translation,
    word_translations: words, word_tips: {}, word_play_counts: {},
    sentence_segments: [text.replaceAll('**', '')], translation_segments: [translation], review_count: 3, word_play_total: 2,
    completion_count: 1, audio_available: true, audio_status: 'ready',
    audio_url: `/api/english/sentences/${index + 1}/audio`,
    pronunciations: Object.fromEntries(Object.keys(words).map(entry => [entry, `/api/test-audio/${entry}`])),
    audio_uses_global: true, created_at: '2026-09-08T10:00:00+00:00', word_network: { linked_words: [] }
  }
}

function audioBuffer() {
  const buffer = Buffer.alloc(44 + 8000)
  buffer.write('RIFF', 0); buffer.writeUInt32LE(buffer.length - 8, 4); buffer.write('WAVEfmt ', 8)
  buffer.writeUInt32LE(16, 16); buffer.writeUInt16LE(1, 20); buffer.writeUInt16LE(1, 22)
  buffer.writeUInt32LE(8000, 24); buffer.writeUInt32LE(16000, 28); buffer.writeUInt16LE(2, 32); buffer.writeUInt16LE(16, 34)
  buffer.write('data', 36); buffer.writeUInt32LE(8000, 40)
  return buffer
}

export async function mockStudy(page, options = {}) {
  const scheduledCount = options.scheduledCount || 22
  const state = {
    requests: [], unhandled: [], failCreate: false,
    sentences: Array.from({ length: Math.max(12, scheduledCount) }, (_, index) => sentence(index)),
    completed: new Set(), events: [],
    passages: [1, 2].map(id => ({
      id, title: `2026 英语${id === 1 ? '一' : '二'} · Text ${id}`, source_label: '考研英语阅读练习',
      year: 2026, exam_type: id === 1 ? 'english1' : 'english2', passage_type: 'reading_a', status: 'reading',
      selected_sentence_ids: [],
      body_text: 'Reading is more than a way to collect information. It is an opportunity to **encounter** unfamiliar ideas and to examine what we already believe. A useful question is not simply what a writer says, but how the argument has been developed.\n\nWhen we read a difficult passage, it is tempting to stop at every unfamiliar word. Yet the surrounding sentences often provide the **context** we need. Returning to a word after finishing the paragraph can make its meaning much clearer.\n\nThis is why regular practice matters. Small moments of careful reading gradually change the way we approach a text. Over time, ideas that once seemed distant begin to feel familiar.'
    }))
  }
  const scheduled = state.sentences.slice(0, scheduledCount).map((item, index) => ({
    ...item, review_round_item_id: 1000 + index, review_round_position: index + 1,
    review_repeat_index: 1,
    review_repeat_total: 1
  }))
  scheduled.slice(0, options.completedCount || 0).forEach(item => state.completed.add(item.review_round_item_id))
  const round = () => ({ id: 11, total: scheduled.length, completed: state.completed.size,
    remaining: scheduled.length - state.completed.size, is_completed: state.completed.size === scheduled.length,
    started_at: options.startedAt || '', expires_at: options.expiresAt || '2099-09-17T00:00:00+00:00',
    next_round_at: '2099-09-12T00:00:00+00:00',
    resume_page: Math.floor(Math.max(0, scheduled.findIndex(item => !state.completed.has(item.review_round_item_id))) / 20) + 1
  })
  const voices = [{ provider: 'kokoro', voice: 'bf_emma', name: 'Emma', accent: '英式', gender: '女声', available: true, description: '清晰、平稳，适合长句阅读。' }, { provider: 'edge', voice: 'en-US-JennyNeural', name: 'Jenny', accent: '美式', gender: '女声', available: true, description: '自然、明快的美式发音。' }]
  let globalVoice = { provider: 'kokoro', voice: 'bf_emma' }
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const payload = method === 'GET' ? null : request.postDataJSON()
    state.requests.push({ path, method, payload, query: Object.fromEntries(url.searchParams) })
    const ok = json => route.fulfill({ status: 200, json })
    if (path === '/api/auth/me' || path === '/api/auth/login') return ok({ user: { id: 1, username: 'learner', display_name: '我的学习空间' } })
    if (path === '/api/auth/logout') return ok({ ok: true })
    if (path.endsWith('/audio') || path.startsWith('/api/test-audio/')) return route.fulfill({ contentType: 'audio/wav', body: audioBuffer() })
    if (path === '/api/english/stats') return ok({ active: state.sentences.length, total: state.sentences.length, with_audio: state.sentences.length, sentence_reviews: 150, word_reviews: 240,
      today: { sentence_completions: state.completed.size, sentence_reviews: state.events.filter(item => item.event_type === 'sentence_play').length, word_reviews: 0 },
      legacy: { total_reviews: 100 }, word_network: { cross_sentence_words: 2, weak_words: [{ key: 'context', surfaces: ['context'], linked_sentences: 4, contexts: 2 }] }
    })
    if (path === '/api/english/heatmap') return ok({ window_days: 119, total_reviews: 290, active_days: 47, longest_streak: 8, max_count: 12, legacy_total_reviews: 100,
      days: Array.from({ length: 119 }, (_, index) => ({ date: new Date(Date.UTC(2026, 4, 16 + index)).toISOString().slice(0, 10), weekday: (index + 5) % 7, total: index % 4 ? index % 13 : 0 }))
    })
    if (path === '/api/english/audio/settings') {
      if (method === 'PUT') globalVoice = payload
      return ok({ global: globalVoice, voices, sentences: { following_global: 12 }, sample_text: 'A little practice, every day.' })
    }
    if (path === '/api/english/audio/previews') return ok({ audio_url: '/api/test-audio/preview' })
    if (path === '/api/english/audio/settings/apply') return ok({ queued: 12 })
    if (path === '/api/english/sentences' && method === 'GET') {
      const reviewing = url.searchParams.get('round_queue') === 'true'
      const search = url.searchParams.get('search')?.toLowerCase() || ''
      let items = reviewing ? scheduled : state.sentences.filter(item => (item.text + item.sentence_translation).toLowerCase().includes(search))
      const size = Number(url.searchParams.get('page_size') || 20)
      const currentPage = reviewing && url.searchParams.get('resume') === 'true' ? round().resume_page : Number(url.searchParams.get('page') || 1)
      return ok({ total: items.length, page: currentPage, items: items.slice((currentPage - 1) * size, currentPage * size).map(item => ({ ...item, review_round_item_completed: state.completed.has(item.review_round_item_id) })), ...(reviewing ? { review_round: round() } : {}) })
    }
    if (path === '/api/english/sentences' && method === 'POST') {
      if (state.failCreate) return route.fulfill({ status: 503, json: { detail: '保存暂时失败，请重试' } })
      const created = { ...sentence(state.sentences.length), ...payload, id: state.sentences.length + 1 }
      state.sentences.unshift(created)
      return ok(created)
    }
    if (path === '/api/english/sentences/bulk') {
      for (const item of payload.items) state.sentences.unshift({ ...sentence(state.sentences.length), ...item, id: state.sentences.length + 1 })
      return ok({ created: payload.items.length, reused: 0 })
    }
    const review = path.match(/^\/api\/english\/sentences\/(\d+)\/review$/)
    if (review) {
      const item = scheduled.find(item => item.review_round_item_id === payload.round_item_id)
      state.events.push(payload)
      if (payload.complete_round_item) state.completed.add(payload.round_item_id)
      return ok({ ...item, review_count: item.review_count + (payload.event_type === 'sentence_play' ? 1 : 0), review_round_item_completed: state.completed.has(payload.round_item_id), review_round_completed: round().is_completed })
    }
    const wordPlay = path.match(/^\/api\/english\/sentences\/(\d+)\/words\/.+\/play$/)
    if (wordPlay) return ok(state.sentences.find(item => item.id === Number(wordPlay[1])))
    const oneSentence = path.match(/^\/api\/english\/sentences\/(\d+)$/)
    if (oneSentence) {
      const item = state.sentences.find(item => item.id === Number(oneSentence[1]))
      if (method === 'PUT') Object.assign(item, payload)
      if (method === 'DELETE') state.sentences = state.sentences.filter(entry => entry !== item)
      return ok(item || { ok: true })
    }
    if (path === '/api/english/passages') {
      if (method === 'POST') { const item = { id: 3, ...payload, selected_sentence_ids: [] }; state.passages.push(item); return ok(item) }
      return ok({ items: state.passages, total: state.passages.length, today_items: state.passages.slice(0, 2) })
    }
    const passage = path.match(/^\/api\/english\/passages\/(\d+)(?:\/(sync-sentences|complete))?$/)
    if (passage) {
      const item = state.passages.find(item => item.id === Number(passage[1]))
      if (passage[2] === 'sync-sentences') { item.selected_sentence_ids = payload.candidate_indexes.map(index => 100 + index); return ok({ inserted: payload.candidate_indexes.length, reused: 0, passage: item }) }
      if (passage[2] === 'complete') item.status = 'done'
      if (method === 'PUT') Object.assign(item, payload)
      if (method === 'DELETE') state.passages = state.passages.filter(entry => entry !== item)
      return ok(item)
    }
    state.unhandled.push({ path, method })
    return route.fulfill({ status: 501, json: { detail: `Unmocked endpoint: ${method} ${path}` } })
  })
  return state
}
