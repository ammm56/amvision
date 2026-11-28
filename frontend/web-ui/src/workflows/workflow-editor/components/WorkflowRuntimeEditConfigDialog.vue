<template>
  <ConfirmDialog
    v-if="open && runtime"
    title="编辑运行实例配置"
    confirm-label="保存配置"
    cancel-label="取消"
    :busy="busy"
    :confirm-disabled="!displayName.trim() || !timeoutValid"
    confirm-variant="primary"
    initial-focus="first-field"
    scroll-body
    @cancel="emit('cancel')"
    @confirm="submitConfig"
  >
    <div class="rt-edit-context">
      <strong>{{ appName }}</strong>
      <span class="rt-edit-state">{{ stateLabel }}</span>
    </div>

    <label class="rt-edit-row">
      <span class="rt-edit-label">实例名称 <em>*</em></span>
      <input
        v-model="displayName"
        type="text"
        maxlength="200"
        :disabled="busy"
        placeholder="请输入实例名称"
      />
    </label>

    <div class="rt-edit-row">
      <span class="rt-edit-label">发布版本</span>
      <span class="rt-edit-readonly">{{ versionLabel }}</span>
    </div>

    <label class="rt-edit-row">
      <span class="rt-edit-label">请求超时（秒） <em>*</em></span>
      <input
        v-model="requestTimeoutSeconds"
        type="number"
        min="1"
        step="1"
        :max="Number.MAX_SAFE_INTEGER"
        :disabled="busy"
        :aria-invalid="!timeoutValid"
        :aria-describedby="!timeoutValid ? timeoutErrorId : undefined"
      />
    </label>

    <div class="rt-edit-row">
      <span class="rt-edit-label">执行记录 <em>*</em></span>
      <Select
        floating
        :model-value="workflowRunRecordMode"
        :options="recordModeOptions"
        :disabled="busy"
        aria-label="执行记录"
        @update:model-value="workflowRunRecordMode = parseRecordMode($event)"
      />
    </div>

    <div class="rt-edit-row">
      <span class="rt-edit-label">返回诊断 <em>*</em></span>
      <Select
        floating
        :model-value="returnDiagnostics"
        :options="diagnosticsOptions"
        :disabled="busy"
        aria-label="返回诊断"
        @update:model-value="returnDiagnostics = String($event) === 'true' ? 'true' : 'false'"
      />
    </div>

    <InlineError v-if="!timeoutValid" :id="timeoutErrorId" message="请求超时必须为正整数（秒）" />
    <InlineError v-if="errorMessage" :message="errorMessage" />
    <template #leading-actions>
      <p class="rt-edit-note">保存后，下次启动生效。</p>
    </template>
  </ConfirmDialog>
</template>

<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'

import { getErrorMessage } from '@/shared/api/error'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { updateWorkflowAppRuntimeConfig } from '../services/workflow-runtime.service'
import type { WorkflowAppRuntime } from '../types'
import { readRuntimeDiagnosticsEnabled, readRuntimeRecordMode } from '../utils/workflow-run-display'

type RecordMode = 'none' | 'minimal' | 'full'

const props = defineProps<{
  open: boolean
  appName: string
  versionLabel: string
  runtime: WorkflowAppRuntime | null
}>()

const emit = defineEmits<{
  cancel: []
  saved: [runtime: WorkflowAppRuntime]
}>()

const displayName = ref('')
const requestTimeoutSeconds = ref<number | string>(60)
const workflowRunRecordMode = ref<RecordMode>('none')
const returnDiagnostics = ref<'true' | 'false'>('false')
const busy = ref(false)
const errorMessage = ref<string | null>(null)
const timeoutErrorId = useId()

const recordModeOptions = [
  { label: '不保存', value: 'none' },
  { label: '摘要', value: 'minimal' },
  { label: '完整', value: 'full' },
]

const diagnosticsOptions = [
  { label: '关闭', value: 'false' },
  { label: '开启', value: 'true' },
]

const stateLabel = computed(() => {
  const state = props.runtime?.observed_state
  if (state === 'stopped') return '已停止'
  if (state === 'failed') return '启动失败'
  if (state === 'running') return '运行中（需先停止）'
  return '状态未知'
})

const timeoutValid = computed(() => {
  const num = Number(requestTimeoutSeconds.value)
  return Number.isSafeInteger(num) && num > 0
})

watch(
  () => [props.open, props.runtime?.workflow_runtime_id] as const,
  ([isOpen]) => {
    if (!isOpen || !props.runtime) return
    displayName.value = props.runtime.display_name || ''
    requestTimeoutSeconds.value = props.runtime.request_timeout_seconds || 60
    workflowRunRecordMode.value = readRuntimeRecordMode(props.runtime)
    returnDiagnostics.value = readRuntimeDiagnosticsEnabled(props.runtime) ? 'true' : 'false'
    errorMessage.value = null
  },
  { immediate: true },
)

function parseRecordMode(value: unknown): RecordMode {
  return value === 'full' || value === 'minimal' ? value : 'none'
}

async function submitConfig(): Promise<void> {
  if (!props.runtime || !displayName.value.trim() || !timeoutValid.value || busy.value) return
  busy.value = true
  errorMessage.value = null
  try {
    const updated = await updateWorkflowAppRuntimeConfig(props.runtime.workflow_runtime_id, {
      expectedGeneration: props.runtime.revision_generation,
      displayName: displayName.value.trim(),
      requestTimeoutSeconds: Number(requestTimeoutSeconds.value),
      workflowRunRecordMode: workflowRunRecordMode.value,
      returnDiagnostics: returnDiagnostics.value === 'true',
    })
    emit('saved', updated)
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.rt-edit-context {
  display: grid;
  gap: 2px;
  padding-bottom: 6px;
}

.rt-edit-context strong {
  font-size: 14px;
  color: var(--am-text-strong);
}

.rt-edit-state {
  font-size: 12px;
  color: var(--am-text-muted);
}

.rt-edit-row {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
}

.rt-edit-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--am-text-strong);
}

.rt-edit-label em {
  color: #dc2626;
  font-style: normal;
}

.rt-edit-row input {
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

.rt-edit-row input:focus-visible {
  outline: 2px solid var(--am-input-focus-ring);
  outline-offset: 1px;
}

.rt-edit-readonly {
  font-size: 13px;
  color: var(--am-text-strong);
}

.rt-edit-note {
  margin: 0;
  font-size: 12px;
  color: var(--am-text-muted);
}

@media (max-width: 420px) {
  .rt-edit-row { grid-template-columns: 1fr; gap: 5px; }
}
</style>
