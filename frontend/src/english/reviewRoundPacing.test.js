import assert from 'node:assert/strict'
import test from 'node:test'
import { nextStudyDayAt, reviewRoundPacing } from './reviewRoundPacing.js'

const round = {
  total: 1041,
  completed: 117,
  started_at: '2026-09-10T00:00:00+00:00',
  expires_at: '2026-09-21T00:00:00+00:00'
}

test('1041 items use an eleven-day cumulative reminder with existing progress', () => {
  assert.deepEqual(reviewRoundPacing(round, Date.parse('2026-09-15T02:00:00Z')), {
    days: 11, day: 6, dailyAverage: 95, target: 568, completed: 117, behind: 451, ahead: 0
  })
  const targets = Array.from({ length: 11 }, (_, day) => (
    reviewRoundPacing(round, Date.UTC(2026, 8, 10 + day)).target
  ))
  assert.equal(targets.at(-1), 1041)
  const dailyAmounts = targets.map((value, index) => value - (targets[index - 1] || 0))
  assert.equal(Math.min(...dailyAmounts), 94)
  assert.equal(Math.max(...dailyAmounts), 95)
})

test('pacing advances at Beijing 08:00 and handles the first and last day', () => {
  const before = Date.parse('2026-09-15T07:59:59+08:00')
  const after = Date.parse('2026-09-15T08:00:00+08:00')
  assert.equal(reviewRoundPacing(round, before).day, 5)
  assert.equal(reviewRoundPacing(round, after).day, 6)
  assert.equal(nextStudyDayAt(before), after)
  assert.equal(nextStudyDayAt(after), Date.parse('2026-09-16T08:00:00+08:00'))
  assert.equal(reviewRoundPacing(round, Date.parse(round.started_at) - 1).target, 0)
  assert.equal(reviewRoundPacing(round, Date.parse(round.started_at)).target, 95)
  assert.equal(reviewRoundPacing(round, Date.parse(round.expires_at)).target, 1041)
})

test('completing more than the suggested amount shows a lead without capping progress', () => {
  const ahead = reviewRoundPacing({ ...round, completed: 700 }, Date.parse('2026-09-15T02:00:00Z'))
  assert.equal(ahead.completed, 700)
  assert.equal(ahead.ahead, 132)
  assert.equal(ahead.behind, 0)
  const onTrack = reviewRoundPacing({ ...round, completed: 568 }, Date.parse('2026-09-15T02:00:00Z'))
  assert.equal(onTrack.behind, 0)
  assert.equal(onTrack.ahead, 0)
})

test('deletions use the existing cycle dates and missing metadata hides the reminder', () => {
  assert.equal(reviewRoundPacing({ ...round, total: 900 }, Date.parse('2026-09-15T02:00:00Z')).days, 11)
  assert.equal(reviewRoundPacing({ ...round, total: 0 }), null)
  assert.equal(reviewRoundPacing({ total: 1041 }), null)
  assert.equal(reviewRoundPacing({ ...round, expires_at: round.started_at }), null)
})
