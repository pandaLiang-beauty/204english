import { ref } from 'vue'
import { englishApi } from './api.js'

export function useEnglishAudio(sentencesRef, callbacks = {}) {
  const preloadWindowStart = ref(0)
  const preloadGeneration = ref(0)

  let currentWordAudio = null
  let currentSentenceAudio = null
  let currentSentenceId = null
  const sentenceAudioElements = new Map()
  const audioStatusRefreshTimers = new Set()
  const preloadWindowSize = 36
  const preloadWarmupDelay = 180

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

  function setSentenceAudioRef(sentenceId, el) {
    const id = Number(sentenceId)
    if (!id) return
    if (el) sentenceAudioElements.set(id, el)
    else sentenceAudioElements.delete(id)
  }

  async function toggleSentenceAudio(sentence) {
    if (!sentence) return
    const sentenceId = Number(sentence.id)
    const audio = sentenceAudioElements.get(sentenceId)
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
    currentSentenceAudio = audio
    currentSentenceId = sentenceId
    sentence.ui.message = ''
    try {
      await audio.play()
    } catch (err) {
      sentence.ui.audioPlaying = false
      sentence.ui.status = ''
      if (currentSentenceAudio === audio) {
        currentSentenceAudio = null
        currentSentenceId = null
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
        currentWordAudio.pause()
        currentWordAudio = null
      }
      currentWordAudio = new Audio(source)
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

  async function handleSentenceAudioEnded(sentence) {
    if (!sentence) return
    handleSentenceAudioPause(sentence)
    sentence.ui.status = '音频结束，记录复习'
    try {
      const updated = await callbacks.markReviewed?.(sentence, {
        eventType: 'sentence_play',
        silentMessage: true
      })
      if (updated?.review_round_completed) await callbacks.reloadRound?.()
    } finally {
      const fresh = sentencesRef.value.find(item => item.id === sentence.id)
      if (fresh) fresh.ui.status = ''
    }
  }

  function handleSentenceAudioPlay(sentence) {
    const sentenceId = Number(sentence?.id)
    const audio = sentenceAudioElements.get(sentenceId)
    if (currentSentenceAudio && currentSentenceAudio !== audio) {
      currentSentenceAudio.pause()
    }
    currentSentenceAudio = audio || currentSentenceAudio
    currentSentenceId = sentenceId || currentSentenceId
    sentence.ui.audioPlaying = true
    sentence.ui.status = '播放中'
  }

  function handleSentenceAudioPause(sentence) {
    sentence.ui.audioPlaying = false
    sentence.ui.status = ''
    applyPendingSentenceAudioCache(sentence)
    if (Number(sentence?.id) === currentSentenceId) {
      currentSentenceAudio = null
      currentSentenceId = null
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
  }

  function schedulePreloadWindow(startIndex = preloadWindowStart.value) {
    if (typeof window === 'undefined') return
    const generationSnapshot = preloadGeneration.value
    const begin = Math.max(0, startIndex)
    const end = Math.min(sentencesRef.value.length, begin + preloadWindowSize)
    for (let index = begin; index < end; index += 1) {
      const sentence = sentencesRef.value[index]
      const delay = preloadWarmupDelay * (index - begin)
      window.setTimeout(() => {
        if (preloadGeneration.value !== generationSnapshot) return
        preloadSentencePackage(sentence)
      }, delay)
    }
  }

  function preloadSentencePackage(sentence) {
    preloadSentenceAudio(sentence)
    preloadWordPronunciations(sentence)
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

  function preloadWordPronunciations(sentence) {
    if (!sentence || sentence.ui.wordPreloadPromise) return sentence?.ui?.wordPreloadPromise
    const entries = Object.entries(sentence.pronunciations || {})
    if (!entries.length) return undefined
    sentence.ui.wordPreloadPromise = (async () => {
      try {
        for (const [word, url] of entries) {
          await cacheWordAudioBlob(sentence, word, url)
        }
      } catch (err) {
        console.warn('预加载单词读音失败', err)
      } finally {
        sentence.ui.wordPreloadPromise = null
      }
    })()
    return sentence.ui.wordPreloadPromise
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
    const index = sentencesRef.value.findIndex(item => item.id === sentence.id)
    if (index === -1) return
    const nextStart = index + 1
    if (nextStart <= preloadWindowStart.value) return
    preloadWindowStart.value = nextStart
    schedulePreloadWindow(preloadWindowStart.value)
  }

  function disposeSentenceCaches(list = []) {
    list.forEach(sentence => {
      if (!sentence?.ui) return
      if (Number(sentence.id) === currentSentenceId && currentSentenceAudio) {
        currentSentenceAudio.pause()
        currentSentenceAudio = null
        currentSentenceId = null
      }
      sentenceAudioElements.delete(Number(sentence.id))
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
    if (currentWordAudio) {
      currentWordAudio.pause()
      currentWordAudio = null
    }
    if (currentSentenceAudio) {
      currentSentenceAudio.pause()
      currentSentenceAudio = null
      currentSentenceId = null
    }
    resetPreloadWindow()
    disposeSentenceCaches(sentencesRef.value)
  }

  return {
    scheduleAudioStatusRefresh,
    resolveSentenceAudioSrc,
    setSentenceAudioRef,
    toggleSentenceAudio,
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
