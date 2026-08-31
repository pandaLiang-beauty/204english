<template>
  <section class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
    <div class="grid gap-4">
      <div class="rounded-lg border border-border bg-surface p-4">
        <div class="flex items-center justify-between gap-3">
          <h2 class="text-sm font-semibold text-text">复习热力</h2>
          <span class="text-xs text-muted">近 {{ heatmap?.window_days ?? 119 }} 天 {{ heatmap?.total_reviews ?? 0 }} 次</span>
        </div>
        <div class="mt-4 overflow-x-auto pb-1">
          <div
            class="grid grid-flow-col grid-rows-7 gap-1"
            :style="{ gridTemplateColumns: `repeat(${heatmapColumns}, 0.85rem)` }"
          >
            <div
              v-for="(day, index) in heatmapCells"
              :key="day?.date || `blank-${index}`"
              :class="heatCellClass(day, 'large')"
              :title="heatCellTitle(day)"
            />
          </div>
        </div>
      </div>

      <div class="grid gap-3 md:grid-cols-4">
        <div class="rounded-lg border border-border bg-surface p-4">
          <div class="text-xs text-muted">今日整句</div>
          <div class="mt-2 text-2xl font-semibold tabular-nums">{{ stats.today?.sentence_reviews ?? 0 }}</div>
        </div>
        <div class="rounded-lg border border-border bg-surface p-4">
          <div class="text-xs text-muted">今日单词</div>
          <div class="mt-2 text-2xl font-semibold tabular-nums">{{ stats.today?.word_reviews ?? 0 }}</div>
        </div>
        <div class="rounded-lg border border-border bg-surface p-4">
          <div class="text-xs text-muted">今日标词</div>
          <div class="mt-2 text-2xl font-semibold tabular-nums">{{ stats.today?.focus_toggles ?? 0 }}</div>
        </div>
        <div class="rounded-lg border border-border bg-surface p-4">
          <div class="text-xs text-muted">旧系统累计</div>
          <div class="mt-2 text-2xl font-semibold tabular-nums">{{ legacyReviewTotal }}</div>
        </div>
      </div>

      <div class="rounded-lg border border-border bg-surface p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold text-text">整句音色</h2>
            <div class="mt-1 text-xs text-muted">全局 {{ globalSentenceAudioIdentity() }}</div>
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
              应用到已有句子
            </button>
          </div>
        </div>

        <div class="mt-3 rounded-md bg-bg px-3 py-2 text-sm leading-6 text-text">
          {{ audioSettings.sample_text || 'relatively' }}
        </div>

        <div class="mt-3 flex items-center justify-between gap-3">
          <div class="inline-flex rounded-md border border-border bg-bg p-0.5" role="group" aria-label="音色来源">
            <button
              type="button"
              :class="voiceProviderFilterButtonClass('kokoro')"
              :aria-pressed="voiceProviderFilter === 'kokoro'"
              @click="emit('update:voice-provider-filter', 'kokoro')"
            >
              Kokoro <span class="tabular-nums">{{ kokoroVoiceCount }}</span>
            </button>
            <button
              type="button"
              :class="voiceProviderFilterButtonClass('edge')"
              :aria-pressed="voiceProviderFilter === 'edge'"
              @click="emit('update:voice-provider-filter', 'edge')"
            >
              Edge TTS <span class="tabular-nums">{{ edgeVoiceCount }}</span>
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
                    <span class="text-xs text-muted">{{ voice.voice }}</span>
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
              </div>
            </div>
          </section>
        </div>

        <div v-if="audioSettingsMessage" class="mt-3 text-xs text-success">{{ audioSettingsMessage }}</div>
        <div v-if="audioSettingsError" class="mt-3 text-xs text-danger">{{ audioSettingsError }}</div>
      </div>
    </div>

    <aside class="grid content-start gap-3 xl:sticky xl:top-4">
      <div class="rounded-lg border border-border bg-surface p-4">
        <h2 class="text-sm font-semibold text-text">语料状态</h2>
        <dl class="mt-3 grid gap-2 text-sm">
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">全部句子</dt>
            <dd class="font-semibold tabular-nums">{{ stats.total ?? '-' }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">有效句子</dt>
            <dd class="font-semibold tabular-nums">{{ stats.active ?? '-' }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">有音频</dt>
            <dd class="font-semibold tabular-nums">{{ stats.with_audio ?? '-' }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">活跃天数</dt>
            <dd class="font-semibold tabular-nums">{{ heatmap?.active_days ?? 0 }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">事件记录</dt>
            <dd class="font-semibold tabular-nums">{{ heatmap?.tracked_total_reviews ?? 0 }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">旧系统累计</dt>
            <dd class="font-semibold tabular-nums">{{ legacyReviewTotal }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">最长连续</dt>
            <dd class="font-semibold tabular-nums">{{ heatmap?.longest_streak ?? 0 }}</dd>
          </div>
        </dl>
      </div>

      <div class="rounded-lg border border-border bg-surface p-4">
        <div class="flex items-center justify-between gap-3">
          <h2 class="text-sm font-semibold text-text">关联词</h2>
          <span class="text-xs text-muted tabular-nums">{{ stats.word_network?.cross_sentence_words ?? 0 }}</span>
        </div>
        <div v-if="weakNetworkWords.length" class="mt-3 grid gap-2">
          <div
            v-for="word in weakNetworkWords"
            :key="word.key"
            class="rounded-md border border-border bg-bg px-3 py-2"
          >
            <div class="flex items-center justify-between gap-3">
              <div class="min-w-0 truncate text-sm font-semibold text-text">{{ word.surfaces?.[0] || word.key }}</div>
              <div class="shrink-0 text-xs tabular-nums text-muted">{{ Math.round((word.weakness || 0) * 100) }}%</div>
            </div>
            <div class="mt-1 flex flex-wrap gap-1.5 text-[11px] text-muted">
              <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ word.linked_sentences }} 句</span>
              <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ word.contexts }} 义项</span>
              <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ word.played_edges }} 已听</span>
            </div>
          </div>
        </div>
        <div v-else class="mt-3 text-sm text-muted">暂无跨句关联词</div>
      </div>
    </aside>
  </section>
</template>

<script setup>
import { Check, Pause, Play, RefreshCw } from '@lucide/vue'

defineProps({
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
