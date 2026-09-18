import { englishApi } from './api.js'
import { sentenceInstanceKey } from './sentencePresentation.js'
import { mergeReviewRoundState } from './reviewRoundState.js'

/**
 * Serializes review writes for each sentence instance.
 *
 * A review queue is intentionally separate from rendering and pagination: its
 * only job is to make rapid manual and audio-triggered review events arrive at
 * the API in order while keeping the optimistic card state coherent.
 */
export function createReviewEventQueue({
  sentences,
  reviewRound,
  updateSentenceInList,
  refreshActivity,
  audioControls,
  onRoundExpired,
  onRoundCompleted
}) {
  const queues = new Map()

  function currentQueuedSentence(queue, fallback = null) {
    return sentences.value.find(item => sentenceInstanceKey(item) === queue.instanceKey)
      || queue.latestSentence
      || fallback
  }

  function syncReviewQueueUi(queue) {
    const current = currentQueuedSentence(queue, queue.events[0]?.sentence)
    if (!current?.ui) return
    current.ui.reviewPending = queue.events.length
    current.ui.reviewing = queue.events.length > 0
  }

  async function submitQueuedReviewEvent(queue, event) {
    const current = currentQueuedSentence(queue, event.sentence)
    if (!current) return undefined
    queue.latestSentence = current
    try {
      const isCurrentRound = () => Boolean(event.roundId && Number(reviewRound.value?.id) === event.roundId)
      const updated = await englishApi.reviewSentence(queue.sentenceId, {
        event_type: event.eventType,
        complete_round_item: event.completeRound,
        round_item_id: event.roundItemId || undefined
      })
      if (updated.review_round_expired) {
        if (isCurrentRound()) await onRoundExpired?.()
        return updated
      }
      const fresh = currentQueuedSentence(queue, current)
      const wasRoundCompleted = Boolean(fresh.review_round_item_completed)
      const itemCompleted = Boolean(updated.review_round_item_is_completed ?? updated.review_round_item_completed)
      const completedThisWrite = !wasRoundCompleted && itemCompleted
      const decorated = updateSentenceInList({
        ...updated,
        review_round_item_completed: itemCompleted,
        review_round_completed: Boolean(updated.review_round_completed)
      }, fresh, { scope: 'review' })
      queue.latestSentence = decorated
      const summary = updated.review_round
      if (isCurrentRound() && Number(summary?.id) === event.roundId) {
        reviewRound.value = mergeReviewRoundState(reviewRound.value, summary)
      } else if (completedThisWrite && isCurrentRound() && !summary) {
        reviewRound.value = {
          ...reviewRound.value,
          completed: Math.min(Number(reviewRound.value.completed || 0) + 1, Number(reviewRound.value.total || 0)),
          remaining: Math.max(Number(reviewRound.value.remaining || 0) - 1, 0),
          available_remaining: Math.max(Number(reviewRound.value.available_remaining ?? reviewRound.value.remaining ?? 0) - 1, 0)
        }
      }
      if (!event.silentMessage) decorated.ui.message = '已记录复习'
      audioControls()?.advancePreloadWindowFromSentence?.(decorated)
      await refreshActivity()
      if (isCurrentRound() && (!summary || Number(summary.id) === event.roundId) && decorated.review_round_completed) onRoundCompleted?.(updated)
      return decorated
    } catch (err) {
      const fresh = currentQueuedSentence(queue, current)
      if (fresh?.ui) fresh.ui.message = err?.message || '记录失败'
      return undefined
    }
  }

  async function drainReviewEventQueue(queue) {
    if (queue.processing) return
    queue.processing = true
    const settled = []
    try {
      while (queue.events.length) {
        const event = queue.events[0]
        const result = await submitQueuedReviewEvent(queue, event)
        queue.events.shift()
        syncReviewQueueUi(queue)
        settled.push({ event, result })
      }
    } finally {
      queue.processing = false
      if (queues.get(queue.instanceKey) === queue && !queue.events.length) queues.delete(queue.instanceKey)
      settled.forEach(({ event, result }) => event.resolve(result))
    }
  }

  function markReviewed(sentence, options = {}) {
    const sentenceId = Number(sentence?.id)
    if (!sentenceId) return Promise.resolve(undefined)
    const instanceKey = sentenceInstanceKey(sentence)
    const eventType = options.eventType === 'sentence_play' ? 'sentence_play' : 'sentence_review'
    let queue = queues.get(instanceKey)
    if (!queue) {
      queue = {
        instanceKey,
        sentenceId,
        events: [],
        processing: false,
        latestSentence: sentence
      }
      queues.set(instanceKey, queue)
    }
    if (!options.silentMessage && sentence.ui) sentence.ui.message = ''
    const pending = new Promise(resolve => {
      queue.events.push({
        sentence,
        eventType,
        completeRound: options.completeRound !== false,
        roundItemId: Number(sentence.review_round_item_id || 0),
        roundId: Number(reviewRound.value?.id || 0),
        silentMessage: Boolean(options.silentMessage),
        resolve
      })
    })
    syncReviewQueueUi(queue)
    void drainReviewEventQueue(queue)
    return pending
  }

  return { markReviewed }
}
