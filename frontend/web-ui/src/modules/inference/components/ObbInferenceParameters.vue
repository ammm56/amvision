<template>
  <label class="field">
    <span>{{ t('inferenceOps.fields.scoreThreshold') }}</span>
    <input :value="scoreThreshold" type="number" min="0" max="1" step="0.01" @input="emitThreshold" />
  </label>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ scoreThreshold: number }>()
const emit = defineEmits<{ 'update:scoreThreshold': [value: number] }>()
const { t } = useI18n()

function emitThreshold(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  if (Number.isFinite(value) && value >= 0 && value <= 1) emit('update:scoreThreshold', value)
}
</script>
