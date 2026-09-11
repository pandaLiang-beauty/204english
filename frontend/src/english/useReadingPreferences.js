import { ref } from 'vue'

function saved(key, allowed, fallback) {
  try {
    const value = localStorage.getItem(key)
    return allowed.includes(value) ? value : fallback
  } catch { return fallback }
}
const readingSize = ref(saved('204-reading-size', ['normal', 'large'], 'normal'))
function select(target, key, allowed, value) {
  if (!allowed.includes(value)) return
  target.value = value
  try { localStorage.setItem(key, value) } catch { /* Optional preference storage. */ }
}
export function useReadingPreferences() {
  return {
    readingSize,
    setReadingSize: value => select(readingSize, '204-reading-size', ['normal', 'large'], value)
  }
}
