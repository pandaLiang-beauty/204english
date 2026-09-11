import { computed, ref } from 'vue'
import { englishApi } from './api.js'

/**
 * Owns voice-selection state and the preview lifecycle.
 * Playback for study sentences stays in useEnglishAudio; this composable only
 * manages the configuration screens and per-sentence voice selection.
 */
export function useEnglishAudioSettings(callbacks = {}) {
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
  let voicePreviewAudio = null

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

  function audioVoiceKey(provider, voice) {
    const cleanProvider = String(provider || '').trim().toLowerCase()
    const cleanVoice = String(voice || '').trim()
    return cleanProvider && cleanVoice ? `${cleanProvider}|${cleanVoice}` : ''
  }

  function audioVoiceFromKey(value) {
    const [provider, ...voiceParts] = String(value || '').split('|')
    return { provider, voice: voiceParts.join('|') }
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
      applyAudioSettingsResult(await englishApi.updateAudioSettings(selection))
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
      const result = await englishApi.createAudioPreview({ provider: voice.provider, voice: voice.voice })
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
      const decorated = callbacks.updateSentenceInList?.(updated, sentence)
      if (decorated?.ui) {
        decorated.ui.message = updated.audio_needs_regeneration
          ? '音色已指定，正在生成整句音频'
          : '音色设置已更新'
      }
      if (updated.audio_needs_regeneration) callbacks.scheduleAudioStatusRefresh?.(25000)
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

  return {
    audioSettings,
    selectedGlobalVoice,
    audioSettingsLoading,
    audioSettingsSaving,
    audioSettingsApplying,
    audioSettingsMessage,
    audioSettingsError,
    previewLoadingVoice,
    previewPlayingVoice,
    voiceProviderFilter,
    audioVoiceGroups,
    filteredAudioVoiceGroups,
    kokoroVoiceCount,
    edgeVoiceCount,
    audioVoiceKey,
    loadAudioSettings,
    saveGlobalAudioSettings,
    applyGlobalAudioSettings,
    stopVoicePreview,
    playVoicePreview,
    sentenceAudioSelection,
    changeSentenceAudioVoice,
    compactDate,
    audioProviderLabel,
    audioVoiceOptionLabel,
    voiceProviderFilterButtonClass,
    globalSentenceAudioIdentity,
    sentenceAudioIdentity,
    wordAudioIdentity,
    sentenceAudioButtonClass,
    sentenceAudioStatusLabel,
    sentenceAudioStatusClass
  }
}
