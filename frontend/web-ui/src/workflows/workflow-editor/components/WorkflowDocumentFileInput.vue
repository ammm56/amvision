<template>
  <input ref="input" type="file" accept=".json,application/json" hidden :disabled="disabled" :aria-label="t('workflowEditor.document.import')" @change="selectFile" />
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ import: [file: File] }>()
const { t } = useI18n()
const input = ref<HTMLInputElement | null>(null)
function open(): void {
  if (!props.disabled) input.value?.click()
}
function selectFile(event: Event): void {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (file && !props.disabled) emit('import', file)
}
defineExpose({ open })
</script>
