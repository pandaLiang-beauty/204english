<template>
  <main class="login-screen">
    <section class="login-intro">
      <div class="brand"><span class="brand-mark"><BookOpen /></span><div class="brand-name">204 英语</div></div>
      <div class="login-message">
        <p class="section-label">A LITTLE, EVERY DAY</p>
        <h1>把每一句，<br />慢慢读明白。</h1>
        <p>从一篇真题、一句话开始。留下需要理解的词句，在一次次复习中，让英文变得熟悉。</p>
        <div class="login-steps"><span>01 阅读真题</span><span>02 积累句子</span><span>03 持续复习</span></div>
      </div>
      <p class="quiet-note">你的个人英语学习空间</p>
    </section>
    <section class="login-form-area">
      <ThemeSwitcher />
      <form class="login-form" @submit.prevent="submit">
        <p class="section-label">WELCOME BACK</p>
        <h2>继续你的学习</h2>
        <p class="quiet-note mt-3">输入密码，回到上次的进度。</p>
        <label for="login-password">登录密码</label>
        <div class="password-field">
          <input id="login-password" v-model="password" :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password" autofocus class="ui-input" placeholder="输入你的密码" :aria-invalid="Boolean(error)" aria-describedby="login-error" />
          <button type="button" class="ui-icon-button ghost" :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            :aria-pressed="showPassword" @click="showPassword = !showPassword"><EyeOff v-if="showPassword" /><Eye v-else /></button>
        </div>
        <button type="submit" :disabled="loading || !password" class="ui-button primary">{{ loading ? '正在登录…' : '进入学习空间' }}<ArrowRight /></button>
        <p v-if="error" id="login-error" role="alert" class="status-message error mt-4">{{ error }}</p>
      </form>
    </section>
  </main>
</template>
<script setup>
import { BookOpen, Eye, EyeOff, ArrowRight } from '@lucide/vue'
import { ref } from 'vue'
import ThemeSwitcher from './ThemeSwitcher.vue'
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
