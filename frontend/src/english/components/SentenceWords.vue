<template>
  <div class="sentence-words" :class="{ 'is-compact': compact }">
    <div v-for="(entry, index) in wordEntries(sentence)" :key="entry.word" class="word-row">
      <div class="min-w-0">
        <div class="word-heading"><span>{{ entry.word }}</span><kbd v-if="index < 9 && (shortcuts || compact)" :class="{ 'shortcut-inactive': compact && !shortcuts }">{{ index + 1 }}</kbd></div>
        <p class="word-meaning">{{ entry.meaning || '释义准备中…' }}</p>
        <p v-if="entry.tip" class="word-tip">{{ entry.tip }}</p>
      </div>
      <button type="button" class="ui-icon-button ghost" :disabled="sentence.ui.wordPlaying === entry.word || !entry.audio"
        :aria-label="`听 ${entry.word} 的发音`" :title="entry.audio ? `听 ${entry.word} 的发音` : '读音准备中'" @click.stop="playWord(sentence, entry.word)"><Volume2 /></button>
    </div>
  </div>
</template>
<script setup>
import { Volume2 } from '@lucide/vue'
import { wordEntries } from '../sentencePresentation.js'
defineProps({ sentence: { type: Object, required: true }, playWord: { type: Function, required: true }, shortcuts: Boolean, compact: Boolean })
</script>
