<template>
  <div class="h-full overflow-y-auto bg-bg text-text">
    <div class="mx-auto grid min-h-full max-w-[1500px] gap-4 px-3 py-4 md:px-5">
      <header class="border-b border-border pb-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="text-xs font-medium text-muted">英语 · {{ modeLabel }}</div>
            <h1 class="mt-1 text-xl font-semibold tracking-normal text-text">{{ pageTitle }}</h1>
            <div v-if="isReview && reviewRound" class="mt-1 text-xs tabular-nums text-muted">
              本轮 {{ reviewRound.completed || 0 }} / {{ reviewRound.total || 0 }}
            </div>
            <div v-if="isLibrary" class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs tabular-nums text-muted">
              <span>{{ stats.active ?? total }} 句</span>
              <span>{{ stats.with_audio ?? 0 }} 条整句音频</span>
              <span>{{ stats.word_network?.cross_sentence_words ?? 0 }} 个跨句关联词</span>
            </div>
          </div>
          <div class="flex flex-wrap items-center justify-end gap-2">
            <button
              v-if="!isPassages"
              type="button"
              class="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition hover:opacity-90"
              @click="$emit('goPassages')"
            >
              <BookMarked class="h-4 w-4" />
              每日阅读
            </button>
            <button
              v-else
              type="button"
              class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
              @click="$emit('goReview')"
            >
              <BookOpenCheck class="h-4 w-4" />
              句子复习
            </button>
            <button
              type="button"
              class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
              @click="load({ resumeRound: true })"
            >
              <RefreshCw class="h-4 w-4" />
              刷新
            </button>
          </div>
        </div>

        <div v-if="!isLibrary" class="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
          <div class="rounded-md border border-border bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">有效句子</div>
            <div class="mt-1 flex flex-wrap items-baseline gap-x-1 font-semibold tabular-nums text-text">
              <span>{{ stats.active ?? total }}</span>
              <span class="text-[11px] font-normal text-muted">（今日已复习 {{ stats.today?.reviewed_sentences ?? 0 }} 句）</span>
            </div>
          </div>
          <div class="rounded-md border border-border bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">累计整句</div>
            <div class="mt-1 flex flex-wrap items-baseline gap-x-1 font-semibold tabular-nums text-text">
              <span>{{ stats.sentence_reviews ?? '-' }}</span>
              <span class="text-[11px] font-normal text-muted">（今日复习 {{ stats.today?.sentence_reviews ?? 0 }} 次）</span>
            </div>
          </div>
          <div class="rounded-md border border-border bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">累计单词</div>
            <div class="mt-1 flex flex-wrap items-baseline gap-x-1 font-semibold tabular-nums text-text">
              <span>{{ stats.word_reviews ?? '-' }}</span>
              <span class="text-[11px] font-normal text-muted">（今日复习 {{ stats.today?.word_reviews ?? 0 }} 次）</span>
            </div>
          </div>
          <div class="rounded-md border border-border bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">连续天数</div>
            <div class="mt-1 font-semibold tabular-nums text-text">{{ heatmap?.current_streak ?? 0 }}</div>
          </div>
        </div>
      </header>

      <section v-if="isStats" class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
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
                  v-model="selectedGlobalVoice"
                  class="h-9 min-w-0 max-w-full rounded-md border border-border bg-bg px-2 text-sm text-text outline-none focus:border-primary sm:min-w-52"
                  :disabled="audioSettingsLoading || audioSettingsSaving || audioSettingsApplying"
                  aria-label="全局整句音色"
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
                  @click="saveGlobalAudioSettings"
                >
                  <Check class="h-4 w-4" />
                  {{ audioSettingsSaving ? '保存中' : '设为默认' }}
                </button>
                <button
                  type="button"
                  class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
                  :disabled="audioSettingsLoading || audioSettingsSaving || audioSettingsApplying || !selectedGlobalVoice"
                  @click="applyGlobalAudioSettings"
                >
                  <RefreshCw :class="['h-4 w-4', audioSettingsApplying ? 'animate-spin' : '']" />
                  应用到已有句子
                </button>
              </div>
            </div>

            <div class="mt-3 rounded-md bg-bg px-3 py-2 text-sm leading-6 text-text">
              {{ audioSettings.sample_text || 'Clear voices make every English sentence easier to follow and remember.' }}
            </div>

            <div class="mt-3 flex items-center justify-between gap-3">
              <div class="inline-flex rounded-md border border-border bg-bg p-0.5" role="group" aria-label="音色来源">
                <button
                  type="button"
                  :class="voiceProviderFilterButtonClass('kokoro')"
                  :aria-pressed="voiceProviderFilter === 'kokoro'"
                  @click="voiceProviderFilter = 'kokoro'"
                >
                  Kokoro <span class="tabular-nums">{{ kokoroVoiceCount }}</span>
                </button>
                <button
                  type="button"
                  :class="voiceProviderFilterButtonClass('edge')"
                  :aria-pressed="voiceProviderFilter === 'edge'"
                  @click="voiceProviderFilter = 'edge'"
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
                      @click="playVoicePreview(voice)"
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

      <section v-else-if="isPassages" class="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside class="grid content-start gap-4 xl:sticky xl:top-4">
          <section class="rounded-lg border border-border bg-surface p-4">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">今日阅读</h2>
              <span class="text-xs text-muted tabular-nums">2 篇 · 英一/英二</span>
            </div>
            <div v-if="todayPassages.length" class="mt-3 grid gap-2">
              <div
                v-for="(passage, index) in todayPassages"
                :key="passage.id"
                class="rounded-md border border-primary/25 bg-primary/10 p-3"
              >
                <div class="text-xs font-medium text-primary">建议 {{ index + 1 }}</div>
                <button
                  type="button"
                  class="mt-1 block w-full text-left text-sm font-semibold text-text transition hover:text-primary"
                  @click="startPassage(passage)"
                >
                  {{ passageTitle(passage) }}
                </button>
                <div class="mt-2 flex flex-wrap gap-1.5 text-[11px] text-muted">
                  <span class="rounded bg-surface px-1.5 py-0.5">{{ passageStatusLabel(passage.status) }}</span>
                  <span class="rounded bg-surface px-1.5 py-0.5">{{ passageTypeLabel(passage.passage_type) }}</span>
                  <span v-if="passage.year" class="rounded bg-surface px-1.5 py-0.5">{{ passage.year }}</span>
                  <span v-if="passage.exam_type" class="rounded bg-surface px-1.5 py-0.5">{{ examTypeLabel(passage.exam_type) }}</span>
                </div>
                <button
                  type="button"
                  class="mt-3 inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition hover:opacity-90"
                  @click="startPassage(passage)"
                >
                  <Bold class="h-3.5 w-3.5" />
                  {{ passageActionLabel(passage) }}
                </button>
              </div>
            </div>
            <div v-else class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
              暂无未完成阅读
            </div>
          </section>

          <section class="grid min-h-0 rounded-lg border border-border bg-surface p-4">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">文章队列</h2>
              <button
                type="button"
                class="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-muted transition hover:bg-surface-2 hover:text-text"
                @click="resetPassageForm"
              >
                <Plus class="h-3.5 w-3.5" />
                新文章
              </button>
            </div>
            <div class="mt-3 flex flex-wrap gap-1.5">
              <button
                v-for="option in passageTypeFilters"
                :key="option.value || 'all'"
                type="button"
                :class="[
                  'rounded-md border px-2 py-1 text-xs transition',
                  passageTypeFilter === option.value
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border bg-bg text-muted hover:bg-surface-2 hover:text-text'
                ]"
                @click="setPassageTypeFilter(option.value)"
              >
                {{ option.label }}
              </button>
            </div>
            <div class="mt-3 grid grid-cols-2 gap-2">
              <select
                v-model="passageExamFilter"
                class="h-8 rounded-md border border-border bg-bg px-2 text-xs outline-none focus:border-primary"
                @change="applyPassageFilters"
              >
                <option value="">英一 / 英二</option>
                <option value="english1">英语一</option>
                <option value="english2">英语二</option>
              </select>
              <input
                v-model="passageYearFilter"
                type="number"
                min="1900"
                max="2200"
                class="h-8 rounded-md border border-border bg-bg px-2 text-xs outline-none focus:border-primary"
                placeholder="年份"
                @keydown.enter.prevent="applyPassageFilters"
              />
            </div>
            <div class="mt-2 flex gap-2">
              <div class="relative min-w-0 flex-1">
                <Search class="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-muted" />
                <input
                  v-model="passageSearchInput"
                  type="search"
                  class="h-8 w-full rounded-md border border-border bg-bg pl-8 pr-2 text-xs outline-none focus:border-primary"
                  placeholder="年份 / Text / 标题"
                  @keydown.enter.prevent="applyPassageFilters"
                />
              </div>
              <button
                type="button"
                class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted hover:bg-surface-2 hover:text-text"
                title="搜索文章"
                @click="applyPassageFilters"
              >
                <Search class="h-3.5 w-3.5" />
              </button>
            </div>
            <div v-if="passageLoading" class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
              加载中
            </div>
            <div v-else-if="passages.length" class="mt-3 grid gap-2">
              <button
                v-for="passage in passages"
                :key="passage.id"
                type="button"
                class="rounded-md border px-3 py-2 text-left transition"
                :class="activePassage?.id === passage.id ? 'border-primary bg-primary/10' : 'border-border bg-bg hover:bg-surface-2'"
                @click="selectPassage(passage)"
              >
                <div class="flex items-center justify-between gap-3">
                  <span class="min-w-0 truncate text-sm font-semibold text-text">{{ passageTitle(passage) }}</span>
                  <span class="shrink-0 text-[11px] text-muted">#{{ passage.id }}</span>
                </div>
                <div class="mt-1 flex flex-wrap gap-1.5 text-[11px] text-muted">
                  <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ passageStatusLabel(passage.status) }}</span>
                  <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ passageTypeLabel(passage.passage_type) }}</span>
                  <span v-if="passage.year" class="rounded bg-surface-2 px-1.5 py-0.5">{{ passage.year }}</span>
                  <span v-if="passage.exam_type" class="rounded bg-surface-2 px-1.5 py-0.5">{{ examTypeLabel(passage.exam_type) }}</span>
                  <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ markedWordCount(passage) }} 标词</span>
                  <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ candidateCount(passage) }} 标注句</span>
                </div>
              </button>
            </div>
            <div v-else class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
              暂无文章
            </div>
            <div class="mt-3 flex items-center justify-between gap-2 text-xs text-muted">
              <button
                type="button"
                class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border disabled:opacity-40"
                :disabled="passagePage <= 1 || passageLoading"
                title="上一页"
                @click="changePassagePage(-1)"
              >
                <ChevronLeft class="h-3.5 w-3.5" />
              </button>
              <span class="tabular-nums">{{ passagePage }} / {{ passagePageCount }} · {{ passageTotal }}</span>
              <button
                type="button"
                class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border disabled:opacity-40"
                :disabled="passagePage >= passagePageCount || passageLoading"
                title="下一页"
                @click="changePassagePage(1)"
              >
                <ChevronRight class="h-3.5 w-3.5" />
              </button>
            </div>
          </section>
        </aside>

        <main class="grid min-w-0 content-start gap-4">
          <p v-if="passageMessage" class="rounded-md bg-primary/10 px-3 py-2 text-sm text-primary">{{ passageMessage }}</p>
          <p v-if="passageError" class="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{{ passageError }}</p>

          <section
            v-if="activePassage"
            ref="activePassagePanel"
            class="mx-auto grid w-full max-w-[980px] gap-4"
          >
            <div class="border-b border-border pb-4">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="text-xs text-muted">阅读文章 #{{ activePassage.id }}</div>
                  <h2 class="mt-1 text-xl font-semibold leading-7 text-text">{{ passageTitle(activePassage) }}</h2>
                  <div class="mt-2 flex flex-wrap gap-1.5 text-xs text-muted">
                    <span>{{ passageStatusLabel(activePassage.status) }}</span>
                    <span>{{ passageTypeLabel(activePassage.passage_type) }}</span>
                    <span v-if="activePassage.year">{{ activePassage.year }}</span>
                    <span v-if="activePassage.exam_type">{{ examTypeLabel(activePassage.exam_type) }}</span>
                    <span>{{ activePassage.body_text?.length || 0 }} 字符</span>
                    <span>{{ markedWordCount(activePassage) }} 标词</span>
                    <span>{{ candidateCount(activePassage) }} 标注句</span>
                    <span>已同步 {{ activePassage.selected_sentence_ids?.length || 0 }} 句</span>
                  </div>
                </div>
                <div class="flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
                    :disabled="passageSaving"
                    @click="savePassageAnnotations"
                  >
                    <Check class="h-4 w-4" />
                    {{ passageSaving ? '保存中' : '保存标注' }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md border border-primary/40 px-3 text-sm text-primary transition hover:bg-primary/10 disabled:opacity-50"
                    :disabled="passageSyncing || !selectedCandidateIndexes.length"
                    @click="syncSelectedCandidates"
                  >
                    <Upload class="h-4 w-4" />
                    {{ passageSyncing ? '同步中' : `同步 ${selectedCandidateIndexes.length} 句` }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
                    :disabled="passageCompleting || activePassage.status === 'done'"
                    @click="completeActivePassage"
                  >
                    <Check class="h-4 w-4" />
                    {{ activePassage.status === 'done' ? '已完成' : passageCompleting ? '记录中' : '完成阅读' }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
                    @click="passageEditorOpen = !passageEditorOpen"
                  >
                    <Pencil class="h-4 w-4" />
                    {{ passageEditorOpen ? '收起编辑' : '编辑信息' }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md border border-danger/40 px-3 text-sm text-danger transition hover:bg-danger-soft"
                    @click="deleteActivePassage"
                  >
                    <Trash2 class="h-4 w-4" />
                    删除
                  </button>
                </div>
              </div>
            </div>

            <article class="overflow-hidden rounded-lg border border-border bg-bg shadow-sm">
              <div class="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface/80 px-4 py-3 md:px-5">
                <div>
                  <h3 class="text-sm font-semibold text-text">阅读标注</h3>
                  <div class="mt-1 text-xs text-muted">{{ activePassage.source_label || '手动文章' }}</div>
                </div>
                <button
                  type="button"
                  class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted transition hover:bg-surface-2 hover:text-text"
                  title="加粗选中内容"
                  :disabled="passageSaving"
                  @mousedown.prevent="togglePassageBold"
                >
                  <Bold class="h-4 w-4" />
                </button>
              </div>
              <div
                ref="passageAnnotator"
                class="passage-annotator mx-auto min-h-[36rem] w-full max-w-[780px] px-5 py-7 text-[17px] leading-[2] text-text outline-none transition focus:bg-surface/25 md:px-8 md:py-10 md:text-[18px] md:leading-[2.05]"
                :contenteditable="passageSaving ? 'false' : 'true'"
                :aria-disabled="passageSaving"
                role="textbox"
                aria-multiline="true"
                spellcheck="false"
                @input="handlePassageAnnotatorInput"
                @keydown="handlePassageAnnotatorKeydown"
                @paste="handlePassageAnnotatorPaste"
                v-html="passageAnnotatorHtml"
              />
            </article>

            <section class="rounded-lg border border-border bg-surface p-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold text-text">标注句子</h3>
                  <div class="mt-1 text-xs text-muted tabular-nums">{{ candidateCount(activePassage) }} 句 · {{ markedWordCount(activePassage) }} 词</div>
                </div>
                <button
                  type="button"
                  class="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-60"
                  :disabled="passageSyncing || !selectedCandidateIndexes.length"
                  @click="syncSelectedCandidates"
                >
                  <Upload class="h-3.5 w-3.5" />
                  {{ passageSyncing ? '同步中' : `同步 ${selectedCandidateIndexes.length} 句` }}
                </button>
              </div>
              <div v-if="passageCandidates(activePassage).length" class="mt-3 grid gap-2">
                <label
                  v-for="(candidate, index) in passageCandidates(activePassage)"
                  :key="`${candidate.text}-${index}`"
                  class="grid cursor-pointer gap-2 rounded-md border border-border bg-bg p-3 transition hover:border-primary/40"
                >
                  <div class="flex items-start gap-3">
                    <input
                      v-model="selectedCandidateIndexes"
                      type="checkbox"
                      class="mt-1 h-4 w-4 accent-primary"
                      :value="index"
                    />
                    <div class="min-w-0">
                      <div class="text-[15px] font-medium leading-7 text-text">
                        <template v-for="(token, tokenIndex) in sentenceTokens(candidate.text)" :key="tokenIndex">
                          <span
                            v-if="token.focus"
                            class="rounded bg-primary/10 px-1 font-semibold text-primary"
                          >{{ token.text }}</span>
                          <span v-else>{{ token.text }}</span>
                        </template>
                      </div>
                      <div class="mt-2 flex flex-wrap gap-1.5 text-[11px] text-muted">
                        <span v-if="candidate.reason" class="rounded bg-bg px-1.5 py-0.5">{{ candidate.reason }}</span>
                        <span
                          v-for="word in candidate.focus_words || []"
                          :key="`${candidate.text}-${word.word}`"
                          class="rounded bg-bg px-1.5 py-0.5"
                        >
                          {{ word.word }}
                        </span>
                      </div>
                    </div>
                  </div>
                </label>
              </div>
              <div v-else class="mt-3 rounded-md border border-dashed border-border bg-surface px-3 py-4 text-center text-sm text-muted">
                暂无标注句
              </div>
            </section>
          </section>

          <section v-else-if="!passageEditorOpen" class="rounded-lg border border-border bg-surface p-6">
            <h2 class="text-sm font-semibold text-text">选择一篇文章开始阅读</h2>
            <p class="mt-2 text-sm text-muted">左侧队列里选择文章，或者新增一篇文章。</p>
          </section>

          <section v-if="passageEditorOpen || !activePassage" class="rounded-lg border border-border bg-surface p-4">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">{{ passageForm.id ? '编辑信息' : '新增阅读文章' }}</h2>
              <div class="flex flex-wrap gap-2">
                <button
                  v-if="passageForm.id"
                  type="button"
                  class="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-muted transition hover:bg-surface-2 hover:text-text"
                  :disabled="passageSaving"
                  @click="resetPassageForm"
                >
                  <Plus class="h-3.5 w-3.5" />
                  新文章
                </button>
                <button
                  type="button"
                  class="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-60"
                  :disabled="passageSaving || !passageForm.bodyText.trim()"
                  @click="savePassage"
                >
                  <Check class="h-3.5 w-3.5" />
                  {{ passageSaving ? '保存中' : '保存文章' }}
                </button>
              </div>
            </div>

            <div class="grid gap-3 lg:grid-cols-[1fr_130px_120px_140px]">
              <input
                v-model="passageForm.title"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-3 text-sm outline-none transition focus:border-primary"
                placeholder="标题，例如 2026 英语一 Text 1"
              />
              <select
                v-model="passageForm.passageType"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-2 text-sm outline-none transition focus:border-primary"
              >
                <option value="custom">自建文章</option>
                <option value="reading_a">阅读理解</option>
                <option value="cloze">完形填空</option>
                <option value="reading_b">新题型</option>
                <option value="translation">翻译材料</option>
              </select>
              <input
                v-model="passageForm.year"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-3 text-sm outline-none transition focus:border-primary"
                inputmode="numeric"
                placeholder="年份"
              />
              <select
                v-model="passageForm.examType"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-2 text-sm outline-none transition focus:border-primary"
              >
                <option value="">类型</option>
                <option value="english1">英语一</option>
                <option value="english2">英语二</option>
              </select>
            </div>
            <div class="mt-3 grid gap-3 lg:grid-cols-2">
              <input
                v-model="passageForm.sourceLabel"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-3 text-sm outline-none transition focus:border-primary"
                placeholder="来源标签，例如 考研真题"
              />
              <input
                v-model="passageForm.sourceUrl"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-3 text-sm outline-none transition focus:border-primary"
                placeholder="来源链接，可留空"
              />
            </div>
            <textarea
              v-model="passageForm.bodyText"
              :disabled="passageSaving"
              class="mt-3 min-h-[18rem] w-full resize-y rounded-md border border-border bg-bg p-3 text-sm leading-6 outline-none transition focus:border-primary"
              placeholder="粘贴一篇考研英语文章原文"
            />
          </section>
        </main>
      </section>

      <section v-else-if="isCreate" class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <main class="grid min-w-0 gap-4 lg:grid-cols-2">
          <section class="rounded-lg border border-border bg-surface p-4">
            <div class="mb-3 flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">单句新增</h2>
              <span class="text-xs text-muted tabular-nums">当前 {{ stats.active ?? total }} 句</span>
            </div>
            <SentenceEditor
              :model-value="draft"
              :saving="saving"
              :translating="translatingDraft"
              submit-label="保存句子"
              @update:model-value="draft = $event"
              @translate="translateDraft"
              @submit="createSentence"
            />
            <p v-if="error" class="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{{ error }}</p>
          </section>

          <section class="rounded-lg border border-border bg-surface p-4">
            <div class="mb-3 flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">批量导入</h2>
              <div class="flex gap-2">
                <button
                  type="button"
                  class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
                  :disabled="bulkLoading"
                  title="清空"
                  @click="resetBulkImport"
                >
                  <RotateCcw class="h-4 w-4" />
                </button>
                <button
                  type="button"
                  class="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-60"
                  :disabled="bulkLoading || !bulkSentences.length"
                  @click="submitBulkImport"
                >
                  <Upload class="h-4 w-4" />
                  {{ bulkLoading ? '导入中' : '导入' }}
                </button>
              </div>
            </div>
            <textarea
              v-model="bulkText"
              class="min-h-[24rem] w-full resize-y rounded-md border border-border bg-bg p-3 text-sm leading-6 outline-none transition focus:border-primary"
              placeholder="Sentence one&#10;&#10;Sentence two"
              @input="bulkMessage = ''"
            />
            <div class="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
              <span>
                已识别 <span class="font-semibold tabular-nums text-text">{{ bulkSentences.length }}</span> 条
              </span>
              <span v-if="bulkMessage" class="text-primary">{{ bulkMessage }}</span>
            </div>
          </section>
        </main>

        <aside class="grid content-start gap-4 xl:sticky xl:top-4">
          <section class="rounded-lg border border-border bg-surface p-4">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">最近添加</h2>
              <span class="text-xs text-muted tabular-nums">{{ sentences.length }}</span>
            </div>
            <div v-if="loading" class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
              加载中
            </div>
            <div v-else-if="sentences.length" class="mt-3 grid gap-2">
              <div
                v-for="sentence in sentences"
                :key="sentence.id"
                class="rounded-md border border-border bg-bg px-3 py-2"
              >
                <div class="flex items-center justify-between gap-3">
                  <div class="text-xs font-semibold tabular-nums text-muted">#{{ sentence.id }}</div>
                  <div class="text-[11px] text-muted">{{ focusWordCount(sentence) }} 词</div>
                </div>
                <div class="mt-1 line-clamp-2 text-sm leading-5 text-text">
                  {{ plainSentenceText(sentence.text) }}
                </div>
              </div>
            </div>
            <div v-else class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
              暂无句子
            </div>
          </section>

          <section class="rounded-lg border border-border bg-surface p-4">
            <h2 class="text-sm font-semibold text-text">语料状态</h2>
            <dl class="mt-3 grid gap-2 text-sm">
              <div class="flex items-center justify-between gap-3">
                <dt class="text-muted">有效句子</dt>
                <dd class="font-semibold tabular-nums">{{ stats.active ?? '-' }}</dd>
              </div>
              <div class="flex items-center justify-between gap-3">
                <dt class="text-muted">有音频</dt>
                <dd class="font-semibold tabular-nums">{{ stats.with_audio ?? '-' }}</dd>
              </div>
              <div class="flex items-center justify-between gap-3">
                <dt class="text-muted">跨句关联词</dt>
                <dd class="font-semibold tabular-nums">{{ stats.word_network?.cross_sentence_words ?? 0 }}</dd>
              </div>
            </dl>
          </section>
        </aside>
      </section>

      <div v-else class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <main
          :class="[
            'mx-auto grid w-full min-w-0',
            isLibrary ? 'max-w-none gap-3' : 'max-w-[980px] gap-4'
          ]"
        >
          <section v-if="isLibrary" class="overflow-hidden rounded-md border border-border bg-surface">
            <div class="hidden grid-cols-[72px_minmax(240px,1.5fr)_230px_minmax(150px,0.8fr)_minmax(170px,0.9fr)_76px] gap-3 border-b border-border bg-surface-2 px-3 py-2 text-[11px] font-medium text-muted xl:grid">
              <div>编号 / 次数</div>
              <div>句子 / 译文</div>
              <div>音频 / 音色</div>
              <div>重点词</div>
              <div>跨句关联</div>
              <div class="text-right">操作</div>
            </div>

            <article
              v-for="sentence in sentences"
              :key="sentence.id"
              class="border-b border-border last:border-b-0"
            >
              <div class="grid gap-3 px-3 py-3 xl:grid-cols-[72px_minmax(240px,1.5fr)_230px_minmax(150px,0.8fr)_minmax(170px,0.9fr)_76px] xl:items-start">
                <div class="min-w-0">
                  <div class="text-sm font-semibold tabular-nums text-text">#{{ sentence.id }}</div>
                  <div class="mt-1 flex flex-wrap gap-x-2 text-[11px] tabular-nums text-muted xl:grid xl:gap-0.5">
                    <span>整句 {{ sentence.review_count }}</span>
                    <span>单词 {{ sentence.word_play_total }}</span>
                  </div>
                  <div class="mt-1 text-[10px] text-muted">{{ compactDate(sentence.updated_at || sentence.created_at) }}</div>
                </div>

                <div class="min-w-0">
                  <div class="mb-1 text-[10px] font-medium text-muted xl:hidden">句子 / 译文</div>
                  <div class="line-clamp-2 text-sm leading-5 text-text">{{ plainSentenceText(sentence.text) }}</div>
                  <div class="mt-1 line-clamp-2 text-xs leading-5 text-muted">
                    {{ sentence.sentence_translation || '暂无译文' }}
                  </div>
                  <div v-if="sentence.ui.message" class="mt-1 text-[11px] text-primary">{{ sentence.ui.message }}</div>
                </div>

                <div class="min-w-0">
                  <div class="mb-1 text-[10px] font-medium text-muted xl:hidden">音频 / 音色</div>
                  <div class="flex min-w-0 items-start gap-2">
                    <button
                      type="button"
                      :class="sentenceAudioButtonClass(sentence)"
                      :disabled="!sentence.audio_available || !sentence.audio_url"
                      :title="sentence.ui.audioPlaying ? '暂停整句' : '播放整句'"
                      @click="toggleSentenceAudio(sentence)"
                    >
                      <Pause v-if="sentence.ui.audioPlaying" class="h-4 w-4" />
                      <Play v-else class="h-4 w-4" />
                      <span class="sr-only">{{ sentence.ui.audioPlaying ? '暂停整句' : '播放整句' }}</span>
                    </button>
                    <div class="min-w-0 text-[11px] leading-5 text-muted">
                      <div :class="sentenceAudioStatusClass(sentence)" :title="sentence.audio_error || ''">
                        {{ sentenceAudioStatusLabel(sentence) }}
                      </div>
                      <div class="truncate text-text" :title="sentenceAudioIdentity(sentence)">
                        当前 {{ sentenceAudioIdentity(sentence) }}
                      </div>
                      <div class="truncate" :title="wordAudioIdentity(sentence)">
                        单词 {{ wordAudioIdentity(sentence) }} · {{ sentence.word_audio_count ?? Object.keys(sentence.pronunciations || {}).length }}/{{ focusWordCount(sentence) }}
                      </div>
                    </div>
                  </div>
                  <select
                    class="mt-1.5 h-7 w-full rounded-md border border-border bg-bg px-1.5 text-[11px] text-text outline-none focus:border-primary disabled:opacity-50"
                    :value="sentenceAudioSelection(sentence)"
                    :disabled="audioSettingsLoading || sentence.ui.audioVoiceSaving"
                    :aria-label="`句子 ${sentence.id} 的整句音色`"
                    @change="changeSentenceAudioVoice(sentence, $event)"
                  >
                    <option value="">跟随全局 · {{ globalSentenceAudioIdentity() }}</option>
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
                        {{ audioVoiceOptionLabel(voice) }}
                      </option>
                    </optgroup>
                  </select>
                </div>

                <div class="min-w-0">
                  <div class="mb-1 flex items-center justify-between gap-2 text-[10px] font-medium text-muted xl:hidden">
                    <span>重点词</span><span>{{ focusWordCount(sentence) }}</span>
                  </div>
                  <div v-if="wordEntries(sentence).length" class="flex flex-wrap gap-1.5">
                    <button
                      v-for="entry in wordEntries(sentence).slice(0, 3)"
                      :key="entry.word"
                      type="button"
                      class="max-w-full truncate rounded border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary transition hover:bg-primary/15 disabled:opacity-50"
                      :disabled="sentence.ui.wordPlaying === entry.word"
                      :title="wordEntryTitle(entry)"
                      @click="playWord(sentence, entry.word)"
                    >
                      {{ entry.word }}
                    </button>
                    <span v-if="wordEntries(sentence).length > 3" class="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">
                      +{{ wordEntries(sentence).length - 3 }}
                    </span>
                  </div>
                  <div v-else class="text-[11px] text-muted">无重点词</div>
                </div>

                <div class="min-w-0">
                  <div class="mb-1 flex items-center justify-between gap-2 text-[10px] font-medium text-muted xl:hidden">
                    <span>跨句关联</span><span>{{ networkWords(sentence).length }}</span>
                  </div>
                  <div v-if="networkWords(sentence).length" class="grid gap-1">
                    <div
                      v-for="word in networkWords(sentence).slice(0, 3)"
                      :key="word.key"
                      class="flex min-w-0 items-center justify-between gap-2 text-[11px]"
                      :title="networkWordTitle(word)"
                    >
                      <span class="truncate font-medium text-text">{{ word.surface || word.key }}</span>
                      <span class="shrink-0 tabular-nums text-muted">{{ word.linked_sentences }}句 · 弱{{ Math.round((word.weakness || 0) * 100) }}%</span>
                    </div>
                    <div v-if="networkWords(sentence).length > 3" class="text-[10px] text-muted">
                      另有 {{ networkWords(sentence).length - 3 }} 个关联词
                    </div>
                  </div>
                  <div v-else class="text-[11px] text-muted">无跨句关联</div>
                </div>

                <div class="flex items-start justify-end gap-1 xl:grid xl:grid-cols-2">
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted transition hover:bg-surface-2 hover:text-text"
                    :title="sentence.ui.showEditor ? '收起编辑' : '编辑句子'"
                    @click="toggleEditor(sentence)"
                  >
                    <Pencil class="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-danger/40 text-danger transition hover:bg-danger-soft"
                    title="删除句子"
                    @click="deleteSentence(sentence)"
                  >
                    <Trash2 class="h-3.5 w-3.5" />
                  </button>
                </div>

                <audio
                  v-if="sentence.audio_available && sentence.audio_url"
                  :ref="el => setSentenceAudioRef(sentence.id, el)"
                  class="hidden"
                  :src="resolveSentenceAudioSrc(sentence)"
                  :preload="sentence.ui.cachedAudioUrl ? 'auto' : 'none'"
                  @play="handleSentenceAudioPlay(sentence)"
                  @pause="handleSentenceAudioPause(sentence)"
                  @ended="handleSentenceAudioEnded(sentence)"
                />

                <div v-if="sentence.ui.showEditor" class="rounded-md border border-border bg-bg p-3 xl:col-span-6">
                  <SentenceEditor
                    :model-value="sentence.ui.editDraft"
                    :saving="sentence.ui.saving"
                    :translating="sentence.ui.translating"
                    submit-label="保存修改"
                    @update:model-value="sentence.ui.editDraft = $event"
                    @translate="translateSentenceDraft(sentence)"
                    @submit="saveSentence(sentence)"
                  />
                </div>
              </div>
            </article>
          </section>

          <template v-else>
          <article
            v-for="(sentence, index) in sentences"
            :key="sentence.id"
            :ref="el => setSentenceCardRef(sentence.id, el)"
            :class="sentenceCardClass(sentence, index)"
            @click="activateSentence(index)"
          >
            <div class="flex flex-wrap items-start justify-between gap-3 border-b border-border bg-surface/80 px-4 py-3 md:px-5">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <h2 class="text-base font-semibold text-text">
                    句子 #{{ sentence.id }}
                    <span v-if="index === activeSentenceIndex && keyboardEnabled" class="ml-1 text-xs font-medium text-primary">当前</span>
                  </h2>
                  <span class="text-xs text-muted">
                    整句 <span class="font-semibold tabular-nums text-text">{{ sentence.review_count }}</span>
                  </span>
                  <span class="text-xs text-muted">
                    单词 <span class="font-semibold tabular-nums text-text">{{ sentence.word_play_total }}</span>
                  </span>
                  <span
                    class="text-xs"
                    :class="sentenceAudioStatusClass(sentence)"
                    :title="sentence.audio_error || ''"
                  >
                    {{ sentenceAudioStatusLabel(sentence) }}
                  </span>
                </div>
                <div class="mt-2 min-h-6">
                  <span v-if="sentence.ui.message" class="rounded-md bg-primary/10 px-2 py-1 text-xs text-primary">
                    {{ sentence.ui.message }}
                  </span>
                  <span v-else-if="sentence.ui.status" class="rounded-md bg-surface-2 px-2 py-1 text-xs text-muted">
                    {{ sentence.ui.status }}
                  </span>
                </div>
              </div>

              <div class="flex flex-wrap justify-end gap-2">
                <div v-if="sentence.audio_available && sentence.audio_url" class="grid justify-items-center gap-1">
                  <button
                    type="button"
                    :class="sentenceAudioButtonClass(sentence)"
                    :title="sentence.ui.audioPlaying ? '暂停整句' : '播放整句'"
                    @click="toggleSentenceAudio(sentence)"
                  >
                    <Pause v-if="sentence.ui.audioPlaying" class="h-4 w-4" />
                    <Play v-else class="h-4 w-4" />
                    <span class="sr-only">{{ sentence.ui.audioPlaying ? '暂停整句' : '播放整句' }}</span>
                  </button>
                </div>
                <div class="grid justify-items-center gap-1">
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
                    :aria-busy="sentence.ui.reviewing"
                    @click="markReviewed(sentence)"
                  >
                    <Check class="h-4 w-4" />
                    {{ sentence.ui.reviewPending ? `+1复习 · 待记 ${sentence.ui.reviewPending}` : '+1复习' }}
                  </button>
                </div>
                <button
                  type="button"
                  class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
                  @click="toggleEditor(sentence)"
                >
                  <Pencil class="h-4 w-4" />
                  {{ sentence.ui.showEditor ? '收起编辑' : '编辑' }}
                </button>
                <button
                  v-if="isLibrary"
                  type="button"
                  class="inline-flex h-9 items-center gap-1.5 rounded-md border border-danger/40 px-3 text-sm text-danger transition hover:bg-danger-soft"
                  @click="deleteSentence(sentence)"
                >
                  <Trash2 class="h-4 w-4" />
                  删除
                </button>
              </div>
            </div>

            <div v-if="sentence.ui.showEditor" class="mx-4 mt-4 rounded-md border border-border bg-surface p-3 md:mx-5">
              <SentenceEditor
                :model-value="sentence.ui.editDraft"
                :saving="sentence.ui.saving"
                :translating="sentence.ui.translating"
                submit-label="保存修改"
                @update:model-value="sentence.ui.editDraft = $event"
                @translate="translateSentenceDraft(sentence)"
                @submit="saveSentence(sentence)"
              />
            </div>

            <div class="sentence-reader px-5 py-7 text-[18px] leading-[2] text-text md:px-8 md:py-8 md:text-[20px] md:leading-[2.05]">
              <template v-for="(token, index) in sentenceTokens(sentence.text)" :key="index">
                <button
                  v-if="token.focus"
                  type="button"
                  class="rounded-md bg-primary/10 px-1.5 font-semibold text-primary underline-offset-4 transition hover:bg-primary/15 hover:underline"
                  @click="playWord(sentence, token.text)"
                >{{ token.text }}</button>
                <span v-else class="whitespace-pre-wrap">{{ token.text }}</span>
              </template>
            </div>

            <div v-if="networkWords(sentence).length" class="flex flex-wrap gap-2 px-5 pb-5 md:px-8">
              <span
                v-for="word in networkWords(sentence)"
                :key="word.key"
                class="inline-flex items-center gap-1.5 rounded-md border border-primary/20 bg-primary/10 px-2 py-1 text-xs text-primary"
              >
                <span class="font-semibold">{{ word.surface || word.key }}</span>
                <span class="text-muted">{{ word.linked_sentences }}句</span>
                <span class="tabular-nums text-muted">{{ Math.round((word.weakness || 0) * 100) }}%</span>
              </span>
            </div>

            <audio
              v-if="sentence.audio_available && sentence.audio_url"
              :ref="el => setSentenceAudioRef(sentence.id, el)"
              class="hidden"
              :src="resolveSentenceAudioSrc(sentence)"
              :preload="sentence.ui.cachedAudioUrl ? 'auto' : 'none'"
              @play="handleSentenceAudioPlay(sentence)"
              @pause="handleSentenceAudioPause(sentence)"
              @ended="handleSentenceAudioEnded(sentence)"
            />

            <div class="grid gap-3 border-t border-border bg-surface/60 px-4 py-4 md:px-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
              <section class="rounded-md border border-border bg-bg p-3">
                <div class="flex items-center justify-between gap-3">
                  <h3 class="text-xs font-semibold text-muted">整句翻译</h3>
                  <div class="grid justify-items-center gap-1">
                    <button
                      type="button"
                      class="inline-flex h-8 items-center gap-1 rounded-md border border-border px-2.5 text-xs text-muted transition hover:bg-bg hover:text-text disabled:opacity-50"
                      :disabled="!hasTranslationContent(sentence)"
                      @click="sentence.ui.showTranslation = !sentence.ui.showTranslation"
                    >
                      <Eye class="h-3.5 w-3.5" />
                      {{ sentence.ui.showTranslation ? '隐藏' : '显示' }}
                    </button>
                  </div>
                </div>
                <div v-if="sentence.ui.showTranslation && segmentPairs(sentence).length" class="sentence-segments mt-3 space-y-3">
                  <div class="sentence-segment-en text-sm leading-7 text-text">
                    <template v-for="(segment, index) in sentenceSegmentSources(sentence)" :key="`${sentence.id}-source-${index}`">
                      <span>{{ segment }}</span>
                      <span v-if="index < sentenceSegmentSources(sentence).length - 1" class="font-semibold text-primary"> / </span>
                    </template>
                  </div>
                  <div class="sentence-segment-zh text-sm leading-7 text-muted">
                    <template v-for="(segment, index) in sentenceSegmentTargets(sentence)" :key="`${sentence.id}-target-${index}`">
                      <span>{{ segment }}</span>
                      <span v-if="index < sentenceSegmentTargets(sentence).length - 1" class="font-semibold text-primary"> / </span>
                    </template>
                  </div>
                </div>
                <div v-else-if="sentence.ui.showTranslation && sentence.sentence_translation" class="sentence-translation mt-2 whitespace-pre-wrap text-sm leading-6 text-text">
                  {{ sentence.sentence_translation }}
                </div>
                <div v-else class="mt-2 text-sm text-muted">未显示</div>
              </section>

              <section class="rounded-md border border-dashed border-border bg-bg p-3">
                <div class="mb-2 flex items-center justify-between gap-2">
                  <h3 class="text-xs font-semibold text-muted">重点词</h3>
                  <div class="text-[11px] text-muted tabular-nums">{{ wordEntries(sentence).length }}</div>
                </div>
                <div v-if="wordEntries(sentence).length" class="flex flex-wrap gap-2">
                  <span
                    v-for="entry in wordEntries(sentence)"
                    :key="entry.word"
                    class="inline-flex max-w-full items-center gap-2 rounded-md border border-primary/25 bg-primary/10 px-2 py-1.5 text-sm text-primary"
                  >
                    <span class="min-w-0 break-words">
                      <span class="font-semibold">{{ entry.word }}</span>
                      <span class="text-muted"> = {{ entry.meaning || '未填释义' }}</span>
                      <span v-if="entry.tip" class="text-muted"> · {{ entry.tip }}</span>
                      <span class="ml-1 text-xs text-muted tabular-nums">({{ entry.count }})</span>
                    </span>
                    <span class="grid shrink-0 justify-items-center gap-1">
                      <button
                        type="button"
                        class="inline-flex h-7 w-8 items-center justify-center rounded-md border border-primary/30 text-primary transition hover:bg-primary/10 disabled:opacity-50"
                        :disabled="sentence.ui.wordPlaying === entry.word"
                        :title="entry.audio ? '播放读音' : '无读音'"
                        @click="playWord(sentence, entry.word)"
                      >
                        <Volume2 class="h-4 w-4" />
                      </button>
                    </span>
                  </span>
                </div>
                <div v-else class="text-sm text-muted">暂无重点词</div>
              </section>
            </div>
          </article>
          </template>

          <div v-if="loading" class="rounded-lg border border-border bg-surface p-6 text-center text-sm text-muted">
            加载中
          </div>
          <div v-else-if="!sentences.length" class="rounded-lg border border-border bg-surface p-6 text-center text-sm text-muted">
            没有匹配的句子
          </div>

          <nav class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface p-3 text-sm">
            <button
              type="button"
              class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-40"
              :disabled="page <= 1 || loading"
              @click="prevPage"
            >
              <ChevronLeft class="h-4 w-4" />
              上一页
            </button>
            <div class="text-muted">
              第 <span class="font-semibold tabular-nums text-text">{{ page }}</span> /
              <span class="font-semibold tabular-nums text-text">{{ pageCount }}</span> 页，
              共 <span class="font-semibold tabular-nums text-text">{{ total }}</span> 条
            </div>
            <button
              type="button"
              class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-40"
              :disabled="page >= pageCount || loading"
              @click="nextPage"
            >
              下一页
              <ChevronRight class="h-4 w-4" />
            </button>
          </nav>
        </main>

        <aside class="order-first grid content-start gap-4 xl:order-last xl:sticky xl:top-4">
          <section class="rounded-lg border border-border bg-surface p-4">
            <h2 class="text-sm font-semibold text-text">筛选</h2>
            <div class="mt-3 grid gap-2">
              <div class="relative min-w-0">
                <Search class="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" />
                <input
                  v-model="searchInput"
                  type="search"
                  class="h-9 w-full rounded-md border border-border bg-bg py-2 pl-9 pr-3 text-sm outline-none transition focus:border-primary"
                  placeholder="搜索句子 / 释义 / 单词"
                  @keydown.enter.prevent="applySearch"
                />
              </div>
              <div class="grid grid-cols-[minmax(0,1fr)_90px] gap-2">
                <select
                  v-model="sort"
                  class="h-9 min-w-0 rounded-md border border-border bg-bg px-2 text-sm outline-none transition focus:border-primary"
                  @change="reloadFirstPage"
                >
                  <option value="smart">智能复习</option>
                  <option value="least-reviewed">最少复习</option>
                  <option value="latest">最新添加</option>
                  <option value="oldest">最早添加</option>
                  <option value="id-asc">编号升序</option>
                  <option value="id-desc">编号降序</option>
                  <option value="missing-audio">缺音频</option>
                </select>
                <select
                  v-model="pageSize"
                  class="h-9 rounded-md border border-border bg-bg px-2 text-sm outline-none transition focus:border-primary"
                  @change="reloadFirstPage"
                >
                  <option v-for="option in pageSizeOptions" :key="option" :value="option">{{ option }}</option>
                </select>
              </div>
              <button
                type="button"
                class="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-60"
                :disabled="loading"
                @click="applySearch"
              >
                <Search class="h-4 w-4" />
                应用
              </button>
            </div>
            <p v-if="error" class="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{{ error }}</p>
          </section>

          <section v-if="!isLibrary" class="rounded-lg border border-border bg-surface p-4">
            <div class="flex items-center justify-between gap-2">
              <h2 class="text-sm font-semibold text-text">复习热力</h2>
              <span class="text-xs text-muted">近 {{ heatmap?.window_days ?? 119 }} 天</span>
            </div>
            <div class="mt-3 overflow-x-auto pb-1">
              <div
                class="grid grid-flow-col grid-rows-7 gap-1"
                :style="{ gridTemplateColumns: `repeat(${heatmapColumns}, 0.75rem)` }"
              >
                <div
                  v-for="(day, index) in heatmapCells"
                  :key="day?.date || `rail-${index}`"
                  :class="heatCellClass(day)"
                  :title="heatCellTitle(day)"
                />
              </div>
            </div>
            <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
              <span>活跃 {{ heatmap?.active_days ?? 0 }} 天</span>
              <span>窗口 {{ heatmap?.total_reviews ?? 0 }} 次</span>
              <span v-if="legacyReviewTotal">旧累计 {{ legacyReviewTotal }} 次</span>
            </div>
          </section>

          <section v-if="isLibrary" class="rounded-lg border border-border bg-surface p-4">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">新增</h2>
              <button
                type="button"
                class="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-muted transition hover:bg-surface-2 hover:text-text"
                @click="createOpen = !createOpen"
              >
                <Plus class="h-3.5 w-3.5" />
                {{ createOpen ? '收起' : '单句' }}
              </button>
            </div>
            <div v-if="createOpen" class="mt-3 rounded-md border border-border bg-bg p-3">
              <SentenceEditor
                :model-value="draft"
                :saving="saving"
                :translating="translatingDraft"
                submit-label="保存"
                @update:model-value="draft = $event"
                @translate="translateDraft"
                @submit="createSentence"
              />
            </div>

            <div class="mt-3 border-t border-border pt-3">
              <div class="mb-2 flex items-center justify-between gap-3">
                <h3 class="text-xs font-semibold text-muted">批量导入</h3>
                <div class="flex gap-2">
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
                    :disabled="bulkLoading"
                    title="清空"
                    @click="resetBulkImport"
                  >
                    <RotateCcw class="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground disabled:opacity-60"
                    :disabled="bulkLoading || !bulkSentences.length"
                    title="导入"
                    @click="submitBulkImport"
                  >
                    <Upload class="h-4 w-4" />
                  </button>
                </div>
              </div>
              <textarea
                v-model="bulkText"
                class="min-h-32 w-full resize-y rounded-md border border-border bg-bg p-3 text-sm leading-6 outline-none transition focus:border-primary"
                placeholder="Sentence one&#10;&#10;Sentence two"
                @input="bulkMessage = ''"
              />
              <div v-if="bulkSentences.length" class="mt-2 text-xs text-muted">
                已识别 <span class="font-semibold tabular-nums text-text">{{ bulkSentences.length }}</span> 条
              </div>
              <p v-if="bulkMessage" class="mt-2 text-sm text-primary">{{ bulkMessage }}</p>
            </div>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Bold,
  BookMarked,
  BookOpenCheck,
  Check,
  ChevronLeft,
  ChevronRight,
  Eye,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  Upload,
  Volume2
} from '@lucide/vue'
import { englishApi } from './api'
import SentenceEditor from './SentenceEditor.vue'
import {
  candidateCount,
  markedWordCount,
  passageCandidates
} from './passageMarkdown'
import { useEnglishAudio } from './useEnglishAudio'
import { usePassageEditor } from './usePassageEditor'
import { useEnglishSentenceList } from './useEnglishSentenceList'

const props = defineProps({
  mode: { type: String, default: 'review' }
})
defineEmits(['goPassages', 'goReview'])


const isLibrary = computed(() => props.mode === 'library')
const isCreate = computed(() => props.mode === 'create')
const isStats = computed(() => props.mode === 'stats')
const isPassages = computed(() => props.mode === 'passages')
const isReview = computed(() => !isLibrary.value && !isCreate.value && !isStats.value && !isPassages.value)
const modeLabel = computed(() => {
  if (isPassages.value) return '阅读'
  if (isCreate.value) return '新增'
  if (isLibrary.value) return '句库'
  if (isStats.value) return '统计'
  return '复习'
})
const pageTitle = computed(() => {
  if (isPassages.value) return '每日阅读'
  if (isCreate.value) return '新增语料'
  if (isLibrary.value) return '句库管理'
  if (isStats.value) return '复习统计'
  return '智能复习队列'
})

let passageControls
let audioControls
let desktopQuery = null
let keyboardReviewPromise = null
let voicePreviewAudio = null

const activeSentenceIndex = ref(0)
const desktopKeyboardAvailable = ref(false)
const audioSettings = ref({ global: {}, voices: [], sentences: {} })
const selectedGlobalVoice = ref('')
const audioSettingsLoading = ref(false)
const audioSettingsSaving = ref(false)
const audioSettingsApplying = ref(false)
const audioSettingsMessage = ref('')
const audioSettingsError = ref('')
const previewLoadingVoice = ref('')
const previewPlayingVoice = ref('')
const voiceProviderFilter = ref('kokoro')
const audioVoiceGroups = computed(() => {
  const groups = []
  for (const voice of audioSettings.value.voices || []) {
    const key = voice.provider === 'edge'
      ? 'edge'
      : `${voice.accent || '其他'}-${voice.gender || '音色'}`
    let group = groups.find(item => item.key === key)
    if (!group) {
      group = {
        key,
        provider: voice.provider,
        label: voice.provider === 'edge'
          ? 'Edge TTS'
          : `Kokoro · ${voice.accent || ''}${voice.gender || ''}`,
        voices: []
      }
      groups.push(group)
    }
    group.voices.push(voice)
  }
  return groups
})
const filteredAudioVoiceGroups = computed(() => (
  audioVoiceGroups.value.filter(group => group.provider === voiceProviderFilter.value)
))
const kokoroVoiceCount = computed(() => (
  (audioSettings.value.voices || []).filter(voice => voice.provider === 'kokoro').length
))
const edgeVoiceCount = computed(() => (
  (audioSettings.value.voices || []).filter(voice => voice.provider === 'edge').length
))
const sentenceCardRefs = new Map()
const FOCUS_WORD_KEY_INDEX = Object.freeze({ q: 0, e: 1, r: 2, f: 3, g: 4 })
const keyboardEnabled = computed(() => (
  desktopKeyboardAvailable.value
  && !isCreate.value
  && !isStats.value
  && !isPassages.value
  && !isLibrary.value
))

const {
  sentences,
  stats,
  heatmap,
  error,
  loading,
  saving,
  translatingDraft,
  page,
  pageSize,
  pageSizeOptions,
  total,
  searchInput,
  sort,
  createOpen,
  draft,
  bulkText,
  bulkLoading,
  bulkMessage,
  reviewRound,
  pageCount,
  weakNetworkWords,
  legacyReviewTotal,
  heatmapCells,
  heatmapColumns,
  bulkSentences,
  sentenceTokens,
  plainSentenceText,
  hasTranslationContent,
  segmentPairs,
  sentenceSegmentSources,
  sentenceSegmentTargets,
  focusWordCount,
  wordEntries,
  networkWords,
  heatCellClass,
  heatCellTitle,
  load,
  refreshActivity,
  reloadFirstPage,
  applySearch,
  prevPage,
  nextPage,
  createSentence,
  translateDraft,
  resetBulkImport,
  submitBulkImport,
  toggleEditor,
  translateSentenceDraft,
  saveSentence,
  deleteSentence,
  updateSentenceInList,
  markReviewed,
  resetForModeChange
} = useEnglishSentenceList({
  isCreate: () => isCreate.value,
  isStats: () => isStats.value,
  isPassages: () => isPassages.value,
  isReview: () => isReview.value,
  loadPassages: (...args) => passageControls?.loadPassages?.(...args),
  audioControls: () => audioControls,
  onSentencesLoaded: (items, round) => {
    const nextIndex = round ? items.findIndex(item => !item.review_round_item_completed) : 0
    activeSentenceIndex.value = nextIndex >= 0 ? nextIndex : 0
  }
})

function applyListDefaultsForMode() {
  if (isLibrary.value) {
    sort.value = 'id-desc'
    pageSize.value = 40
  } else if (isReview.value) {
    sort.value = 'smart'
    pageSize.value = 20
  }
}

const activeSentence = computed(() => sentences.value[activeSentenceIndex.value] || sentences.value[0] || null)

passageControls = usePassageEditor({
  refreshActivity
})

const {
  passages,
  todayPassages,
  activePassage,
  passageTotal,
  passageLoading,
  passageSaving,
  passageSyncing,
  passageCompleting,
  passageMessage,
  passageError,
  selectedCandidateIndexes,
  passageTypeFilter,
  passageExamFilter,
  passageYearFilter,
  passageSearchInput,
  passagePage,
  passagePageCount,
  passageTypeFilters,
  passageForm,
  passageEditorOpen,
  activePassagePanel,
  passageAnnotator,
  passageAnnotatorHtml,
  passageDirty,
  passageTitle,
  passageStatusLabel,
  examTypeLabel,
  passageTypeLabel,
  passageActionLabel,
  togglePassageBold,
  handlePassageAnnotatorInput,
  handlePassageAnnotatorKeydown,
  handlePassageAnnotatorPaste,
  flushPassageAutosave,
  loadPassages,
  setPassageTypeFilter,
  applyPassageFilters,
  changePassagePage,
  resetPassageForm,
  selectPassage,
  startPassage,
  savePassage,
  savePassageAnnotations,
  syncSelectedCandidates,
  completeActivePassage,
  deleteActivePassage
} = passageControls

defineExpose({
  flushPendingChanges: flushPassageAutosave,
  hasPendingChanges: () => passageDirty.value
})

audioControls = useEnglishAudio(sentences, {
  shouldSkipStatusRefresh: () => isPassages.value || isStats.value,
  refreshAudioStatus: () => load(),
  updateSentenceInList,
  refreshActivity,
  markReviewed,
  reloadRound: reloadFirstPage
})

const {
  scheduleAudioStatusRefresh,
  resolveSentenceAudioSrc,
  setSentenceAudioRef,
  toggleSentenceAudio,
  playWord,
  handleSentenceAudioEnded,
  handleSentenceAudioPlay,
  handleSentenceAudioPause,
  resetPreloadWindow,
  schedulePreloadWindow,
  advancePreloadWindowFromSentence,
  disposeSentenceCaches,
  disposeAudioResources
} = audioControls

function setSentenceCardRef(sentenceId, el) {
  const id = Number(sentenceId)
  if (!id) return
  if (el) sentenceCardRefs.set(id, el)
  else sentenceCardRefs.delete(id)
}

function sentenceCardClass(sentence, index) {
  const active = keyboardEnabled.value && index === activeSentenceIndex.value
  return [
    'overflow-hidden rounded-lg border bg-bg shadow-sm transition',
    active ? 'border-primary shadow-md ring-1 ring-primary/30' : 'border-border'
  ]
}

function activateSentence(index, options = {}) {
  const nextIndex = Math.max(0, Math.min(Number(index) || 0, Math.max(sentences.value.length - 1, 0)))
  activeSentenceIndex.value = nextIndex
  if (options.scroll) scrollActiveSentenceIntoView()
}

async function scrollActiveSentenceIntoView() {
  await nextTick()
  const sentence = activeSentence.value
  const el = sentence ? sentenceCardRefs.get(Number(sentence.id)) : null
  el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
}

async function moveActiveSentence(delta) {
  if (!sentences.value.length) return
  const nextIndex = activeSentenceIndex.value + delta
  if (nextIndex >= 0 && nextIndex < sentences.value.length) {
    activateSentence(nextIndex, { scroll: true })
    return
  }
  if (nextIndex >= sentences.value.length && page.value < pageCount.value && !loading.value) {
    await nextPage()
    activateSentence(0, { scroll: true })
    return
  }
  if (nextIndex < 0 && page.value > 1 && !loading.value) {
    await prevPage()
    activateSentence(Math.max(sentences.value.length - 1, 0), { scroll: true })
  }
}

async function markActiveReviewedAndNext() {
  if (keyboardReviewPromise) return keyboardReviewPromise
  const sentence = activeSentence.value
  if (!sentence || sentence.ui.reviewing) return false
  const sentenceId = Number(sentence.id)
  const pendingReview = (async () => {
    const updated = await markReviewed(sentence)
    if (!updated) return false
    if (updated.review_round_completed) {
      await reloadFirstPage()
      activateSentence(0, { scroll: true })
      return true
    }
    if (Number(activeSentence.value?.id) === sentenceId) {
      await moveActiveSentence(1)
    }
    return true
  })()
  keyboardReviewPromise = pendingReview
  try {
    return await pendingReview
  } finally {
    if (keyboardReviewPromise === pendingReview) keyboardReviewPromise = null
  }
}

function closeActiveSentencePanels() {
  const sentence = activeSentence.value
  if (!sentence) return
  sentence.ui.showTranslation = false
  if (sentence.ui.showEditor) toggleEditor(sentence)
}

function toggleActiveTranslation() {
  const sentence = activeSentence.value
  if (!sentence || !hasTranslationContent(sentence)) return
  sentence.ui.showTranslation = !sentence.ui.showTranslation
}

function playFocusWordAt(index) {
  const sentence = activeSentence.value
  if (!sentence) return
  const entries = wordEntries(sentence)
  const entry = entries[index]
  if (!entry) return
  playWord(sentence, entry.word)
}

function focusWordIndexForKey(key) {
  if (/^[1-9]$/.test(key)) return Number(key) - 1
  return FOCUS_WORD_KEY_INDEX[key] ?? -1
}

function isKeyboardInputTarget(target) {
  const el = target instanceof Element ? target : null
  if (!el) return false
  const tag = el.tagName?.toLowerCase()
  return (
    tag === 'input'
    || tag === 'textarea'
    || tag === 'select'
    || tag === 'button'
    || tag === 'a'
    || tag === 'summary'
    || el.isContentEditable
    || el.closest?.(
      'input, textarea, select, button, a[href], summary, '
      + '[contenteditable="true"], [role="textbox"], [role="button"], [role="link"], '
      + '[role="menuitem"], [role="option"], [role="switch"], [role="checkbox"], [role="radio"]'
    )
  )
}

function updateDesktopKeyboardAvailability() {
  desktopKeyboardAvailable.value = Boolean(desktopQuery?.matches)
}

function handleEnglishKeyboard(event) {
  if (!keyboardEnabled.value || event.defaultPrevented || isKeyboardInputTarget(event.target)) return
  if (event.ctrlKey || event.metaKey || event.altKey) return
  if (!sentences.value.length) return

  const key = String(event.key || '').toLowerCase()
  const focusWordIndex = focusWordIndexForKey(key)
  const isShortcut = (
    event.code === 'Space'
    || key === 'enter'
    || key === 'j'
    || key === 'arrowdown'
    || key === 'arrowup'
    || key === 's'
    || key === 'w'
    || key === 't'
    || key === 'escape'
    || focusWordIndex >= 0
  )
  if (!isShortcut || event.isComposing) return
  if (event.repeat || keyboardReviewPromise) {
    event.preventDefault()
    return
  }

  if (event.code === 'Space') {
    event.preventDefault()
    if (activeSentence.value?.audio_available && activeSentence.value?.audio_url) {
      toggleSentenceAudio(activeSentence.value)
    }
    return
  }

  if (key === 'enter' || key === 'j') {
    event.preventDefault()
    void markActiveReviewedAndNext()
    return
  }
  if (key === 'arrowdown' || key === 's') {
    event.preventDefault()
    moveActiveSentence(1)
    return
  }
  if (key === 'arrowup' || key === 'w') {
    event.preventDefault()
    moveActiveSentence(-1)
    return
  }
  if (key === 't') {
    event.preventDefault()
    toggleActiveTranslation()
    return
  }
  if (key === 'escape') {
    event.preventDefault()
    closeActiveSentencePanels()
    return
  }
  if (focusWordIndex >= 0) {
    event.preventDefault()
    playFocusWordAt(focusWordIndex)
  }
}

function installDesktopKeyboardDetection() {
  if (typeof window === 'undefined' || !window.matchMedia) return
  desktopQuery = window.matchMedia('(min-width: 768px)')
  updateDesktopKeyboardAvailability()
  if (desktopQuery.addEventListener) {
    desktopQuery.addEventListener('change', updateDesktopKeyboardAvailability)
  } else {
    desktopQuery.addListener?.(updateDesktopKeyboardAvailability)
  }
  window.addEventListener('resize', updateDesktopKeyboardAvailability)
}

function removeDesktopKeyboardDetection() {
  if (!desktopQuery) return
  if (desktopQuery.removeEventListener) {
    desktopQuery.removeEventListener('change', updateDesktopKeyboardAvailability)
  } else {
    desktopQuery.removeListener?.(updateDesktopKeyboardAvailability)
  }
  window.removeEventListener('resize', updateDesktopKeyboardAvailability)
  desktopQuery = null
}

function audioVoiceKey(provider, voice) {
  const cleanProvider = String(provider || '').trim().toLowerCase()
  const cleanVoice = String(voice || '').trim()
  return cleanProvider && cleanVoice ? `${cleanProvider}|${cleanVoice}` : ''
}

function audioVoiceFromKey(value) {
  const [provider, ...voiceParts] = String(value || '').split('|')
  const voice = voiceParts.join('|')
  return { provider, voice }
}

function applyAudioSettingsResult(result) {
  audioSettings.value = result || { global: {}, voices: [], sentences: {} }
  selectedGlobalVoice.value = audioVoiceKey(
    audioSettings.value.global?.provider,
    audioSettings.value.global?.voice
  )
}

async function loadAudioSettings({ quiet = false } = {}) {
  if (!quiet) audioSettingsLoading.value = true
  audioSettingsError.value = ''
  try {
    applyAudioSettingsResult(await englishApi.audioSettings())
  } catch (err) {
    audioSettingsError.value = err?.message || '音色设置加载失败'
  } finally {
    audioSettingsLoading.value = false
  }
}

async function saveGlobalAudioSettings() {
  const selection = audioVoiceFromKey(selectedGlobalVoice.value)
  if (!selection.provider || !selection.voice || audioSettingsSaving.value) return
  audioSettingsSaving.value = true
  audioSettingsMessage.value = ''
  audioSettingsError.value = ''
  try {
    const result = await englishApi.updateAudioSettings(selection)
    applyAudioSettingsResult(result)
    audioSettingsMessage.value = '全局默认音色已保存'
  } catch (err) {
    audioSettingsError.value = err?.message || '全局音色保存失败'
  } finally {
    audioSettingsSaving.value = false
  }
}

async function applyGlobalAudioSettings() {
  const count = Number(audioSettings.value.sentences?.following_global || 0)
  const selection = audioVoiceFromKey(selectedGlobalVoice.value)
  if (audioSettingsApplying.value || !selection.provider || !selection.voice) return
  if (!window.confirm(`将全局音色应用到现有的 ${count} 个未单独指定音色的句子吗？`)) return
  audioSettingsApplying.value = true
  audioSettingsMessage.value = ''
  audioSettingsError.value = ''
  try {
    const currentKey = audioVoiceKey(
      audioSettings.value.global?.provider,
      audioSettings.value.global?.voice
    )
    if (selectedGlobalVoice.value !== currentKey) {
      applyAudioSettingsResult(await englishApi.updateAudioSettings(selection))
    }
    const result = await englishApi.applyAudioSettings()
    audioSettingsMessage.value = result.queued
      ? `已排队生成 ${result.queued} 条整句音频`
      : '现有句子已经使用该音色'
    await loadAudioSettings({ quiet: true })
  } catch (err) {
    audioSettingsError.value = err?.message || '应用全局音色失败'
  } finally {
    audioSettingsApplying.value = false
  }
}

function stopVoicePreview() {
  if (voicePreviewAudio) {
    voicePreviewAudio.pause()
    voicePreviewAudio.src = ''
    voicePreviewAudio = null
  }
  previewPlayingVoice.value = ''
}

async function playVoicePreview(voice) {
  const key = audioVoiceKey(voice?.provider, voice?.voice)
  if (!key || !voice?.available) return
  if (previewPlayingVoice.value === key) {
    stopVoicePreview()
    return
  }
  stopVoicePreview()
  previewLoadingVoice.value = key
  audioSettingsMessage.value = ''
  audioSettingsError.value = ''
  try {
    const result = await englishApi.createAudioPreview({
      provider: voice.provider,
      voice: voice.voice
    })
    const audio = new Audio(result.audio_url)
    voicePreviewAudio = audio
    audio.addEventListener('play', () => {
      if (voicePreviewAudio === audio) previewPlayingVoice.value = key
    })
    audio.addEventListener('ended', () => {
      if (voicePreviewAudio === audio) stopVoicePreview()
    })
    audio.addEventListener('error', () => {
      if (voicePreviewAudio !== audio) return
      stopVoicePreview()
      audioSettingsError.value = '试听音频播放失败'
    })
    await audio.play()
  } catch (err) {
    stopVoicePreview()
    audioSettingsError.value = err?.message || '音色试听失败'
  } finally {
    if (previewLoadingVoice.value === key) previewLoadingVoice.value = ''
  }
}

function sentenceAudioSelection(sentence) {
  if (sentence?.audio_uses_global !== false) return ''
  return audioVoiceKey(sentence?.audio_effective_provider, sentence?.audio_effective_voice)
}

async function changeSentenceAudioVoice(sentence, event) {
  if (!sentence || sentence.ui.audioVoiceSaving) return
  const select = event?.target
  const value = String(select?.value || '')
  const previousValue = sentenceAudioSelection(sentence)
  const selection = audioVoiceFromKey(value)
  sentence.ui.audioVoiceSaving = true
  sentence.ui.message = ''
  try {
    const updated = await englishApi.updateSentenceAudioSettings(
      sentence.id,
      value
        ? { provider: selection.provider, voice: selection.voice, use_global: false }
        : { use_global: true }
    )
    const decorated = updateSentenceInList(updated, sentence)
    decorated.ui.message = updated.audio_needs_regeneration
      ? '音色已指定，正在生成整句音频'
      : '音色设置已更新'
    if (updated.audio_needs_regeneration) scheduleAudioStatusRefresh(25000)
  } catch (err) {
    sentence.ui.message = err?.message || '音色设置失败'
    if (select) select.value = previousValue
  } finally {
    sentence.ui.audioVoiceSaving = false
  }
}

function compactDate(value) {
  const text = String(value || '').trim()
  return text ? text.slice(0, 10) : '-'
}

function audioProviderLabel(value) {
  const provider = String(value || '').trim().toLowerCase()
  if (provider === 'kokoro') return 'Kokoro'
  if (provider === 'edge') return 'Edge TTS'
  return provider || '未标注'
}

function audioVoiceOptionLabel(voice) {
  return `${voice.name} · ${voice.voice}`
}

function voiceProviderFilterButtonClass(provider) {
  return [
    'h-8 rounded px-3 text-xs font-medium transition',
    voiceProviderFilter.value === provider
      ? 'bg-primary text-primary-foreground'
      : 'text-muted hover:bg-surface-2 hover:text-text'
  ]
}

function globalSentenceAudioIdentity() {
  const provider = audioProviderLabel(audioSettings.value.global?.provider)
  const voice = String(audioSettings.value.global?.voice || '').trim()
  return voice ? `${provider} · ${voice}` : provider
}

function sentenceAudioIdentity(sentence) {
  const provider = audioProviderLabel(sentence?.audio_provider)
  const voice = String(sentence?.audio_voice || '').trim()
  return voice ? `${provider} · ${voice}` : provider
}

function wordAudioIdentity(sentence) {
  const provider = audioProviderLabel(sentence?.word_audio_provider || 'edge')
  const voice = String(sentence?.word_audio_voice || '').trim()
  return voice ? `${provider} · ${voice}` : provider
}

function wordEntryTitle(entry) {
  return [entry?.word, entry?.meaning, entry?.tip].filter(Boolean).join(' · ')
}

function networkWordTitle(word) {
  const surface = word?.surface || word?.key || '关联词'
  const linked = Number(word?.linked_sentences || 0)
  const weakness = Math.round(Number(word?.weakness || 0) * 100)
  return `${surface} · 关联 ${linked} 个句子 · 薄弱度 ${weakness}%`
}

function sentenceAudioButtonClass(sentence) {
  return [
    'inline-flex h-9 w-9 items-center justify-center rounded-md border transition disabled:opacity-50',
    sentence?.ui?.audioPlaying
      ? 'border-primary bg-primary text-primary-foreground'
      : 'border-border text-muted hover:bg-surface-2 hover:text-text'
  ]
}

function sentenceAudioStatusLabel(sentence) {
  const status = String(sentence?.audio_status || '').toLowerCase()
  if (sentence?.audio_available && status === 'ready') return '有音频'
  if (status === 'pending') return '待生成音频'
  if (status === 'failed') return '生成失败'
  return '缺音频'
}

function sentenceAudioStatusClass(sentence) {
  const status = String(sentence?.audio_status || '').toLowerCase()
  if (sentence?.audio_available && status === 'ready') return 'text-success'
  if (status === 'failed') return 'text-danger'
  return 'text-warning'
}

watch(() => props.mode, async () => {
  resetForModeChange()
  activeSentenceIndex.value = 0
  applyListDefaultsForMode()
  await Promise.all([load(), loadAudioSettings({ quiet: true })])
})

watch(sentences, items => {
  if (!items.length) {
    activeSentenceIndex.value = 0
    return
  }
  if (activeSentenceIndex.value >= items.length) {
    activeSentenceIndex.value = items.length - 1
  }
})

onMounted(() => {
  installDesktopKeyboardDetection()
  window.addEventListener('keydown', handleEnglishKeyboard)
  applyListDefaultsForMode()
  load()
  loadAudioSettings()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleEnglishKeyboard)
  removeDesktopKeyboardDetection()
  stopVoicePreview()
  disposeAudioResources()
})
</script>

<style scoped>
.passage-annotator,
.sentence-reader,
.sentence-segment-en,
.sentence-translation {
  --english-reading-font: Georgia, "Arial Hebrew", "Noto Sans Hebrew", "Times New Roman",
    Times, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "PingFang TC",
    "Microsoft JhengHei", "Noto Sans CJK TC", "Hiragino Sans", "Yu Gothic", Meiryo,
    "Noto Sans CJK JP", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans CJK KR", serif;
}

.passage-annotator {
  font-family: var(--english-reading-font);
  letter-spacing: 0;
}

.sentence-reader {
  font-family: var(--english-reading-font);
  letter-spacing: 0;
}

.sentence-translation {
  font-family: var(--english-reading-font);
  letter-spacing: 0;
}

.sentence-segment-en {
  font-family: var(--english-reading-font);
  letter-spacing: 0;
}

.sentence-reader button {
  font-family: inherit;
}

.passage-annotator :deep(p) {
  margin: 0 0 1.45rem;
  text-wrap: pretty;
}

.passage-annotator :deep(p:last-child) {
  margin-bottom: 0;
}

.passage-annotator :deep(strong),
.passage-annotator :deep(b) {
  border-radius: 0.25rem;
  background: color-mix(in srgb, var(--primary, #b85c38) 12%, transparent);
  padding: 0.02rem 0.28rem;
  color: var(--primary, #b85c38);
  font-weight: 700;
}
</style>
