import assert from 'node:assert/strict'
import test from 'node:test'

import {
  focusWordIndexForKey,
  isKeyboardInputTarget,
  keyboardShortcutForEvent
} from './keyboardShortcuts.js'

function target(tagName, { reviewScope = false } = {}) {
  const normalizedTag = String(tagName || '').toLowerCase()
  const element = {
    tagName,
    closest(selector) {
      if (selector.includes('[data-review-keyboard-scope]')) {
        return reviewScope ? { dataset: { reviewKeyboardScope: '' } } : null
      }
      if (normalizedTag === 'button' && selector.includes('button')) {
        return element
      }
      return null
    }
  }
  return element
}

function keyEvent(key, options = {}) {
  return {
    key,
    code: options.code || '',
    target: options.target || target('div'),
    defaultPrevented: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    isComposing: false,
    ...options
  }
}

test('review shortcuts map to actions independently of viewport width', () => {
  assert.deepEqual(keyboardShortcutForEvent(keyEvent('j')), { action: 'review-next' })
  assert.deepEqual(keyboardShortcutForEvent(keyEvent('Enter')), { action: 'review-next' })
  assert.deepEqual(keyboardShortcutForEvent(keyEvent(' ', { code: 'Space' })), { action: 'toggle-audio' })
  assert.deepEqual(keyboardShortcutForEvent(keyEvent('ArrowDown')), { action: 'move', delta: 1 })
  assert.deepEqual(keyboardShortcutForEvent(keyEvent('w')), { action: 'move', delta: -1 })
  assert.deepEqual(keyboardShortcutForEvent(keyEvent('t')), { action: 'toggle-translation' })
  assert.deepEqual(keyboardShortcutForEvent(keyEvent('Escape')), { action: 'close-panels' })
  assert.deepEqual(keyboardShortcutForEvent(keyEvent('q')), { action: 'play-word', index: 0 })
  assert.deepEqual(keyboardShortcutForEvent(keyEvent('9')), { action: 'play-word', index: 8 })
})

test('clicking a review-card button does not disable the global shortcuts', () => {
  const reviewButton = target('BUTTON', { reviewScope: true })
  const navigationButton = target('BUTTON')

  assert.equal(isKeyboardInputTarget(reviewButton), false)
  assert.deepEqual(
    keyboardShortcutForEvent(keyEvent('j', { target: reviewButton })),
    { action: 'review-next' }
  )
  assert.equal(isKeyboardInputTarget(navigationButton), true)
  assert.equal(keyboardShortcutForEvent(keyEvent('j', { target: navigationButton })), null)
})

test('text-entry controls keep their native typing and IME behavior', () => {
  const input = target('INPUT')
  const textarea = target('TEXTAREA')
  const editable = { ...target('DIV'), isContentEditable: true }

  assert.equal(isKeyboardInputTarget(input), true)
  assert.equal(isKeyboardInputTarget(textarea), true)
  assert.equal(isKeyboardInputTarget(editable), true)
  assert.equal(keyboardShortcutForEvent(keyEvent('j', { target: input })), null)
  assert.equal(keyboardShortcutForEvent(keyEvent('j', { isComposing: true })), null)
})

test('buttons inside the inline sentence editor keep their native keyboard behavior', () => {
  const editorButton = target('BUTTON', { reviewScope: true })
  editorButton.closest = selector => {
    if (selector.includes('[data-review-keyboard-ignore]')) return { dataset: { reviewKeyboardIgnore: '' } }
    return editorButton
  }

  assert.equal(isKeyboardInputTarget(editorButton), true)
  assert.equal(keyboardShortcutForEvent(keyEvent('Enter', { target: editorButton })), null)
})

test('focus-word shortcuts retain their q/e/r/f/g and number mapping', () => {
  assert.equal(focusWordIndexForKey('q'), 0)
  assert.equal(focusWordIndexForKey('E'), 1)
  assert.equal(focusWordIndexForKey('g'), 4)
  assert.equal(focusWordIndexForKey('1'), 0)
  assert.equal(focusWordIndexForKey('9'), 8)
  assert.equal(focusWordIndexForKey('0'), -1)
  assert.equal(focusWordIndexForKey('x'), -1)
})
