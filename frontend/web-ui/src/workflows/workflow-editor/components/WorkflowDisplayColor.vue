<template>
  <div class="display-color">
    <div class="display-color__control">
      <button type="button" :aria-label="t('workflowDisplay.chooseColor', { label })" :aria-expanded="open" :disabled="disabled" @click="open = !open">
        <span class="display-color__swatch" :style="{ background: resolved }" />
      </button>
      <input :aria-label="label" :value="draft" :placeholder="presetLabel || 'Auto'" :disabled="disabled" spellcheck="false" @input="update(($event.target as HTMLInputElement).value)" />
      <button type="button" :disabled="disabled" :aria-label="t('workflowDisplay.resetColor', { label })" @click="choose(null)"><RotateCcw :size="14" /></button>
    </div>
    <div v-if="open" class="display-color__palette">
      <button v-for="color in paletteColors" :key="color" type="button" :disabled="disabled" :aria-label="color" :title="color" :style="{ background: color }" @click="choose(color)" />
      <template v-if="presets">
        <button v-for="(preset, key) in statePresets" :key="key" class="display-color__preset" type="button" :disabled="disabled" @click="choose(key)"><span class="display-color__swatch" :style="{ background: preset.color }" />{{ preset.label }}</button>
      </template>
    </div>
    <small v-if="invalid" role="alert">{{ t('workflowDisplay.invalidColor') }}</small>
  </div>
</template>
<script setup lang="ts">
import { useTranslation } from '@/platform/i18n'
const { t } = useTranslation()
import { computed, ref, watch } from 'vue'
import { RotateCcw } from '@lucide/vue'
import { displayColor, isHexColor, normalizeHexColor, paletteColors, statePresets } from '../parameters/display-colors'
const props = withDefaults(defineProps<{ modelValue?: unknown; label: string; presets?: boolean; disabled?: boolean; defaultColor?: string }>(), { defaultColor: 'var(--am-text)' })
const emit = defineEmits<{ 'update:modelValue': [value: string | null]; 'validity-change': [valid: boolean] }>()
const open = ref(false), draft = ref(''), invalid = ref(false)
const presetLabel = computed(() => props.presets && typeof props.modelValue === 'string' ? statePresets[props.modelValue]?.label : '')
const resolved = computed(() => displayColor(props.modelValue) || props.defaultColor)
watch(() => props.modelValue, value => { draft.value = typeof value === 'string' && isHexColor(value) ? value : ''; invalid.value = false }, { immediate: true })
function update(value: string) {
  draft.value = value
  invalid.value = Boolean(value.trim()) && !isHexColor(value)
  emit('validity-change', !invalid.value)
  if (!invalid.value) emit('update:modelValue', value.trim() ? normalizeHexColor(value) : null)
}
function choose(value: string | null) { invalid.value = false; draft.value = value && isHexColor(value) ? value : ''; emit('validity-change', true); emit('update:modelValue', value); open.value = false }
</script>
<style scoped>
.display-color { display: grid; gap: 6px; min-width: 0; }
.display-color__control { display: flex; gap: 6px; align-items: center; min-width: 0; }
.display-color__control input { width: 100%; min-width: 0; height: 36px; padding: 6px 8px; border: 1px solid var(--am-border-strong); border-radius: var(--am-radius-sm); color: var(--am-text); background: var(--am-input); font: inherit; }
.display-color button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; flex: none; min-height: 30px; padding: 4px; border: 1px solid var(--am-border); border-radius: 4px; color: var(--am-text); background: var(--am-surface); cursor: pointer; }
.display-color__swatch { display: inline-block; width: 20px; height: 20px; border: 1px solid var(--am-border); border-radius: 3px; }
.display-color__palette { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 5px; padding: 8px; border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); }
.display-color__palette .display-color__preset { grid-column: span 4; font: inherit; }
.display-color small { color: var(--am-danger-text); }
.display-color :focus-visible { outline: 2px solid var(--am-input-focus-ring); outline-offset: 2px; }
</style>
