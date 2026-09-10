<template>
  <div class="study-shell">
    <a class="skip-link" href="#study-content">跳到学习内容</a>
    <EnglishTopNav
      :view="view"
      :user="user"
      @set-view="setView"
      @logout="requestLogout"
    />

    <main id="study-content" class="study-main" tabindex="-1">
      <EnglishFlow
        ref="englishFlow"
        :mode="view"
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

async function flushPendingChanges(options = {}) {
  const result = await englishFlow.value?.flushPendingChanges?.(options)
  return result !== false
}

async function setView(targetView) {
  if (!englishNavigation.viewPaths[targetView] || targetView === view.value) return
  await router.push(pathForView(targetView))
}

const removeNavigationGuard = router.beforeEach(async to => {
  if (viewFromPath(to.path) === view.value) return true
  return flushPendingChanges()
})

async function requestLogout() {
  if (!await flushPendingChanges({ leavingApp: true })) return
  emit('logout')
}

function handleBeforeUnload(event) {
  if (!englishFlow.value?.hasPendingChanges?.()) return
  event.preventDefault()
  event.returnValue = ''
}

watch(() => route.path, path => {
  const nextView = viewFromPath(path)
  if (nextView === view.value) return
  view.value = nextView
})

onMounted(() => window.addEventListener('beforeunload', handleBeforeUnload))
onBeforeUnmount(() => {
  removeNavigationGuard()
  window.removeEventListener('beforeunload', handleBeforeUnload)
})
</script>
