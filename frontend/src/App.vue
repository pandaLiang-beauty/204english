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
import LoginView from './platform/components/LoginView.vue'

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

async function checkAuthentication() {
  // 登录页是唯一的恢复入口，不能因为隧道里的请求或动态模块卡住而永久停在加载态。
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 8000)
  try {
    const result = await platformApi.me({ signal: controller.signal })
    currentUser.value = result.user
  } catch {
    // 401、网络故障和超时都应该让用户得到可操作的登录表单。
    currentUser.value = null
  } finally {
    window.clearTimeout(timer)
    authChecked.value = true
  }
}

onMounted(() => {
  void checkAuthentication()
})
</script>
