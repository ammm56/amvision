<template>
  <label class="field">
    <span>{{ t('inferenceOps.fields.scoreThreshold') }}</span>
    <input :value="scoreThreshold" type="number" min="0" max="1" step="0.01" @input="emitThreshold('update:scoreThreshold', $event)" />
  </label>
  <label class="field">
    <span>{{ t('inferenceOps.fields.maskThreshold') }}</span>
    <input :value="maskThreshold" type="number" min="0" max="1" step="0.01" @input="emitThreshold('update:maskThreshold', $event)" />
  </label>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ scoreThreshold: number; maskThreshold: number }>()
type ThresholdEvent = 'update:scoreThreshold' | 'update:maskThreshold'
const emit = defineEmits<{
  'update:scoreThreshold': [value: number]
  'update:maskThreshold': [value: number]
}>()
const { t } = useI18n()

function emitThreshold(name: ThresholdEvent, event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value) || value < 0 || value > 1) return
  if (name === 'update:scoreThreshold') emit('update:scoreThreshold', value)
  else emit('update:maskThreshold', value)
}
</script>
