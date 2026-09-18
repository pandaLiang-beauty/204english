import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { manualPassageCandidates, splitMarkedPassageSentences } from './passageMarkdown.js'

const fixtures = JSON.parse(readFileSync(new URL('../../../fixtures/passage_sentence_cases.json', import.meta.url), 'utf8'))
for (const fixture of fixtures) {
  test(`passage boundaries: ${fixture.name}`, () => {
    assert.deepEqual(splitMarkedPassageSentences(fixture.text), fixture.sentences)
    assert.deepEqual(manualPassageCandidates({ body_text: fixture.text }).map(item => item.text), fixture.candidates)
  })
}
