import assert from 'node:assert/strict'
import test from 'node:test'

import { segmentPairs } from './sentencePresentation.js'

test('segment pairs preserve each English and Chinese reading block for review rendering', () => {
  assert.deepEqual(segmentPairs({
    sentence_segments: ['When the bell rang', 'we left the room.'],
    translation_segments: ['铃响时', '我们离开了房间。']
  }), [
    { source: 'When the bell rang', target: '铃响时' },
    { source: 'we left the room.', target: '我们离开了房间。' }
  ])
})
