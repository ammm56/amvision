<template>
  <button type="button" class="appearance-summary" :disabled="disabled" :aria-label="t('workflowDisplay.editLabel', { label: 'Appearance' })" @click="edit">{{ t(configured ? 'workflowDisplay.custom' : 'workflowDisplay.default') }}<span>{{ t('workflowDisplay.edit') }}</span></button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" title="Appearance" :confirm-label="t('workflowDisplay.apply')" :cancel-label="t('workflowDisplay.cancel')" confirm-variant="primary" size="medium" scroll-body :confirm-disabled="!valid || disabled" @cancel="open = false" @confirm="apply">
      <div class="appearance-editor">
        <label v-for="control in appearanceControls" :key="control.key">
          <span>{{ control.label }}</span>
          <input type="number" :aria-label="control.label" :min="control.min" :max="control.max" step="1" :placeholder="control.default === null ? 'Auto' : String(control.default)" :value="draft[control.key] ?? ''" :disabled="disabled" @input="setNumber(control.key, ($event.target as HTMLInputElement).value)" />
          <small>{{ control.key === 'background_opacity' ? '%' : 'CSS px' }} · {{ control.min }}–{{ control.max }}</small>
        </label>
        <div class="appearance-editor__color"><span>Background Color</span><WorkflowDisplayColor :key="colorRevision" v-model="draft.background_color" label="Background Color" default-color="var(--am-surface)" :disabled="disabled" @validity-change="colorValid = $event" /></div>
      </div>
      <p v-if="!valid" role="alert">{{ t('workflowDisplay.invalidAppearance') }}</p>
      <div class="appearance-preview" :aria-label="t('workflowDisplay.appearancePreview')"><WorkflowValueDisplay :payload="preview" overlay /></div>
      <template #leading-actions><Button variant="secondary" :disabled="disabled" @click="reset">{{ t('workflowDisplay.reset') }}</Button></template>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import { useTranslation } from '@/platform/i18n'
const { t } = useTranslation()
import { computed, ref } from 'vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Button from '@/shared/ui/components/Button.vue'
import WorkflowDisplayColor from './WorkflowDisplayColor.vue'
import WorkflowValueDisplay from './WorkflowValueDisplay.vue'
import { appearanceControls } from '../preview/value-display'
import type { WorkflowJsonObject } from '../types'
const props = defineProps<{ modelValue: unknown; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: WorkflowJsonObject] }>()
const open = ref(false), draft = ref<WorkflowJsonObject>({}), colorValid = ref(true)
const colorRevision = ref(0)
const configured = computed(() => Boolean(props.modelValue && Object.keys(props.modelValue).length))
const valid = computed(() => colorValid.value && appearanceControls.every(c => {
  const value = draft.value[c.key]
  return value === undefined || value === null && c.default === null || typeof value === 'number' && Number.isInteger(value) && value >= c.min && value <= c.max
}))
const preview = computed<WorkflowJsonObject>(() => ({ appearance: draft.value, fields: [
  { label: 'Status', value: 'OK', format: 'status', states: { OK: 'success' } },
  { label: 'Quantity', value: 24, format: 'integer' },
  { label: 'Rate', value: .9583, format: 'percent', precision: 2 },
] }))
function edit() { draft.value = JSON.parse(JSON.stringify(props.modelValue || {})); colorValid.value = true; open.value = true }
function setNumber(key: string, value: string) {
  if (!value.trim()) delete draft.value[key]
  else draft.value[key] = Number(value)
}
function reset() { draft.value = {}; colorValid.value = true; colorRevision.value++ }
function apply() { if (!valid.value || props.disabled) return; emit('update:modelValue', draft.value); open.value = false }
</script>
<style scoped>
.appearance-summary { display: flex; justify-content: space-between; width: 100%; height: 28px; align-items: center; padding: 0 8px; border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); background: var(--am-input); color: var(--am-text); font: inherit; cursor: pointer; }
.appearance-summary span { color: var(--am-text-muted); }
.appearance-editor { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.appearance-editor label, .appearance-editor__color { display: grid; align-content: start; gap: 6px; min-width: 0; font-size: 13px; }
.appearance-editor input { width: 100%; min-width: 0; min-height: 36px; padding: 8px; border: 1px solid var(--am-border-strong); border-radius: var(--am-radius-sm); background: var(--am-input); color: var(--am-text); font: inherit; }
.appearance-editor small { color: var(--am-text-muted); }
.appearance-preview { height: 260px; padding: 12px; margin-top: 16px; border: 1px solid var(--am-border); border-radius: var(--am-radius-md); background: var(--am-surface-soft); overflow: hidden; }
[role='alert'] { color: var(--am-danger-text); }
@media (max-width: 540px) { .appearance-editor { grid-template-columns: minmax(0, 1fr); } }
</style>
