<template>
  <ConfirmDialog
    v-if="open"
    title="切换版本"
    confirm-label="切换版本"
    cancel-label="取消"
    :busy="busy"
    :confirm-disabled="confirmDisabled"
    confirm-variant="primary"
    initial-focus="first-field"
    @cancel="emit('cancel')"
    @confirm="emit('confirm')"
  >
    <div class="workflow-runtime-version-route">
      <div>
        <span>{{ t('workflowEditor.appDetail.fields.activeVersion') }}</span>
        <strong>{{ currentVersionLabel }}</strong>
      </div>
      <span aria-hidden="true">→</span>
      <div>
        <span>{{ t('workflowEditor.appDetail.fields.targetVersion') }}</span>
        <strong>{{ targetVersionLabel }}</strong>
      </div>
    </div>

    <div class="rt-ver-row">
      <span class="rt-ver-label">{{ t('workflowEditor.appDetail.fields.targetVersion') }} <em>*</em></span>
      <Select
        floating
        :model-value="targetVersionId"
        :options="versionOptions"
        :disabled="busy"
        aria-label="目标版本"
        @update:model-value="emit('update:targetVersionId', readString($event))"
      />
    </div>

    <label v-if="showBreakingOverride" class="workflow-dialog-check">
      <input
        :checked="allowBreakingContract"
        type="checkbox"
        @change="emit('update:allowBreakingContract', readChecked($event))"
      />
      <span>{{ t('workflowEditor.appDetail.fields.breakingOverride') }}</span>
    </label>

    <label v-if="showBreakingOverride && allowBreakingContract" class="rt-ver-field">
      <span>{{ t('workflowEditor.appDetail.fields.breakingReason') }}</span>
      <input
        :value="breakingChangeReason"
        maxlength="2048"
        :placeholder="t('workflowEditor.appDetail.placeholders.breakingReason')"
        @input="emit('update:breakingChangeReason', readInput($event))"
      />
    </label>

    <InlineError v-if="errorMessage" :message="errorMessage" />
  </ConfirmDialog>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

type SelectValue = string | number | boolean | null

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

defineProps<{
  open: boolean
  busy: boolean
  confirmDisabled: boolean
  currentVersionLabel: string
  targetVersionId: string
  targetVersionLabel: string
  versionOptions: SelectOption[]
  showBreakingOverride: boolean
  allowBreakingContract: boolean
  breakingChangeReason: string
  errorMessage?: string | null
}>()

const emit = defineEmits<{
  cancel: []
  confirm: []
  'update:targetVersionId': [value: string]
  'update:allowBreakingContract': [value: boolean]
  'update:breakingChangeReason': [value: string]
}>()

const { t } = useI18n()

function readString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function readChecked(event: Event): boolean {
  return event.target instanceof HTMLInputElement && event.target.checked
}

function readInput(event: Event): string {
  return event.target instanceof HTMLInputElement ? event.target.value : ''
}
</script>

<style scoped>
.workflow-runtime-version-route {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
}

.workflow-runtime-version-route > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.workflow-runtime-version-route span {
  color: var(--am-text-muted);
  font-size: 12px;
}

.workflow-runtime-version-route strong {
  color: var(--am-text-strong);
  font-size: 14px;
  overflow-wrap: anywhere;
}

.rt-ver-row {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
}

.rt-ver-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--am-text-strong);
}

.rt-ver-label em {
  color: #dc2626;
  font-style: normal;
}

.rt-ver-field {
  display: grid;
  gap: 6px;
}

.rt-ver-field > span {
  color: var(--am-text-strong);
  font-size: 13px;
  font-weight: 500;
}

.rt-ver-field input {
  width: 100%;
  box-sizing: border-box;
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--am-border-strong);
  border-radius: var(--am-radius-sm);
  background: var(--am-input);
  color: var(--am-text-strong);
  font-size: 13px;
}

.rt-ver-field input:focus-visible {
  outline: 2px solid var(--am-input-focus-ring);
  outline-offset: 1px;
}

.workflow-dialog-check {
  display: flex;
  align-items: center;
  gap: var(--am-space-sm);
  font-size: 13px;
  color: var(--am-text-strong);
}

.workflow-dialog-check input {
  width: 16px;
  height: 16px;
}
</style>
