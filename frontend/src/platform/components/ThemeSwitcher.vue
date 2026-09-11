<template>
  <div class="theme-switcher inline-flex items-center rounded-md border border-border bg-surface p-0.5" aria-label="主题">
    <button
      v-for="item in themes"
      :key="item.value"
      type="button"
      :title="item.label"
      :aria-label="item.label"
      :aria-pressed="theme === item.value"
      :class="[
        'inline-flex size-7 items-center justify-center rounded transition',
        theme === item.value ? 'bg-primary text-primary-foreground' : 'text-muted hover:bg-surface-2 hover:text-text'
      ]"
      @click="setTheme(item.value)"
    >
      <component :is="item.value === 'dark' ? Moon : Sun" class="size-3.5" />
    </button>
  </div>
</template>

<script setup>
import { Moon, Sun } from '@lucide/vue'
import { useTheme } from '../composables/useTheme'

const { theme, themes, setTheme } = useTheme()
</script>
