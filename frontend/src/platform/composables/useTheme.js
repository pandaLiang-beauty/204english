import { computed, ref } from 'vue'

export const THEMES = [
  { value: 'light', label: '日间' },
  { value: 'dark', label: '夜间' },
  { value: 'system', label: '跟随系统' }
]
const STORAGE_KEY = 'study-theme'
const isValid = value => THEMES.some(item => item.value === value)
const media = typeof window !== 'undefined' ? window.matchMedia?.('(prefers-color-scheme: dark)') : null
const systemDark = ref(Boolean(media?.matches))

function readPreference() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (isValid(saved)) return saved
  } catch { /* Storage is optional. */ }
  return 'system'
}
const theme = ref(readPreference())
const resolvedTheme = computed(() => theme.value === 'system' ? (systemDark.value ? 'dark' : 'light') : theme.value)

function apply() {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = resolvedTheme.value
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolvedTheme.value === 'dark' ? '#171c19' : '#f5f6f3')
}
media?.addEventListener?.('change', event => { systemDark.value = event.matches; apply() })
if (typeof window !== 'undefined') {
  window.addEventListener('storage', event => {
    if (event.key !== STORAGE_KEY && event.key !== null) return
    theme.value = isValid(event.newValue) ? event.newValue : 'system'
    apply()
  })
}
apply()

export function useTheme() {
  function setTheme(next) {
    if (!isValid(next)) return
    theme.value = next
    try { localStorage.setItem(STORAGE_KEY, next) } catch { /* Keep this visit usable. */ }
    apply()
  }
  return { theme, resolvedTheme, themes: THEMES, setTheme }
}
