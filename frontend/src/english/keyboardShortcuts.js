const FOCUS_WORD_KEY_INDEX = Object.freeze({ q: 0, e: 1, r: 2, f: 3, g: 4 })

const TEXT_INPUT_SELECTOR = [
  'input',
  'textarea',
  'select',
  '[contenteditable="true"]',
  '[role="textbox"]'
].join(', ')

const INTERACTIVE_SELECTOR = [
  'button',
  'a[href]',
  'summary',
  '[role="button"]',
  '[role="link"]',
  '[role="menuitem"]',
  '[role="option"]',
  '[role="switch"]',
  '[role="checkbox"]',
  '[role="radio"]'
].join(', ')

function closest(element, selector) {
  return typeof element?.closest === 'function' ? element.closest(selector) : null
}

/**
 * Text entry controls keep their normal browser/IME behavior. Interactive
 * controls outside a review sentence card do too, while controls inside a
 * review card remain in the keyboard shortcut scope after being clicked.
 */
export function isKeyboardInputTarget(target) {
  if (!target || typeof target !== 'object') return false
  if (closest(target, '[data-review-keyboard-ignore]')) return true

  const tag = String(target.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable) {
    return true
  }
  if (closest(target, TEXT_INPUT_SELECTOR)) return true

  const interactive = closest(target, INTERACTIVE_SELECTOR)
  if (!interactive) return false
  return !closest(interactive, '[data-review-keyboard-scope]')
}

export function focusWordIndexForKey(key) {
  const normalized = String(key || '').toLowerCase()
  if (/^[1-9]$/.test(normalized)) return Number(normalized) - 1
  return FOCUS_WORD_KEY_INDEX[normalized] ?? -1
}

/**
 * Converts a browser key event into a small, testable review action. The
 * component still owns the side effects (audio, persistence and navigation).
 */
export function keyboardShortcutForEvent(event) {
  if (!event || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return null
  if (event.isComposing || isKeyboardInputTarget(event.target)) return null

  const key = String(event.key || '').toLowerCase()
  const focusWordIndex = focusWordIndexForKey(key)
  if (event.code === 'Space' || key === ' ' || key === 'spacebar') {
    return { action: 'toggle-audio' }
  }
  if (key === 'enter' || key === 'j') return { action: 'review-next' }
  if (key === 'arrowdown' || key === 's') return { action: 'move', delta: 1 }
  if (key === 'arrowup' || key === 'w') return { action: 'move', delta: -1 }
  if (key === 't') return { action: 'toggle-translation' }
  if (key === 'escape') return { action: 'close-panels' }
  if (focusWordIndex >= 0) return { action: 'play-word', index: focusWordIndex }
  return null
}
