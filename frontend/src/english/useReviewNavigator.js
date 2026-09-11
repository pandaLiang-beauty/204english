import { computed, nextTick, ref } from 'vue'
import { keyboardShortcutForEvent } from './keyboardShortcuts.js'
import {
  hasTranslationContent,
  sentenceInstanceKey,
  wordEntries
} from './sentencePresentation.js'

/**
 * Keyboard navigation and active-card state for the review page.
 * The page supplies persistence and audio actions, keeping this composable
 * independent from the sentence list transport.
 */
export function useReviewNavigator(options) {
  const activeSentenceIndex = ref(0)
  const sentenceCardRefs = new Map()
  let keyboardReviewPromise = null

  const activeSentence = computed(() => (
    options.sentences.value[activeSentenceIndex.value]
    || options.sentences.value[0]
    || null
  ))

  function setSentenceCardRef(sentence, el) {
    const key = sentenceInstanceKey(sentence)
    if (el) sentenceCardRefs.set(key, el)
    else sentenceCardRefs.delete(key)
  }

  function activateSentence(index, { scroll = false } = {}) {
    const maxIndex = Math.max(options.sentences.value.length - 1, 0)
    const nextIndex = Math.max(0, Math.min(Number(index) || 0, maxIndex))
    if (nextIndex !== activeSentenceIndex.value) options.stopAllAudio?.()
    activeSentenceIndex.value = nextIndex
    if (scroll) void scrollActiveSentenceIntoView()
  }

  async function scrollActiveSentenceIntoView() {
    await nextTick()
    const sentence = activeSentence.value
    const el = sentence ? sentenceCardRefs.get(sentenceInstanceKey(sentence)) : null
    el?.focus?.({ preventScroll: true })
    el?.scrollIntoView?.({ behavior: globalThis.window?.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' })
  }

  async function moveActiveSentence(delta) {
    if (!options.sentences.value.length) return
    const nextIndex = activeSentenceIndex.value + delta
    if (nextIndex >= 0 && nextIndex < options.sentences.value.length) {
      activateSentence(nextIndex, { scroll: true })
      return
    }
    if (nextIndex >= options.sentences.value.length && options.page.value < options.pageCount.value && !options.loading.value) {
      await options.nextPage()
      activateSentence(0, { scroll: true })
      return
    }
    if (nextIndex < 0 && options.page.value > 1 && !options.loading.value) {
      await options.prevPage()
      activateSentence(Math.max(options.sentences.value.length - 1, 0), { scroll: true })
    }
  }

  async function markActiveReviewedAndNext() {
    if (keyboardReviewPromise) return keyboardReviewPromise
    const sentence = activeSentence.value
    if (!sentence || sentence.ui.reviewing) return false
    const instanceKey = sentenceInstanceKey(sentence)
    const pendingReview = (async () => {
      options.stopAllAudio()
      if (sentence.review_round_item_completed) {
        if (sentenceInstanceKey(activeSentence.value) === instanceKey) await moveActiveSentence(1)
        return true
      }
      sentence.ui.message = ''
      const updated = await options.markReviewed(sentence, { silentMessage: true })
      if (!updated) return false
      if (updated.review_round_completed) {
        await options.reloadFirstPage()
        activateSentence(0, { scroll: true })
        return true
      }
      if (sentenceInstanceKey(activeSentence.value) === instanceKey) await moveActiveSentence(1)
      return true
    })()
    keyboardReviewPromise = pendingReview
    try {
      return await pendingReview
    } finally {
      if (keyboardReviewPromise === pendingReview) keyboardReviewPromise = null
    }
  }

  function reviewSentenceAndNext(index) {
    activateSentence(index)
    return markActiveReviewedAndNext()
  }

  function closeActiveSentencePanels() {
    const sentence = activeSentence.value
    if (!sentence) return
    sentence.ui.showTranslation = false
    if (sentence.ui.showEditor) options.toggleEditor(sentence)
  }

  function toggleActiveTranslation() {
    const sentence = activeSentence.value
    if (!sentence || !hasTranslationContent(sentence)) return
    sentence.ui.showTranslation = !sentence.ui.showTranslation
  }

  function playFocusWordAt(index) {
    const entry = wordEntries(activeSentence.value)[index]
    if (entry) options.playWord(activeSentence.value, entry.word)
  }

  function handleEnglishKeyboard(event) {
    if (!options.isEnabled() || !options.sentences.value.length) return
    const shortcut = keyboardShortcutForEvent(event)
    if (!shortcut) return
    if (event.repeat || keyboardReviewPromise) {
      event.preventDefault()
      return
    }
    if (shortcut.action === 'toggle-audio') {
      event.preventDefault()
      if (activeSentence.value?.audio_available && activeSentence.value?.audio_url) {
        options.toggleSentenceAudio(activeSentence.value)
      }
      return
    }
    if (shortcut.action === 'review-next') {
      event.preventDefault()
      void markActiveReviewedAndNext()
      return
    }
    if (shortcut.action === 'move') {
      event.preventDefault()
      void moveActiveSentence(shortcut.delta)
      return
    }
    if (shortcut.action === 'toggle-translation') {
      event.preventDefault()
      toggleActiveTranslation()
      return
    }
    if (shortcut.action === 'close-panels') {
      event.preventDefault()
      closeActiveSentencePanels()
      return
    }
    if (shortcut.action === 'play-word') {
      event.preventDefault()
      playFocusWordAt(shortcut.index)
    }
  }

  return {
    activeSentenceIndex,
    activeSentence,
    setSentenceCardRef,
    activateSentence,
    moveActiveSentence,
    markActiveReviewedAndNext,
    reviewSentenceAndNext,
    handleEnglishKeyboard
  }
}
