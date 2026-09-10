<template>
  <aside class="study-navigation" aria-label="学习空间">
    <div class="brand">
      <span class="brand-mark"><BookOpen /></span>
      <div><div class="brand-name">204 英语</div><div class="brand-caption">个人英语学习</div></div>
    </div>
    <p class="navigation-label">我的学习空间</p>
    <nav class="desktop-navigation" aria-label="主导航">
      <button v-for="item in englishNavigation.nav" :key="item.value" type="button" class="nav-item"
        :aria-current="active(item.value) ? 'page' : undefined" @click="$emit('set-view', item.value)">
        <component :is="icons[item.icon]" /><span>{{ item.label }}</span>
      </button>
    </nav>
    <button type="button" class="ui-button navigation-add" @click="$emit('set-view', 'create')"><Plus />添加句子</button>
    <div class="navigation-footer">
      <p class="quiet-note">选择适合此刻的外观</p>
      <ThemeSwitcher />
      <div class="user-footer">
        <span class="user-avatar">{{ userInitial }}</span>
        <span class="user-name">{{ user?.display_name || user?.username || '我的账号' }}</span>
        <button type="button" class="ui-icon-button ghost" title="退出登录" aria-label="退出登录" @click="$emit('logout')"><LogOut /></button>
      </div>
    </div>
    <header class="mobile-topbar">
      <div class="brand"><span class="brand-mark"><BookOpen /></span><span class="brand-name">204 英语</span></div>
      <div class="flex items-center gap-1">
        <ThemeSwitcher />
        <button type="button" class="ui-icon-button ghost" aria-label="退出登录" title="退出登录" @click="$emit('logout')"><LogOut /></button>
      </div>
    </header>
    <nav class="mobile-navigation" aria-label="手机导航">
      <button v-for="item in englishNavigation.nav" :key="item.value" type="button"
        :aria-current="active(item.value) ? 'page' : undefined" @click="$emit('set-view', item.value)">
        <component :is="icons[item.icon]" /><span>{{ item.shortLabel }}</span>
      </button>
    </nav>
  </aside>
</template>
<script setup>
import { computed } from 'vue'
import { BarChart3, BookOpen, BookOpenCheck, Library, LogOut, Plus } from '@lucide/vue'
import ThemeSwitcher from '../platform/components/ThemeSwitcher.vue'
import { englishNavigation } from './navigation.js'
const props = defineProps({ view: { type: String, required: true }, user: { type: Object, default: null } })
defineEmits(['set-view', 'logout'])
const icons = { BarChart3, BookOpen, BookOpenCheck, Library }
const active = value => englishNavigation.activeNav(props.view) === value
const userInitial = computed(() => String(props.user?.display_name || props.user?.username || '我').slice(0, 1).toUpperCase())
</script>
