<template>
  <label class="field">
    <span>{{ t('inferenceOps.fields.topK') }}</span>
    <input :value="topK" type="number" min="1" max="1000" step="1" @input="emitNumber" />
  </label>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ topK: number }>()
const emit = defineEmits<{ 'update:topK': [value: number] }>()
const { t } = useI18n()

function emitNumber(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  if (Number.isInteger(value) && value >= 1) emit('update:topK', value)
}
</script>
