<template>
  <div class="segmented-control theme-switcher" role="group" aria-label="外观模式">
    <button v-for="item in themes" :key="item.value" type="button"
      :title="item.label" :aria-label="item.label" :aria-pressed="theme === item.value" @click="setTheme(item.value)">
      <component :is="icons[item.value]" />
      <span class="theme-label">{{ item.value === 'system' ? '系统' : item.label }}</span>
    </button>
  </div>
</template>
<script setup>
import { Monitor, Moon, Sun } from '@lucide/vue'
import { useTheme } from '../composables/useTheme.js'
const { theme, themes, setTheme } = useTheme()
const icons = { light: Sun, dark: Moon, system: Monitor }
</script>
