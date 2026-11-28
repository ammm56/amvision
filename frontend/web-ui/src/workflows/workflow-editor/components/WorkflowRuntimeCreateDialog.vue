<template>
  <ConfirmDialog
    v-if="open"
    title="创建运行实例"
    confirm-label="创建实例"
    cancel-label="取消"
    :busy="busy"
    :confirm-disabled="!selectedVersionId || !timeoutValid"
    confirm-variant="primary"
    initial-focus="first-field"
    @cancel="emit('cancel')"
    @confirm="confirmCreate"
  >
    <p v-if="appName" class="rt-create-subtitle">所属应用：{{ appName }}</p>

    <label class="rt-form-row">
      <span class="rt-form-label">实例名称</span>
      <input
        v-model="displayName"
        type="text"
        maxlength="200"
        :disabled="busy"
        placeholder="可选，默认使用应用名称"
      />
    </label>

    <div class="rt-form-row">
      <span class="rt-form-label">发布版本 <em>*</em></span>
      <Select
        floating
        :model-value="selectedVersionId"
        :options="versionOptions"
        :disabled="busy"
        aria-label="发布版本"
        @update:model-value="selectedVersionId = readString($event)"
      />
    </div>

    <label class="rt-form-row">
      <span class="rt-form-label">{{ t('workflowEditor.appDetail.fields.requestTimeoutSeconds') }}</span>
      <input
        v-model="requestTimeoutSeconds"
        type="number"
        min="1"
        step="1"
        :max="Number.MAX_SAFE_INTEGER"
        :disabled="busy"
        :aria-invalid="!timeoutValid"
        :placeholder="t('workflowEditor.appDetail.fields.serviceDefaultTimeout')"
      />
    </label>

    <div class="rt-form-row">
      <span class="rt-form-label">执行记录 <em>*</em></span>
      <Select
        floating
        :model-value="workflowRunRecordMode"
        :options="workflowRunRecordModeOptions"
        :disabled="busy"
        aria-label="执行记录"
        @update:model-value="workflowRunRecordMode = readRecordMode($event)"
      />
    </div>

    <div class="rt-form-row">
      <span class="rt-form-label">返回诊断 <em>*</em></span>
      <Select
        floating
        :model-value="returnDiagnostics"
        :options="returnDiagnosticsOptions"
        :disabled="busy"
        aria-label="返回诊断"
        @update:model-value="returnDiagnostics = readString($event) === 'true' ? 'true' : 'false'"
      />
    </div>

    <p class="rt-form-note">创建后处于停止状态。</p>
    <InlineError v-if="!timeoutValid" :message="t('workflowEditor.appDetail.fields.invalidRequestTimeout')" />
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
  displayName?: string
  workflowAppVersionId: string
  workflowRunRecordMode: WorkflowRunRecordMode
  returnDiagnostics: boolean
  requestTimeoutSeconds: number | null
}

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

const props = defineProps<{
  open: boolean
  busy: boolean
  appName?: string
  defaultVersionId: string
  versionOptions: SelectOption[]
  errorMessage?: string | null
}>()

const emit = defineEmits<{
  cancel: []
  create: [value: WorkflowRuntimeCreateDialogValue]
}>()

const { t } = useI18n()
const displayName = ref('')
const selectedVersionId = ref('')
const workflowRunRecordMode = ref<WorkflowRunRecordMode>('none')
const returnDiagnostics = ref('false')
const requestTimeoutSeconds = ref<number | string>('')
const timeoutValid = computed(() => requestTimeoutSeconds.value === '' || (
  typeof requestTimeoutSeconds.value === 'number'
  && Number.isSafeInteger(requestTimeoutSeconds.value)
  && requestTimeoutSeconds.value > 0
))

const workflowRunRecordModeOptions = computed<SelectOption[]>(() => [
  { label: '不保存', value: 'none', description: t('workflowEditor.appDetail.options.recordNone') },
  { label: '摘要', value: 'minimal', description: t('workflowEditor.appDetail.options.recordMinimal') },
  { label: '完整', value: 'full', description: t('workflowEditor.appDetail.options.recordFull') },
])

const returnDiagnosticsOptions = computed<SelectOption[]>(() => [
  { label: '关闭', value: 'false', description: t('workflowEditor.appDetail.options.diagnosticsOff') },
  { label: '开启', value: 'true', description: t('workflowEditor.appDetail.options.diagnosticsOn') },
])

watch(
  () => props.open,
  (open) => {
    if (!open) return
    displayName.value = ''
    selectedVersionId.value = props.defaultVersionId
    workflowRunRecordMode.value = 'none'
    returnDiagnostics.value = 'false'
    requestTimeoutSeconds.value = ''
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
  if (!selectedVersionId.value || !timeoutValid.value || props.busy) return
  const trimmedName = displayName.value.trim()
  emit('create', {
    ...(trimmedName ? { displayName: trimmedName } : {}),
    workflowAppVersionId: selectedVersionId.value,
    workflowRunRecordMode: workflowRunRecordMode.value,
    returnDiagnostics: returnDiagnostics.value === 'true',
    requestTimeoutSeconds: requestTimeoutSeconds.value === '' ? null : Number(requestTimeoutSeconds.value),
  })
}
</script>

<style scoped>
.rt-create-subtitle {
  margin: 0 0 4px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.rt-form-row {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
}

.rt-form-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--am-text-strong);
}

.rt-form-label em {
  color: #dc2626;
  font-style: normal;
}

.rt-form-row input {
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

.rt-form-row input:focus-visible {
  outline: 2px solid var(--am-input-focus-ring);
  outline-offset: 1px;
}

.rt-form-note {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--am-text-muted);
}
</style>
