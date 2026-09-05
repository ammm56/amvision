<template>
  <ConfirmDialog
    v-if="open"
    :title="t('workflowEditor.appDetail.actions.switchVersion')"
    :confirm-label="t('workflowEditor.appDetail.actions.switchVersion')"
    :cancel-label="t('common.cancel')"
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
    <label class="workflow-dialog-field">
      <span>{{ t('workflowEditor.appDetail.fields.targetVersion') }}</span>
      <Select
        :model-value="targetVersionId"
        :options="versionOptions"
        @update:model-value="emit('update:targetVersionId', readString($event))"
      />
    </label>
    <label v-if="showBreakingOverride" class="workflow-dialog-check">
      <input
        :checked="allowBreakingContract"
        type="checkbox"
        @change="emit('update:allowBreakingContract', readChecked($event))"
      />
      <span>{{ t('workflowEditor.appDetail.fields.breakingOverride') }}</span>
    </label>
    <label v-if="showBreakingOverride && allowBreakingContract" class="workflow-dialog-field">
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
.workflow-dialog-field {
  display: grid;
  gap: var(--am-space-sm);
}

.workflow-dialog-field > span,
.workflow-runtime-version-route span {
  color: var(--am-text-muted);
  font-size: 13px;
  font-weight: 700;
}

.workflow-dialog-check {
  display: flex;
  align-items: center;
  gap: var(--am-space-sm);
}

.workflow-dialog-check input {
  width: 18px;
  height: 18px;
}

.workflow-runtime-version-route {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: var(--am-space-md);
  padding: var(--am-space-md);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
}

.workflow-runtime-version-route > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.workflow-runtime-version-route strong {
  overflow-wrap: anywhere;
}
</style>
