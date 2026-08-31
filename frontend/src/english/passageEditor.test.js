import assert from 'node:assert/strict'
import test from 'node:test'

import { englishApi } from './api.js'
import { useEnglishAudio } from './useEnglishAudio.js'
import { useEnglishSentenceList } from './useEnglishSentenceList.js'
import { usePassageEditor } from './usePassageEditor.js'
import { roundSentence } from './testFixtures.js'

test('a passage save response preserves edits made after the request started', async () => {
  const originalUpdatePassage = englishApi.updatePassage
  const originalWarn = console.warn
  let releaseSave
  const saveGate = new Promise(resolve => {
    releaseSave = resolve
  })
  englishApi.updatePassage = async () => saveGate
  console.warn = () => {}

  try {
    const editor = usePassageEditor()
    const passage = {
      id: 9,
      title: 'Race passage',
      source_label: '',
      source_url: '',
      year: null,
      exam_type: '',
      passage_type: 'custom',
      body_text: 'Request body',
      status: 'reading'
    }
    editor.passages.value = [passage]
    editor.activePassage.value = passage
    editor.passageForm.value = {
      id: 9,
      title: 'Race passage',
      sourceLabel: '',
      sourceUrl: '',
      year: '',
      examType: '',
      passageType: 'custom',
      bodyText: 'Request body',
      status: 'reading'
    }

    const pendingSave = editor.savePassage()
    await Promise.resolve()
    editor.passageForm.value = {
      ...editor.passageForm.value,
      bodyText: 'Newer local body'
    }
    releaseSave(passage)
    await pendingSave

    assert.equal(editor.passageForm.value.bodyText, 'Newer local body')
    assert.equal(editor.activePassage.value.body_text, 'Newer local body')
    assert.equal(editor.passageDirty.value, true)
    assert.match(editor.passageMessage.value, /仍待保存/)
  } finally {
    englishApi.updatePassage = originalUpdatePassage
    console.warn = originalWarn
  }
})

test('passage information edits are included in autosave protection', async () => {
  const originalUpdatePassage = englishApi.updatePassage
  let submittedPayload
  englishApi.updatePassage = async (_passageId, payload) => {
    submittedPayload = payload
    return {
      id: 9,
      title: payload.title,
      source_label: payload.source_label,
      source_url: payload.source_url,
      year: payload.year,
      exam_type: payload.exam_type,
      passage_type: payload.passage_type,
      body_text: payload.body_text,
      status: payload.status
    }
  }

  try {
    const editor = usePassageEditor()
    editor.activePassage.value = {
      id: 9,
      title: 'Original title',
      body_text: 'Original body',
      status: 'reading'
    }
    editor.passageForm.value = {
      id: 9,
      title: 'Updated title',
      sourceLabel: '考研真题',
      sourceUrl: '',
      year: '2026',
      examType: 'english1',
      passageType: 'reading_a',
      bodyText: 'Original body',
      status: 'reading'
    }

    editor.handlePassageFormInput()
    assert.equal(editor.passageDirty.value, true)
    assert.equal(await editor.flushPassageAutosave(), true)
    assert.equal(submittedPayload.title, 'Updated title')
    assert.equal(submittedPayload.year, 2026)
    assert.equal(editor.passageDirty.value, false)
  } finally {
    englishApi.updatePassage = originalUpdatePassage
  }
})

test('an unsaved new passage cannot be silently discarded by navigation', async () => {
  const editor = usePassageEditor()
  editor.passageForm.value.bodyText = 'A new passage draft.'
  editor.handlePassageFormInput({ bodyText: true })

  assert.equal(editor.passageDirty.value, true)
  assert.equal(await editor.flushPassageAutosave(), false)
  assert.equal(editor.passageDirty.value, true)
  assert.match(editor.passageError.value, /尚未保存/)
})

test('passage flush waits for the active autosave request', async () => {
  const originalUpdatePassage = englishApi.updatePassage
  const originalWarn = console.warn
  let releaseSave
  const saveGate = new Promise(resolve => {
    releaseSave = resolve
  })
  englishApi.updatePassage = async () => saveGate
  console.warn = () => {}

  try {
    const editor = usePassageEditor()
    editor.activePassage.value = { id: 9, status: 'reading' }
    editor.passageForm.value = {
      id: 9,
      title: 'Autosave passage',
      sourceLabel: '',
      sourceUrl: '',
      year: '',
      examType: '',
      passageType: 'custom',
      bodyText: 'Edited body',
      status: 'reading'
    }
    editor.passageDirty.value = true

    let settled = false
    const flush = editor.flushPassageAutosave().then(result => {
      settled = true
      return result
    })
    await Promise.resolve()
    assert.equal(settled, false)

    releaseSave({
      id: 9,
      title: 'Autosave passage',
      source_label: '',
      source_url: '',
      year: null,
      exam_type: '',
      passage_type: 'custom',
      body_text: 'Edited body',
      status: 'reading'
    })
    assert.equal(await flush, true)
    assert.equal(editor.passageDirty.value, false)
  } finally {
    englishApi.updatePassage = originalUpdatePassage
    console.warn = originalWarn
  }
})

test('首屏的 stats 与句子列表并发请求，不再白等一个隧道往返', async () => {
  const originals = { stats: englishApi.stats, sentences: englishApi.sentences }
  let sentencesCalled = false
  let releaseStats
  // stats 故意卡住：如果这两个请求还是串行的，句子请求永远发不出去，这个测试会挂死。
  const statsGate = new Promise(resolve => {
    releaseStats = resolve
  })

  englishApi.stats = async () => {
    await statsGate
    return { active: 4 }
  }
  englishApi.sentences = async () => {
    sentencesCalled = true
    releaseStats()
    return { items: [roundSentence(1)], total: 1, page: 1 }
  }

  try {
    const list = useEnglishSentenceList({ isReview: () => true })
    await list.load()
    assert.equal(sentencesCalled, true)
    assert.deepEqual(list.sentences.value.map(item => item.id), [1])
    // 句子响应里的 total 必须盖住 fetchActivity 写进去的 stats.active，取值顺序不能被并发打乱。
    assert.equal(list.total.value, 1)
  } finally {
    Object.assign(englishApi, originals)
  }
})

test('音频预加载同时最多 3 个请求在飞，不会把链路打满', async () => {
  const originalWindow = globalThis.window
  const originalFetch = globalThis.fetch
  const originalCreateObjectURL = URL.createObjectURL
  const originalRevokeObjectURL = URL.revokeObjectURL

  let inFlight = 0
  let peak = 0
  let started = 0
  const pending = []

  globalThis.window = { setTimeout, clearTimeout }
  URL.createObjectURL = () => 'blob:stub'
  URL.revokeObjectURL = () => {}
  globalThis.fetch = () => {
    inFlight += 1
    started += 1
    peak = Math.max(peak, inFlight)
    return new Promise(resolve => {
      pending.push(() => {
        inFlight -= 1
        resolve({ ok: true, blob: async () => ({}) })
      })
    })
  }

  // 12 句 × (1 条整句音频 + 2 个生词读音) = 36 个请求；旧实现会几乎同时全部发出。
  const sentences = Array.from({ length: 12 }, (_, index) => ({
    ...roundSentence(index + 1),
    pronunciations: {
      alpha: `/api/english/pronunciations/${index}/alpha.mp3`,
      beta: `/api/english/pronunciations/${index}/beta.mp3`
    },
    ui: { cachedAudioUrl: '', pendingCachedAudioUrl: '', wordAudioCache: {}, audioPreloadPromise: null }
  }))

  try {
    const controls = useEnglishAudio({ value: sentences })
    controls.schedulePreloadWindow(0)
    await new Promise(resolve => setTimeout(resolve, 250))
    assert.equal(peak <= 3, true, `预加载峰值并发 ${peak}，应当不超过 3`)

    for (let guard = 0; pending.length && guard < 200; guard += 1) {
      pending.shift()()
      await new Promise(resolve => setTimeout(resolve, 0))
    }
    assert.equal(peak <= 3, true, `放行过程中峰值并发 ${peak}，应当不超过 3`)
    assert.equal(started, 36)
  } finally {
    globalThis.window = originalWindow
    globalThis.fetch = originalFetch
    URL.createObjectURL = originalCreateObjectURL
    URL.revokeObjectURL = originalRevokeObjectURL
  }
})
