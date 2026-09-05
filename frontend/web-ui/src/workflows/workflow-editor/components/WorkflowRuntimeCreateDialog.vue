<template>
  <ConfirmDialog
    v-if="open"
    :title="t('workflowEditor.appDetail.actions.createRuntime')"
    :confirm-label="t('workflowEditor.appDetail.actions.createRuntime')"
    :cancel-label="t('common.cancel')"
    :busy="busy"
    :confirm-disabled="!selectedVersionId"
    confirm-variant="primary"
    initial-focus="first-field"
    @cancel="emit('cancel')"
    @confirm="confirmCreate"
  >
    <label class="workflow-dialog-field">
      <span>{{ t('workflowEditor.appDetail.fields.createFromVersion') }}</span>
      <Select
        :model-value="selectedVersionId"
        :options="versionOptions"
        @update:model-value="selectedVersionId = readString($event)"
      />
    </label>
    <label class="workflow-dialog-field">
      <span>{{ t('workflowEditor.appDetail.fields.workflowRunRecord') }}</span>
      <Select
        :model-value="workflowRunRecordMode"
        :options="workflowRunRecordModeOptions"
        @update:model-value="workflowRunRecordMode = readRecordMode($event)"
      />
    </label>
    <label class="workflow-dialog-field">
      <span>{{ t('workflowEditor.appDetail.fields.returnDiagnostics') }}</span>
      <Select
        :model-value="returnDiagnostics"
        :options="returnDiagnosticsOptions"
        @update:model-value="returnDiagnostics = readString($event) === 'true' ? 'true' : 'false'"
      />
    </label>
    <InlineError v-if="errorMessage" :message="errorMessage" />
  </ConfirmDialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

type SelectValue = string | number | boolean | null
type WorkflowRunRecordMode = 'full' | 'minimal' | 'none'

interface WorkflowRuntimeCreateDialogValue {
  workflowAppVersionId: string
  workflowRunRecordMode: WorkflowRunRecordMode
  returnDiagnostics: boolean
}

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

const props = defineProps<{
  open: boolean
  busy: boolean
  defaultVersionId: string
  versionOptions: SelectOption[]
  errorMessage?: string | null
}>()

const emit = defineEmits<{
  cancel: []
  create: [value: WorkflowRuntimeCreateDialogValue]
}>()

const { t } = useI18n()
const selectedVersionId = ref('')
const workflowRunRecordMode = ref<WorkflowRunRecordMode>('none')
const returnDiagnostics = ref('false')

const workflowRunRecordModeOptions = computed<SelectOption[]>(() => [
  { label: 'none', value: 'none', description: t('workflowEditor.appDetail.options.recordNone') },
  { label: 'minimal', value: 'minimal', description: t('workflowEditor.appDetail.options.recordMinimal') },
  { label: 'full', value: 'full', description: t('workflowEditor.appDetail.options.recordFull') },
])

const returnDiagnosticsOptions = computed<SelectOption[]>(() => [
  { label: t('workflowEditor.appDetail.options.no'), value: 'false', description: t('workflowEditor.appDetail.options.diagnosticsOff') },
  { label: t('workflowEditor.appDetail.options.yes'), value: 'true', description: t('workflowEditor.appDetail.options.diagnosticsOn') },
])

watch(
  () => props.open,
  (open) => {
    if (!open) return
    selectedVersionId.value = props.defaultVersionId
    workflowRunRecordMode.value = 'none'
    returnDiagnostics.value = 'false'
  },
  { immediate: true },
)

function readString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function readRecordMode(value: SelectValue): WorkflowRunRecordMode {
  const normalized = readString(value)
  return normalized === 'full' || normalized === 'minimal' ? normalized : 'none'
}

function confirmCreate(): void {
  if (!selectedVersionId.value) return
  emit('create', {
    workflowAppVersionId: selectedVersionId.value,
    workflowRunRecordMode: workflowRunRecordMode.value,
    returnDiagnostics: returnDiagnostics.value === 'true',
  })
}
</script>

<style scoped>
.workflow-dialog-field {
  display: grid;
  gap: var(--am-space-sm);
}

.workflow-dialog-field > span {
  color: var(--am-text-strong);
  font-size: 13px;
  font-weight: 700;
}
</style>
