<template>
  <section>
    <div class="segmented-control stats-tabs" role="group" aria-label="学习记录页面">
      <button type="button" :aria-pressed="statsTab === 'activity'" @click="statsTab = 'activity'">学习记录</button><button type="button" :aria-pressed="statsTab === 'settings'" @click="statsTab = 'settings'">阅读与声音</button>
    </div>
    <div v-if="statsTab === 'activity'">
      <div class="learning-metrics">
        <div><p>今日完成安排</p><strong>{{ stats.today?.sentence_completions ?? 0 }}<small> 次</small></strong></div>
        <div><p>今日整句听音</p><strong>{{ stats.today?.sentence_reviews ?? 0 }}<small> 次</small></strong></div>
        <div><p>今日重点词听音</p><strong>{{ stats.today?.word_reviews ?? 0 }}<small> 次</small></strong></div>
        <div><p>近 {{ heatmap?.window_days ?? 119 }} 天学习</p><strong>{{ heatmap?.active_days ?? 0 }}<small> 天</small></strong></div>
      </div>
      <div class="learning-record-grid">
        <div class="grid content-start gap-6 min-w-0">
          <section class="surface-panel">
            <div class="flex flex-wrap items-center justify-between gap-2"><h2 class="section-heading">每一次听音，都留下记录</h2><span class="quiet-note">近 {{ heatmap?.window_days ?? 119 }} 天</span></div>
            <p class="quiet-note mt-2">整句与重点词的播放次数</p>
            <div class="heatmap-scroll"><div class="heatmap-grid" :style="{ gridTemplateColumns: `repeat(${heatmapColumns}, minmax(10px, 1fr))` }"><div v-for="(day, index) in heatmapCells" :key="day?.date || `blank-${index}`" :class="heatCellClass(day, 'large')" :title="heatCellTitle(day)" :aria-label="heatCellTitle(day)" :tabindex="day ? 0 : undefined" /></div></div>
            <div class="flex items-center justify-between gap-3 quiet-note"><span>累计 {{ heatmap?.total_reviews ?? 0 }} 次听音</span><div class="heatmap-legend"><span>少</span><i v-for="level in [0, 1, 2, 3]" :key="level" :style="{ background: level ? `color-mix(in srgb, var(--primary) ${level * 33}%, var(--surface))` : 'var(--surface-2)' }" /><span>多</span></div></div>
          </section>
          <section class="surface-panel">
            <div class="flex items-center justify-between gap-3"><h2 class="section-heading">在不同句子里反复遇见</h2><span class="quiet-note">跨句关联词</span></div>
            <p class="quiet-note mt-2">这些词还值得在不同语境里多听、多理解。</p>
            <div class="linked-word-list"><div v-for="word in weakNetworkWords.slice(0, 8)" :key="word.key" class="linked-word-row"><strong>{{ word.surfaces?.[0] || word.key }}</strong><span>{{ word.linked_sentences }} 个句子</span><span>{{ word.contexts }} 种语境</span></div></div>
            <p v-if="!weakNetworkWords.length" class="quiet-note mt-5">积累更多句子后，这里会显示共同出现的重点词。</p>
          </section>
        </div>
        <aside class="collection-summary surface-panel"><BookOpen /><h2 class="section-heading">已经留下的积累</h2><p class="collection-total">{{ stats.active ?? 0 }}<span> 句英文</span></p><dl><div><dt>可听整句</dt><dd>{{ stats.with_audio ?? 0 }} 句</dd></div><div><dt>累计整句播放</dt><dd>{{ stats.sentence_reviews ?? 0 }} 次</dd></div><div><dt>累计重点词播放</dt><dd>{{ stats.word_reviews ?? 0 }} 次</dd></div><div><dt>最长连续学习</dt><dd>{{ heatmap?.longest_streak ?? 0 }} 天</dd></div></dl><p class="quiet-note mt-5">累计播放保留了旧系统的 {{ legacyReviewTotal }} 次历史记录。</p></aside>
      </div>
    </div>
    <div v-else class="preferences-grid">
      <section class="surface-panel reading-preferences"><div><h2 class="section-heading">让阅读更适合此刻</h2><p class="quiet-note mt-2">外观和字号会在这台设备上记住。</p></div><div><p class="quiet-note mb-2">外观</p><ThemeSwitcher /></div><div><p class="quiet-note mb-2">阅读字号</p><div class="segmented-control" role="group" aria-label="阅读字号"><button type="button" :aria-pressed="readingSize === 'normal'" @click="setReadingSize('normal')">标准字号</button><button type="button" :aria-pressed="readingSize === 'large'" @click="setReadingSize('large')">大字阅读</button></div></div></section>
      <div class="surface-panel audio-preferences">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold text-text">选择听起来舒服的声音</h2>
            <div class="mt-1 text-xs text-muted">当前默认：{{ globalSentenceAudioIdentity() }}</div>
          </div>
          <div class="flex flex-wrap items-center justify-end gap-2">
            <select
              :value="selectedGlobalVoice"
              class="h-9 min-w-0 max-w-full rounded-md border border-border bg-bg px-2 text-sm text-text outline-none focus:border-primary sm:min-w-52"
              :disabled="audioSettingsLoading || audioSettingsSaving || audioSettingsApplying"
              aria-label="全局整句音色"
              @change="emit('update:selected-global-voice', $event.target.value)"
            >
              <optgroup
                v-for="group in audioVoiceGroups"
                :key="group.key"
                :label="group.label"
              >
                <option
                  v-for="voice in group.voices"
                  :key="audioVoiceKey(voice.provider, voice.voice)"
                  :value="audioVoiceKey(voice.provider, voice.voice)"
                  :disabled="!voice.available"
                >
                  {{ audioVoiceOptionLabel(voice) }}{{ voice.available ? '' : '（未安装）' }}
                </option>
              </optgroup>
            </select>
            <button
              type="button"
              class="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
              :disabled="audioSettingsLoading || audioSettingsSaving || !selectedGlobalVoice"
              @click="emit('save-global-audio-settings')"
            >
              <Check class="h-4 w-4" />
              {{ audioSettingsSaving ? '保存中' : '设为默认' }}
            </button>
            <button
              type="button"
              class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
              :disabled="audioSettingsLoading || audioSettingsSaving || audioSettingsApplying || !selectedGlobalVoice"
              @click="emit('apply-global-audio-settings')"
            >
              <RefreshCw :class="['h-4 w-4', audioSettingsApplying ? 'animate-spin' : '']" />
              更新已有句子的音色
            </button>
          </div>
        </div>

        <div class="mt-3 rounded-md bg-bg px-3 py-2 text-sm leading-6 text-text">
          {{ audioSettings.sample_text || '选择下面的音色试听。' }}
        </div>

        <div class="mt-3 flex items-center justify-between gap-3">
          <div class="inline-flex rounded-md border border-border bg-bg p-0.5" role="group" aria-label="音色来源">
            <button
              type="button"
              :class="voiceProviderFilterButtonClass('kokoro')"
              :aria-pressed="voiceProviderFilter === 'kokoro'"
              @click="emit('update:voice-provider-filter', 'kokoro')"
            >
              本地音色 <span class="tabular-nums">{{ kokoroVoiceCount }}</span>
            </button>
            <button
              type="button"
              :class="voiceProviderFilterButtonClass('edge')"
              :aria-pressed="voiceProviderFilter === 'edge'"
              @click="emit('update:voice-provider-filter', 'edge')"
            >
              在线音色 <span class="tabular-nums">{{ edgeVoiceCount }}</span>
            </button>
          </div>
          <span class="text-xs tabular-nums text-muted">共 {{ kokoroVoiceCount + edgeVoiceCount }} 个英语音色</span>
        </div>

        <div v-if="audioSettingsLoading" class="mt-3 border-y border-border py-4 text-center text-sm text-muted">
          正在加载音色
        </div>
        <div v-else class="mt-3">
          <section
            v-for="group in filteredAudioVoiceGroups"
            :key="group.key"
            class="mb-3 last:mb-0"
          >
            <div class="mb-1.5 flex items-center justify-between gap-3 text-xs text-muted">
              <h3 class="font-medium text-text">{{ group.label }}</h3>
              <span class="tabular-nums">{{ group.voices.length }}</span>
            </div>
            <div class="divide-y divide-border border-y border-border">
              <div
                v-for="voice in group.voices"
                :key="audioVoiceKey(voice.provider, voice.voice)"
                class="flex min-w-0 items-center gap-3 py-2.5"
              >
                <button
                  type="button"
                  class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-40"
                  :disabled="!voice.available || previewLoadingVoice === audioVoiceKey(voice.provider, voice.voice)"
                  :title="previewPlayingVoice === audioVoiceKey(voice.provider, voice.voice) ? '停止试听' : `试听 ${voice.name}`"
                  @click="emit('play-voice-preview', voice)"
                >
                  <Pause v-if="previewPlayingVoice === audioVoiceKey(voice.provider, voice.voice)" class="h-4 w-4" />
                  <RefreshCw v-else-if="previewLoadingVoice === audioVoiceKey(voice.provider, voice.voice)" class="h-4 w-4 animate-spin" />
                  <Play v-else class="h-4 w-4" />
                  <span class="sr-only">试听 {{ voice.name }}</span>
                </button>
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span class="font-medium text-text">{{ voice.name }}</span>

                    <span
                      v-if="selectedGlobalVoice === audioVoiceKey(voice.provider, voice.voice)"
                      class="rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary"
                    >
                      已选择
                    </span>
                  </div>
                  <div class="mt-0.5 truncate text-xs text-muted" :title="voice.description">
                    {{ voice.description }}
                  </div>
                </div>
                <button type="button" class="ui-button small" :disabled="!voice.available || selectedGlobalVoice === audioVoiceKey(voice.provider, voice.voice)" @click="emit('update:selected-global-voice', audioVoiceKey(voice.provider, voice.voice))">{{ selectedGlobalVoice === audioVoiceKey(voice.provider, voice.voice) ? '已选择' : '选择' }}</button>
              </div>
            </div>
          </section>
        </div>

        <div v-if="audioSettingsMessage" class="mt-3 text-xs text-success">{{ audioSettingsMessage }}</div>
        <div v-if="audioSettingsError" class="mt-3 text-xs text-danger">{{ audioSettingsError }}</div>
      </div>
    </div>
  </section>
</template>
<script setup>
import { ref } from 'vue'
import { BookOpen, Check, Pause, Play, RefreshCw } from '@lucide/vue'
import ThemeSwitcher from '../../platform/components/ThemeSwitcher.vue'
import { useReadingPreferences } from '../useReadingPreferences.js'
const statsTab = ref('activity')
const { readingSize, setReadingSize } = useReadingPreferences()
const props = defineProps({
  stats: { type: Object, required: true },
  heatmap: { type: Object, default: null },
  heatmapCells: { type: Array, default: () => [] },
  heatmapColumns: { type: Number, required: true },
  legacyReviewTotal: { type: Number, required: true },
  weakNetworkWords: { type: Array, default: () => [] },
  heatCellClass: { type: Function, required: true },
  heatCellTitle: { type: Function, required: true },
  audioSettings: { type: Object, required: true },
  selectedGlobalVoice: { type: String, default: '' },
  audioSettingsLoading: { type: Boolean, default: false },
  audioSettingsSaving: { type: Boolean, default: false },
  audioSettingsApplying: { type: Boolean, default: false },
  audioSettingsMessage: { type: String, default: '' },
  audioSettingsError: { type: String, default: '' },
  previewLoadingVoice: { type: String, default: '' },
  previewPlayingVoice: { type: String, default: '' },
  voiceProviderFilter: { type: String, default: 'kokoro' },
  audioVoiceGroups: { type: Array, default: () => [] },
  filteredAudioVoiceGroups: { type: Array, default: () => [] },
  kokoroVoiceCount: { type: Number, required: true },
  edgeVoiceCount: { type: Number, required: true },
  audioVoiceKey: { type: Function, required: true },
  audioVoiceOptionLabel: { type: Function, required: true },
  voiceProviderFilterButtonClass: { type: Function, required: true },
  globalSentenceAudioIdentity: { type: Function, required: true }
})

const emit = defineEmits([
  'update:selected-global-voice',
  'save-global-audio-settings',
  'apply-global-audio-settings',
  'update:voice-provider-filter',
  'play-voice-preview'
])
</script>
