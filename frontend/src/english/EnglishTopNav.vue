<template>
  <header class="english-top-nav shrink-0 border-b border-border bg-surface/95 backdrop-blur">
    <div class="mx-auto flex max-w-[1600px] flex-col gap-2 px-3 py-2 sm:px-5">
      <div class="flex min-w-0 items-center justify-between gap-3">
        <div class="flex min-w-0 items-center gap-2.5">
          <span class="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-contrast">
            <Languages class="size-4" />
          </span>
          <div class="min-w-0">
            <div class="truncate text-sm font-semibold text-text">英语复习</div>
            <div class="truncate text-xs text-muted">句子 · 重点词 · 阅读</div>
          </div>
        </div>

        <div class="flex shrink-0 items-center gap-2">
          <ThemeSwitcher />
          <span class="hidden max-w-28 truncate text-sm text-muted md:inline">{{ user?.display_name || user?.username }}</span>
          <button
            type="button"
            class="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
            @click="$emit('logout')"
          >
            <LogOut class="size-3.5" />
            退出
          </button>
        </div>
      </div>

      <nav class="flex min-w-0 items-center gap-1 overflow-x-auto" aria-label="英语复习导航">
        <button
          v-for="item in englishNavigation.nav"
          :key="item.value"
          type="button"
          :class="viewClass(item.value)"
          @click="$emit('set-view', item.value)"
        >
          <component :is="navIcon(item.icon)" class="size-3.5 shrink-0" />
          <span>{{ item.label }}</span>
        </button>
      </nav>
    </div>
  </header>
</template>

<script setup>
import { BarChart3, BookOpenCheck, Languages, LayoutList, LogOut, Map } from '@lucide/vue'
import ThemeSwitcher from '../platform/components/ThemeSwitcher.vue'
import { englishNavigation } from './navigation.js'

const props = defineProps({
  view: { type: String, required: true },
  user: { type: Object, default: null }
})

defineEmits(['set-view', 'logout'])

const iconMap = { BarChart3, BookOpenCheck, LayoutList, Map }

function navIcon(name) {
  return iconMap[name] || LayoutList
}

function viewClass(value) {
  return [
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border px-3 text-sm transition',
    englishNavigation.activeNav(props.view) === value
      ? 'border-border bg-surface-2 font-medium text-text shadow-sm'
      : 'border-transparent text-muted hover:border-border hover:bg-surface-2 hover:text-text'
  ]
}
</script>
