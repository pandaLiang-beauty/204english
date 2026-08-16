import { ref } from 'vue'

export const THEMES = [
  { value: 'light', label: '浅色主题' },
  { value: 'dark', label: '深色主题' }
]

const VALUES = THEMES.map(t => t.value)
const STORAGE_KEY = 'study-theme'

function apply(value) {
  document.documentElement.setAttribute('data-theme', value)
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    /* localStorage 不可用时忽略 */
  }
}

function resolveInitial() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && VALUES.includes(saved)) return saved
  } catch {
    /* ignore */
  }
  if (window.matchMedia?.('(prefers-color-scheme: dark)')?.matches) return 'dark'
  return 'light'
}

// 模块级单例：所有组件共享同一主题状态；模块加载时即应用，避免首屏闪烁。
const theme = ref(resolveInitial())
apply(theme.value)

export function useTheme() {
  function setTheme(next) {
    if (!VALUES.includes(next)) return
    theme.value = next
    apply(next)
  }

  function cycleTheme() {
    const idx = VALUES.indexOf(theme.value)
    setTheme(VALUES[(idx + 1) % VALUES.length])
  }

  return { theme, themes: THEMES, setTheme, cycleTheme }
}
