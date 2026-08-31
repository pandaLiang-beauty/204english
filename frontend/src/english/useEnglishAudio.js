import { ref } from 'vue'
import { englishApi } from './api.js'

export function useEnglishAudio(sentencesRef, callbacks = {}) {
  const preloadWindowStart = ref(0)
  const preloadGeneration = ref(0)

  let currentWordAudio = null
  let currentSentenceAudio = null
  let currentSentenceKey = ''
  const sentenceAudioElements = new Map()
  const recordedSentenceStarts = new WeakSet()
  const audioStatusRefreshTimers = new Set()
  const preloadWindowSize = 36
  // 预加载走「队列 + 固定并发」而不是按固定间隔一次性铺开：铺开时 20 句 × (1 条整句音频
  // + 每个生词读音) 会同时有几十个 fetch 在飞，把 Cloudflare Tunnel 打满，浏览器侧直接
  // TypeError: Failed to fetch（后端日志里那些请求其实都是 200），预加载全白做。
  const preloadConcurrency = 3
  const preloadStartDelay = 180
  let preloadQueue = []
  let preloadWorkers = 0
  let preloadStartTimer = null

  function scheduleAudioStatusRefresh(delay = 25000) {
    if (typeof window === 'undefined') return
    const timer = window.setTimeout(async () => {
      audioStatusRefreshTimers.delete(timer)
      if (callbacks.shouldSkipStatusRefresh?.()) return
      await callbacks.refreshAudioStatus?.()
    }, delay)
    audioStatusRefreshTimers.add(timer)
  }

  function resolveSentenceAudioSrc(sentence) {
    return sentence?.ui?.cachedAudioUrl || sentence?.audio_url || ''
  }

  function sentenceInstanceKey(sentence) {
    if (typeof sentence === 'number' || typeof sentence === 'string') {
      return `sentence-${Number(sentence || 0)}`
    }
    const roundItemId = Number(sentence?.review_round_item_id || 0)
    return roundItemId > 0 ? `round-${roundItemId}` : `sentence-${Number(sentence?.id || 0)}`
  }

  function setSentenceAudioRef(sentence, el) {
    const key = sentenceInstanceKey(sentence)
    if (!key) return
    if (el) sentenceAudioElements.set(key, el)
    else sentenceAudioElements.delete(key)
  }

  function stopWordAudio() {
    if (!currentWordAudio) return
    currentWordAudio.pause()
    currentWordAudio = null
  }

  function stopSentenceAudio() {
    if (!currentSentenceAudio) return
    currentSentenceAudio.pause()
    currentSentenceAudio = null
    currentSentenceKey = ''
  }

  function stopAllAudio() {
    stopWordAudio()
    stopSentenceAudio()
  }

  async function toggleSentenceAudio(sentence) {
    if (!sentence) return
    const key = sentenceInstanceKey(sentence)
    const audio = sentenceAudioElements.get(key)
    if (!audio) {
      sentence.ui.message = '整句音频不可用'
      return
    }
    if (sentence.ui.audioPlaying && !audio.paused) {
      audio.pause()
      return
    }
    if (currentSentenceAudio && currentSentenceAudio !== audio) {
      currentSentenceAudio.pause()
    }
    stopWordAudio()
    currentSentenceAudio = audio
    currentSentenceKey = key
    sentence.ui.message = ''
    try {
      await audio.play()
    } catch (err) {
      sentence.ui.audioPlaying = false
      sentence.ui.status = ''
      if (currentSentenceAudio === audio) {
        currentSentenceAudio = null
        currentSentenceKey = ''
      }
      sentence.ui.message = err?.message || '无法播放整句音频'
    }
  }

  function resolveWordAudioSource(sentence, word) {
    if (!sentence || !word) return ''
    const cached = sentence.ui.wordAudioCache?.[word]
    if (cached) return cached
    if (sentence.pronunciations?.[word]) return sentence.pronunciations[word]
    const normalized = String(word).trim().toLowerCase().replace(/^\W+|\W+$/g, '')
    const cachedEntry = Object.entries(sentence.ui.wordAudioCache || {}).find(([key]) => (
      String(key).trim().toLowerCase().replace(/^\W+|\W+$/g, '') === normalized
    ))
    if (cachedEntry?.[1]) return cachedEntry[1]
    const sourceEntry = Object.entries(sentence.pronunciations || {}).find(([key]) => (
      String(key).trim().toLowerCase().replace(/^\W+|\W+$/g, '') === normalized
    ))
    return sourceEntry?.[1] || ''
  }

  async function playWord(sentence, word) {
    if (!sentence || !word) return
    sentence.ui.wordPlaying = word
    sentence.ui.message = ''
    try {
      const source = resolveWordAudioSource(sentence, word)
      if (!source) {
        sentence.ui.message = `${word} 暂无读音`
        return
      }
      if (currentWordAudio) {
        stopWordAudio()
      }
      stopSentenceAudio()
      currentWordAudio = new Audio(source)
      currentWordAudio.addEventListener('ended', () => {
        currentWordAudio = null
      }, { once: true })
      await currentWordAudio.play()
      const updated = await englishApi.playWord(sentence.id, word)
      const decorated = callbacks.updateSentenceInList?.(updated, sentence)
      if (decorated?.ui) decorated.ui.wordPlaying = ''
      await callbacks.refreshActivity?.()
    } catch (err) {
      sentence.ui.message = err?.message || '无法播放读音'
    } finally {
      sentence.ui.wordPlaying = ''
    }
  }

  function handleSentenceAudioEnded(sentence) {
    if (!sentence) return
    const audio = sentenceAudioElements.get(sentenceInstanceKey(sentence))
    if (audio) recordedSentenceStarts.delete(audio)
    handleSentenceAudioPause(sentence)
  }

  function handleSentenceAudioPlay(sentence) {
    const key = sentenceInstanceKey(sentence)
    const audio = sentenceAudioElements.get(key)
    if (currentSentenceAudio && currentSentenceAudio !== audio) {
      currentSentenceAudio.pause()
    }
    stopWordAudio()
    currentSentenceAudio = audio || currentSentenceAudio
    currentSentenceKey = key || currentSentenceKey
    sentence.ui.audioPlaying = true
    sentence.ui.status = '播放中'
    if (!audio || Number(audio.currentTime || 0) > 0.05 || recordedSentenceStarts.has(audio)) return
    recordedSentenceStarts.add(audio)
    void callbacks.markReviewed?.(sentence, {
      eventType: 'sentence_play',
      completeRound: false,
      silentMessage: true
    })
  }

  function handleSentenceAudioPause(sentence) {
    sentence.ui.audioPlaying = false
    sentence.ui.status = ''
    applyPendingSentenceAudioCache(sentence)
    if (sentenceInstanceKey(sentence) === currentSentenceKey) {
      currentSentenceAudio = null
      currentSentenceKey = ''
    }
  }

  function applyPendingSentenceAudioCache(sentence) {
    if (!sentence?.ui?.pendingCachedAudioUrl) return
    if (sentence.ui.cachedAudioUrl) URL.revokeObjectURL(sentence.ui.cachedAudioUrl)
    sentence.ui.cachedAudioUrl = sentence.ui.pendingCachedAudioUrl
    sentence.ui.pendingCachedAudioUrl = ''
  }

  function resetPreloadWindow() {
    preloadWindowStart.value = 0
    preloadGeneration.value += 1
    // 换页/换模式时把还没开工的任务丢掉，别让上一页的音频继续抢带宽。
    preloadQueue = []
    if (preloadStartTimer !== null) {
      window.clearTimeout(preloadStartTimer)
      preloadStartTimer = null
    }
  }

  function schedulePreloadWindow(startIndex = preloadWindowStart.value) {
    if (typeof window === 'undefined') return
    const generationSnapshot = preloadGeneration.value
    const begin = Math.max(0, startIndex)
    const end = Math.min(sentencesRef.value.length, begin + preloadWindowSize)
    for (let index = begin; index < end; index += 1) {
      const sentence = sentencesRef.value[index]
      if (!sentence?.ui) continue
      // 队列单位是「一个请求」而不是「一句」：按句排队的话，一句自己就带着整句音频 +
      // 当前生词两个请求在飞，3 个 worker 实际会到 6 并发。先整句音频再本句生词，
      // 保证靠前的句子整包先就绪。
      enqueuePreload(generationSnapshot, sentence, '')
      Object.keys(sentence.pronunciations || {}).forEach(word => {
        enqueuePreload(generationSnapshot, sentence, word)
      })
    }
    startPreloadWorkers()
  }

  function enqueuePreload(generation, sentence, word) {
    if (preloadQueue.some(task => task.sentence === sentence && task.word === word)) return
    preloadQueue.push({ generation, sentence, word })
  }

  function startPreloadWorkers() {
    if (!preloadQueue.length || preloadStartTimer !== null) return
    // 延后一点再开工，把首屏那一下让给正在渲染的句子和它自己的按需播放。
    preloadStartTimer = window.setTimeout(() => {
      preloadStartTimer = null
      while (preloadWorkers < preloadConcurrency && preloadQueue.length) {
        preloadWorkers += 1
        void runPreloadWorker()
      }
    }, preloadStartDelay)
  }

  async function runPreloadWorker() {
    try {
      while (preloadQueue.length) {
        const task = preloadQueue.shift()
        if (task.generation !== preloadGeneration.value) continue
        await runPreloadTask(task)
      }
    } finally {
      preloadWorkers -= 1
    }
  }

  async function runPreloadTask({ sentence, word }) {
    if (word) {
      await cacheWordAudioBlob(sentence, word, sentence.pronunciations?.[word])
      return
    }
    await preloadSentenceAudio(sentence)
  }

  function preloadSentenceAudio(sentence) {
    if (!sentence?.audio_url || sentence.ui.cachedAudioUrl || sentence.ui.audioPreloadPromise) {
      return sentence?.ui?.audioPreloadPromise
    }
    sentence.ui.audioPreloadPromise = (async () => {
      try {
        const blob = await fetchBinaryBlob(sentence.audio_url)
        if (blob) cacheSentenceAudioBlob(sentence, blob)
      } catch (err) {
        console.warn('预加载句子音频失败', err)
      } finally {
        sentence.ui.audioPreloadPromise = null
      }
    })()
    return sentence.ui.audioPreloadPromise
  }

  async function fetchBinaryBlob(url) {
    const resp = await fetch(url, { cache: 'force-cache' })
    if (!resp.ok) throw new Error(`获取音频失败: ${resp.status}`)
    return resp.blob()
  }

  function cacheSentenceAudioBlob(sentence, blob) {
    if (!sentence || !blob) return
    const objectUrl = URL.createObjectURL(blob)
    if (sentence.ui.audioPlaying) {
      if (sentence.ui.pendingCachedAudioUrl) URL.revokeObjectURL(sentence.ui.pendingCachedAudioUrl)
      sentence.ui.pendingCachedAudioUrl = objectUrl
      return
    }
    if (sentence.ui.cachedAudioUrl) URL.revokeObjectURL(sentence.ui.cachedAudioUrl)
    sentence.ui.cachedAudioUrl = objectUrl
  }

  async function cacheWordAudioBlob(sentence, word, url) {
    if (!sentence || !word || !url) return null
    if (sentence.ui.wordAudioCache[word]) return sentence.ui.wordAudioCache[word]
    try {
      const blob = await fetchBinaryBlob(url)
      const objectUrl = URL.createObjectURL(blob)
      sentence.ui.wordAudioCache[word] = objectUrl
      return objectUrl
    } catch (err) {
      console.warn(`缓存 ${word} 读音失败`, err)
      return null
    }
  }

  function advancePreloadWindowFromSentence(sentence) {
    const key = sentenceInstanceKey(sentence)
    const index = sentencesRef.value.findIndex(item => sentenceInstanceKey(item) === key)
    if (index === -1) return
    const nextStart = index + 1
    if (nextStart <= preloadWindowStart.value) return
    preloadWindowStart.value = nextStart
    schedulePreloadWindow(preloadWindowStart.value)
  }

  function disposeSentenceCaches(list = []) {
    list.forEach(sentence => {
      if (!sentence?.ui) return
      const key = sentenceInstanceKey(sentence)
      if (key === currentSentenceKey && currentSentenceAudio) {
        currentSentenceAudio.pause()
        currentSentenceAudio = null
        currentSentenceKey = ''
      }
      sentenceAudioElements.delete(key)
      if (sentence.ui.cachedAudioUrl) URL.revokeObjectURL(sentence.ui.cachedAudioUrl)
      if (sentence.ui.pendingCachedAudioUrl) URL.revokeObjectURL(sentence.ui.pendingCachedAudioUrl)
      Object.values(sentence.ui.wordAudioCache || {}).forEach(url => {
        if (url) URL.revokeObjectURL(url)
      })
      sentence.ui.cachedAudioUrl = ''
      sentence.ui.pendingCachedAudioUrl = ''
      sentence.ui.wordAudioCache = {}
    })
  }

  function disposeAudioResources() {
    audioStatusRefreshTimers.forEach(timer => window.clearTimeout(timer))
    audioStatusRefreshTimers.clear()
    stopAllAudio()
    resetPreloadWindow()
    disposeSentenceCaches(sentencesRef.value)
  }

  return {
    scheduleAudioStatusRefresh,
    resolveSentenceAudioSrc,
    setSentenceAudioRef,
    toggleSentenceAudio,
    stopAllAudio,
    playWord,
    handleSentenceAudioEnded,
    handleSentenceAudioPlay,
    handleSentenceAudioPause,
    resetPreloadWindow,
    schedulePreloadWindow,
    advancePreloadWindowFromSentence,
    disposeSentenceCaches,
    disposeAudioResources
  }
}
