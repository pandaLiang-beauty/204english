import assert from 'node:assert/strict'
import test from 'node:test'
import { nextStudyDayAt, reviewRoundPacing } from './reviewRoundPacing.js'

const round = {
  total: 710,
  completed: 117,
  started_at: '2026-09-10T00:00:00+00:00',
  expires_at: '2026-09-18T00:00:00+00:00'
}

test('710 items use an eight-day cumulative reminder with existing progress', () => {
  assert.deepEqual(reviewRoundPacing(round, Date.parse('2026-09-15T02:00:00Z')), {
    days: 8, day: 6, dailyAverage: 89, target: 533, completed: 117, behind: 416, ahead: 0
  })
  const targets = Array.from({ length: 8 }, (_, day) => (
    reviewRoundPacing(round, Date.UTC(2026, 8, 10 + day)).target
  ))
  assert.equal(targets.at(-1), 710)
  const dailyAmounts = targets.map((value, index) => value - (targets[index - 1] || 0))
  assert.equal(Math.min(...dailyAmounts), 88)
  assert.equal(Math.max(...dailyAmounts), 89)
})

test('pacing advances at Beijing 08:00 and handles the first and last day', () => {
  const before = Date.parse('2026-09-15T07:59:59+08:00')
  const after = Date.parse('2026-09-15T08:00:00+08:00')
  assert.equal(reviewRoundPacing(round, before).day, 5)
  assert.equal(reviewRoundPacing(round, after).day, 6)
  assert.equal(nextStudyDayAt(before), after)
  assert.equal(nextStudyDayAt(after), Date.parse('2026-09-16T08:00:00+08:00'))
  assert.equal(reviewRoundPacing(round, Date.parse(round.started_at) - 1).target, 0)
  assert.equal(reviewRoundPacing(round, Date.parse(round.started_at)).target, 89)
  assert.equal(reviewRoundPacing(round, Date.parse(round.expires_at)).target, 710)
})

test('completing more than the suggested amount shows a lead without capping progress', () => {
  const ahead = reviewRoundPacing({ ...round, completed: 700 }, Date.parse('2026-09-15T02:00:00Z'))
  assert.equal(ahead.completed, 700)
  assert.equal(ahead.ahead, 167)
  assert.equal(ahead.behind, 0)
  const onTrack = reviewRoundPacing({ ...round, completed: 533 }, Date.parse('2026-09-15T02:00:00Z'))
  assert.equal(onTrack.behind, 0)
  assert.equal(onTrack.ahead, 0)
})

test('deletions use the existing cycle dates and missing metadata hides the reminder', () => {
  assert.equal(reviewRoundPacing({ ...round, total: 600 }, Date.parse('2026-09-15T02:00:00Z')).days, 8)
  assert.equal(reviewRoundPacing({ ...round, total: 0 }), null)
  assert.equal(reviewRoundPacing({ total: 710 }), null)
  assert.equal(reviewRoundPacing({ ...round, expires_at: round.started_at }), null)
})
