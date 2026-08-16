<template>
  <div class="flex h-screen flex-col bg-bg text-text">
    <EnglishTopNav
      :view="view"
      :user="user"
      @set-view="setView"
      @logout="requestLogout"
    />

    <main class="min-h-0 flex-1 overflow-hidden">
      <EnglishFlow
        ref="englishFlow"
        :mode="view"
        @go-passages="setView('passages')"
        @go-review="setView('review')"
      />
    </main>
  </div>
</template>

<script setup>
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EnglishTopNav from './english/EnglishTopNav.vue'
import { englishNavigation, pathForView, viewFromPath } from './english/navigation.js'

const EnglishFlow = defineAsyncComponent(() => import('./english/EnglishFlow.vue'))

defineProps({ user: { type: Object, default: null } })
const emit = defineEmits(['logout'])
const route = useRoute()
const router = useRouter()
const englishFlow = ref(null)
const view = ref(viewFromPath(route.path))

async function flushPendingChanges() {
  const result = await englishFlow.value?.flushPendingChanges?.()
  return result !== false
}

async function setView(targetView) {
  if (!englishNavigation.viewPaths[targetView] || targetView === view.value) return
  if (!await flushPendingChanges()) return
  await router.push(pathForView(targetView))
}

async function requestLogout() {
  if (!await flushPendingChanges()) return
  emit('logout')
}

function handleBeforeUnload(event) {
  if (!englishFlow.value?.hasPendingChanges?.()) return
  event.preventDefault()
  event.returnValue = ''
}

watch(() => route.path, async path => {
  const nextView = viewFromPath(path)
  if (nextView === view.value) return
  if (!await flushPendingChanges()) {
    await router.replace(pathForView(view.value))
    return
  }
  view.value = nextView
})

onMounted(() => window.addEventListener('beforeunload', handleBeforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
</script>
