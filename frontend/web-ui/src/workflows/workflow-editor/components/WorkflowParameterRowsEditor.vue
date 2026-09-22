<template>
  <button type="button" class="parameter-rows-summary" :disabled="disabled" :aria-label="t('workflowDisplay.editLabel', { label })" @click="openEditor">
    <span>{{ count ? t('workflowDisplay.configured', { count }) : t('workflowDisplay.unconfigured') }}</span><span>{{ t('workflowDisplay.edit') }}</span>
  </button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" :title="label" :confirm-label="t('workflowDisplay.apply')" :cancel-label="t('workflowDisplay.cancel')" confirm-variant="primary" size="medium" scroll-body
      :confirm-disabled="!valid || disabled" @cancel="open = false" @confirm="apply">
      <WorkflowParameterRows :model-value="draft" :schema="schema" :disabled="disabled"
        @update:model-value="draft = $event" @validity-change="valid = $event" />
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import { useTranslation } from '@/platform/i18n'
const { t } = useTranslation()
import { computed, ref } from 'vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import type { WorkflowJsonObject } from '../types'
import WorkflowParameterRows from './WorkflowParameterRows.vue'

const props = defineProps<{ modelValue: unknown; schema: WorkflowJsonObject; label: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()
const open = ref(false)
const draft = ref<unknown>([])
const valid = ref(true)
const count = computed(() => Array.isArray(props.modelValue) ? props.modelValue.length : 0)
function openEditor() {
  draft.value = JSON.parse(JSON.stringify(props.modelValue ?? []))
  valid.value = true
  open.value = true
}
function apply() {
  if (!valid.value || props.disabled) return
  emit('update:modelValue', draft.value)
  open.value = false
}
</script>
<style scoped>
.parameter-rows-summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; min-width: 0; height: 28px; padding: 0 8px; border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); background: var(--am-input); color: var(--am-text); cursor: pointer; font: inherit; }
.parameter-rows-summary span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.parameter-rows-summary span:last-child { flex: none; color: var(--am-text-muted); }
.parameter-rows-summary:disabled { opacity: .6; cursor: default; }
.parameter-rows-summary:focus-visible { outline: 2px solid var(--am-input-focus-ring); outline-offset: 2px; }
</style>
