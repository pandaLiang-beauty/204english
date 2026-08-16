<template>
  <main class="flex min-h-screen items-center justify-center bg-bg p-5">
    <form
      class="w-full max-w-sm rounded-lg border border-border bg-surface p-7 shadow-sm"
      @submit.prevent="submit"
    >
      <div class="mb-6 flex items-center gap-3">
        <span class="inline-flex size-10 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Languages class="size-5" />
        </span>
        <div>
          <h1 class="text-lg font-semibold text-text">英语复习</h1>
          <p class="text-sm text-muted">个人学习记录</p>
        </div>
      </div>

      <label class="block space-y-1.5">
        <span class="text-sm text-muted">密码</span>
        <div class="relative">
          <input
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password"
            autofocus
            class="w-full rounded-md border border-border bg-surface px-3 py-2.5 pr-11 outline-none transition focus:border-primary"
          />
          <button
            type="button"
            class="absolute right-2 top-1/2 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-muted transition hover:bg-surface-2 hover:text-text"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            :aria-pressed="showPassword"
            @click="showPassword = !showPassword"
          >
            <EyeOff v-if="showPassword" class="size-4" />
            <Eye v-else class="size-4" />
          </button>
        </div>
      </label>

      <button
        type="submit"
        :disabled="loading || !password"
        class="mt-5 w-full rounded-md bg-primary py-2.5 font-medium text-primary-foreground transition enabled:hover:opacity-90 disabled:opacity-60"
      >
        {{ loading ? '登录中...' : '登录' }}
      </button>

      <p v-if="error" class="mt-4 text-center text-sm text-danger">{{ error }}</p>
    </form>
  </main>
</template>

<script setup>
import { Eye, EyeOff, Languages } from '@lucide/vue'
import { ref } from 'vue'
import { platformApi } from '../api.js'

const emit = defineEmits(['logged-in'])
const password = ref('')
const showPassword = ref(false)
const loading = ref(false)
const error = ref('')

async function submit() {
  if (!password.value || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const result = await platformApi.login(password.value)
    emit('logged-in', result.user)
  } catch (err) {
    error.value = err?.message || '密码错误'
  } finally {
    loading.value = false
  }
}
</script>
