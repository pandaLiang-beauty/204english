<template>
  <LoginView v-if="authChecked && !currentUser" @logged-in="onLoggedIn" />
  <div v-else-if="!authChecked" class="flex min-h-screen items-center justify-center text-muted">
    正在检查登录状态...
  </div>
  <StudyApp v-else :user="currentUser" @logout="onLogout" />
</template>

<script setup>
import { defineAsyncComponent, onMounted, ref } from 'vue'
import { platformApi } from './platform/api'

const LoginView = defineAsyncComponent(() => import('./platform/components/LoginView.vue'))
const StudyApp = defineAsyncComponent(() => import('./StudyApp.vue'))

const authChecked = ref(false)
const currentUser = ref(null)

function onLoggedIn(user) {
  currentUser.value = user
}

async function onLogout() {
  await platformApi.logout()
  currentUser.value = null
}

onMounted(async () => {
  try {
    const result = await platformApi.me()
    currentUser.value = result.user
  } catch {
    currentUser.value = null
  } finally {
    authChecked.value = true
  }
})
</script>
