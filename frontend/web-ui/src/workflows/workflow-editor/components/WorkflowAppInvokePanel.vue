<template>
  <div class="invoke-panel">
    <!-- Top context bar -->
    <section class="invoke-context-card">
      <div class="invoke-context-row">
        <div class="invoke-context-left">
          <span class="invoke-label">实例</span>
          <div class="invoke-runtime-select">
            <SelectField
              fit-options
              floating
              :model-value="selectedRuntimeId"
              :options="runtimeOptions"
              :disabled="isCurrentSubmitting || runtimes.length === 0"
              aria-label="选择调试实例"
              @update:model-value="(val) => emit('select-runtime', String(val || ''))"
            />
          </div>
          <span v-if="selectedRuntime" class="invoke-status-pill" :class="`is-${runtimeDotTone}`">
            <i class="invoke-dot" />
            {{ runtimeStateText }}
          </span>
          <span v-if="selectedRuntime" class="invoke-sep">|</span>
          <span v-if="selectedRuntime" class="invoke-muted">
            运行版本 <strong>{{ selectedRuntimeVersionLabel }}</strong>
          </span>
        </div>

        <div class="invoke-context-right">
          <button
            v-if="selectedRuntime"
            type="button"
            class="invoke-link-btn"
            @click="emit('open-runtime-config', selectedRuntime)"
          >
            查看实例配置
          </button>
          <Button variant="secondary" size="sm" :disabled="!requestExamples" @click="emit('open-examples')">
            <Copy :size="14" />
            请求示例
          </Button>
        </div>
      </div>

      <div v-if="selectedRuntime" class="invoke-context-row invoke-context-row--sub">
        <div class="invoke-mode-toggle" role="group" aria-label="调用方式">
          <button
            type="button"
            class="invoke-mode-btn"
            :class="{ 'is-active': submitMode === 'sync' }"
            :disabled="isCurrentSubmitting"
            @click="submitMode = 'sync'"
          >
            同步
          </button>
          <button
            type="button"
            class="invoke-mode-btn"
            :class="{ 'is-active': submitMode === 'async' }"
            :disabled="isCurrentSubmitting || recordMode === 'none'"
            :title="recordMode === 'none' ? '异步调用需要保存执行记录' : '提交异步执行'"
            data-invoke-mode-async
            @click="selectAsyncMode"
          >
            异步
          </button>
        </div>

        <div v-if="recordMode === 'none'" class="invoke-async-warn" data-invoke-async-none-banner>
          <AlertTriangle :size="15" />
          <div class="invoke-async-warn__text">
            <strong>异步调用需要保存执行记录</strong>
            <button
              type="button"
              class="invoke-link-btn"
              @click="emit('open-runtime-config', selectedRuntime)"
            >
              修改配置
            </button>
          </div>
        </div>

        <span class="invoke-record-pill">执行记录：{{ formatRecordModeLabel(recordMode) }}</span>
      </div>
    </section>

    <div v-if="!selectedRuntime" class="invoke-empty-runtime">
      <EmptyState title="未选择运行实例" />
    </div>

    <!-- Main two-column workspace -->
    <div v-else class="invoke-grid">
      <!-- Left: 输入 -->
      <section class="invoke-card">
        <div class="invoke-card__head">
          <h3>输入</h3>
          <TabList
            :model-value="inputTab"
            :tabs="inputTabs"
            label="输入格式"
            variant="underline"
            @update:model-value="switchInputTab"
          />
        </div>

        <!-- 表单模式 -->
        <div v-if="inputTab === 'form'" class="invoke-form-body">
          <div v-if="parsedContractInputs.length === 0" class="invoke-empty-sub">
            无输入参数
          </div>

          <div v-for="input in parsedContractInputs" :key="input.bindingId" class="invoke-input-group">
            <div class="invoke-input-label">
              <strong>{{ input.displayName }}</strong>
              <code class="invoke-binding-id">{{ input.bindingId }}</code>
              <span v-if="input.required" class="invoke-req">必填</span>
            </div>

            <!-- Image input -->
            <template v-if="input.payloadTypeId === 'image-ref.v1' || input.payloadTypeId === 'image-base64.v1'">
              <div class="invoke-radio-row">
                <label class="invoke-radio">
                  <input
                    v-model="getFormState(input.bindingId).imageMode"
                    type="radio"
                    value="upload"
                    :disabled="isInputLocked"
                  />
                  <span>{{ input.payloadTypeId === 'image-base64.v1' ? '上传并转 Base64' : '上传图像' }}</span>
                </label>
                <label class="invoke-radio">
                  <input
                    v-model="getFormState(input.bindingId).imageMode"
                    type="radio"
                    value="json"
                    :disabled="isInputLocked"
                  />
                  <span>使用 JSON 引用</span>
                </label>
              </div>

              <template v-if="getFormState(input.bindingId).imageMode === 'upload'">
                <input
                  :id="`invoke-file-${input.bindingId}`"
                  type="file"
                  accept="image/*"
                  class="invoke-hidden-file"
                  :disabled="isInputLocked"
                  @change="onImageFileChange(input.bindingId, $event)"
                />
                <div class="invoke-image-box">
                  <template v-if="getFormState(input.bindingId).file">
                    <img
                      v-if="getFormState(input.bindingId).previewUrl"
                      :src="getFormState(input.bindingId).previewUrl"
                      :alt="getFormState(input.bindingId).file?.name"
                      class="invoke-image-thumb"
                    />
                    <div class="invoke-image-meta">
                      <strong>{{ getFormState(input.bindingId).file?.name }}</strong>
                      <span>
                        {{ getFormState(input.bindingId).dimensions || '已选择图像' }}
                        · {{ formatFileSize(getFormState(input.bindingId).file?.size || 0) }}
                      </span>
                    </div>
                  </template>
                  <div v-else class="invoke-image-placeholder">
                    <span>尚未选择图像文件</span>
                  </div>
                  <label :for="`invoke-file-${input.bindingId}`" class="invoke-pick-btn">
                    <ImageIcon :size="14" />
                    {{ getFormState(input.bindingId).file ? '更换' : '选择图像' }}
                  </label>
                </div>
                <small v-if="submitMode === 'async' && input.payloadTypeId === 'image-ref.v1'" class="invoke-field-hint">
                  异步模式请改用 JSON 引用
                </small>
              </template>

              <template v-else>
                <textarea
                  v-model="getFormState(input.bindingId).jsonText"
                  rows="4"
                  spellcheck="false"
                  class="invoke-code-area"
                  :disabled="isInputLocked"
                  @input="syncFormFieldToPayload(input.bindingId)"
                />
              </template>
            </template>

            <!-- File inputs -->
            <template v-else-if="input.payloadTypeId === 'file-ref.v1' || input.payloadTypeId === 'file-refs.v1'">
              <input
                :id="`invoke-generic-file-${input.bindingId}`"
                type="file"
                class="invoke-hidden-file"
                :multiple="input.payloadTypeId === 'file-refs.v1'"
                :disabled="isInputLocked"
                @change="onGenericFilesChange(input.bindingId, $event)"
              />
              <div
                class="invoke-file-box"
                :class="{ 'is-dragover': fileDragOverBindingId === input.bindingId, 'is-disabled': isInputLocked }"
                @dragover.prevent="onGenericFilesDragOver(input.bindingId)"
                @dragleave.prevent="onGenericFilesDragLeave(input.bindingId)"
                @drop.prevent="onGenericFilesDrop(input.bindingId, input.payloadTypeId === 'file-refs.v1', $event)"
              >
                <div class="invoke-file-box__main">
                  <FileText :size="16" class="invoke-file-icon" />
                  <div v-if="getFormState(input.bindingId).files.length > 0" class="invoke-image-meta">
                    <strong :title="getFormState(input.bindingId).files.map((f) => f.name).join(', ')">
                      {{
                        getFormState(input.bindingId).files.length === 1
                          ? getFormState(input.bindingId).files[0]?.name
                          : `已选择 ${getFormState(input.bindingId).files.length} 个文件`
                      }}
                    </strong>
                    <span>
                      {{
                        formatFileSize(
                          getFormState(input.bindingId).files.reduce((sum, item) => sum + item.size, 0),
                        )
                      }}
                    </span>
                  </div>
                  <div v-else class="invoke-image-placeholder">
                    <span>点击或拖入文件</span>
                  </div>
                </div>
                <div class="invoke-file-box__actions">
                  <label
                    :for="`invoke-generic-file-${input.bindingId}`"
                    class="invoke-pick-btn"
                    :class="{ 'is-disabled': isInputLocked }"
                  >
                    <Upload :size="14" />
                    {{ getFormState(input.bindingId).files.length > 0 ? '更换' : '选择文件' }}
                  </label>
                  <button
                    v-if="getFormState(input.bindingId).files.length > 0"
                    type="button"
                    class="invoke-file-clear"
                    title="清除文件"
                    aria-label="清除文件"
                    :disabled="isInputLocked"
                    @click="clearGenericFiles(input.bindingId)"
                  >
                    <X :size="13" />
                  </button>
                </div>
              </div>
            </template>

            <!-- Text input -->
            <template v-else-if="input.payloadTypeId === 'text.v1'">
              <textarea
                v-model="getFormState(input.bindingId).textValue"
                rows="3"
                placeholder="输入文本内容"
                class="invoke-text-area"
                :disabled="isInputLocked"
                @input="syncTextFieldToPayload(input.bindingId)"
              />
            </template>

            <!-- Structured value / JSON parameter -->
            <template v-else>
              <textarea
                v-model="getFormState(input.bindingId).jsonText"
                rows="4"
                spellcheck="false"
                class="invoke-code-area"
                :disabled="isInputLocked"
                @input="syncFormFieldToPayload(input.bindingId)"
              />
            </template>
          </div>
        </div>

        <!-- JSON 模式 -->
        <div v-else class="invoke-form-body">
          <div class="invoke-json-toolbar">
            <SelectField
              v-if="hasImageRefInput"
              fit-options
              floating
              :model-value="imageRefSampleTransportKind"
              :options="imageRefTransportOptions"
              :disabled="isInputLocked"
              aria-label="image-ref 示例传输方式"
              @update:model-value="onTransportChange"
            />
            <Button variant="secondary" size="sm" :disabled="isInputLocked" @click="resetAllInputs">
              生成示例输入
            </Button>
          </div>

          <textarea
            v-model="runtimePayloadText"
            rows="11"
            spellcheck="false"
            class="invoke-code-area invoke-code-area--tall"
            :disabled="isInputLocked"
          />
        </div>

        <InlineError :message="formValidationError" />

        <div class="invoke-form-footer">
          <Button
            v-if="canWrite"
            variant="primary"
            :disabled="!canSubmitInvoke"
            :loading="isCurrentSubmitting"
            data-invoke-submit-btn
            @click="handleInvoke"
          >
            {{
              isCurrentSubmitting
                ? '调用中...'
                : submitMode === 'async'
                  ? '提交异步执行'
                  : '调用一次'
            }}
          </Button>
          <Button
            variant="secondary"
            :disabled="isCurrentSubmitting"
            data-invoke-reset-btn
            @click="resetAllInputs"
          >
            重置
          </Button>
        </div>
      </section>

      <!-- Right: 本次结果 / 本次执行 -->
      <section class="invoke-card">
        <div class="invoke-card__head invoke-card__head--split">
          <h3>{{ currentOutcome?.runningRun ? '本次执行' : '本次结果' }}</h3>
          <span
            v-if="currentOutcome?.run"
            class="invoke-result-badge"
            :class="`is-${runStateDotTone(currentOutcome.run.state)}`"
          >
            <i class="invoke-dot" />
            {{ formatRunDetailHeaderState(currentOutcome.run.state) }}
          </span>
        </div>

        <!-- 1. Idle -->
        <div v-if="!currentOutcome" class="invoke-empty-result">
          <FileText :size="36" class="invoke-empty-icon" />
          <strong>尚未调用</strong>
        </div>

        <!-- 2. Disconnect / Unknown sync receipt -->
        <div v-else-if="currentOutcome.unknownReceipt" class="invoke-unknown-state" data-invoke-unknown-result>
          <div class="invoke-unknown-icon">
            <AlertTriangle :size="34" />
          </div>
          <h4>结果待确认</h4>
          <p>
            连接中断，未收到调用结果。<br />
            当前未保存执行记录，无法查询本次结果。
          </p>
          <div class="invoke-unknown-actions">
            <Button variant="secondary" @click="emit('open-runtime-details', selectedRuntime)">
              查看实例状态
            </Button>
            <Button variant="secondary" data-invoke-prepare-new-btn @click="prepareConfirmOpen = true">
              准备新调用
            </Button>
          </div>
        </div>

        <!-- 3. Async / Pending Running -->
        <div v-else-if="currentOutcome.runningRun" class="invoke-running-state">
          <div class="invoke-running-spinner-row">
            <span class="invoke-spinner" aria-hidden="true" />
            <strong>{{ formatRunStateLabel(currentOutcome.runningRun.state) }}</strong>
          </div>

          <dl class="invoke-kv">
            <div>
              <dt>执行编号</dt>
              <dd class="invoke-mono-copy">
                <span>{{ currentOutcome.runningRun.workflow_run_id }}</span>
                <button
                  type="button"
                  class="invoke-copy-mini"
                  title="复制执行编号"
                  @click="copyText(currentOutcome.runningRun.workflow_run_id)"
                >
                  <Copy :size="12" />
                </button>
              </dd>
            </div>
            <div>
              <dt>提交时间</dt>
              <dd>{{ formatSystemDateTime(currentOutcome.runningRun.created_at) }}</dd>
            </div>
            <div>
              <dt>执行方式</dt>
              <dd>异步</dd>
            </div>
            <div>
              <dt>记录方式</dt>
              <dd>{{ formatRecordModeLabel(readRunRecordMode(currentOutcome.runningRun, selectedRuntime)) }}</dd>
            </div>
          </dl>

          <div class="invoke-running-actions">
            <Button
              variant="secondary"
              size="sm"
              :loading="fetchingRun"
              @click="refreshRunningRun(currentOutcome.runningRun)"
            >
              <RefreshCw v-if="!fetchingRun" :size="14" />
              刷新状态
            </Button>
            <Button
              v-if="canWrite"
              variant="secondary"
              size="sm"
              :disabled="cancellingRun"
              @click="cancelConfirmRun = currentOutcome.runningRun"
            >
              <XCircle :size="14" />
              取消执行
            </Button>
            <button
              type="button"
              class="invoke-link-btn"
              @click="emit('view-run-record', currentOutcome.runningRun)"
            >
              查看记录 ›
            </button>
          </div>
        </div>

        <!-- 4. Capacity full -->
        <div v-else-if="currentOutcome.capacityMessage" class="invoke-notice-box is-warn">
          <strong>实例当前满载</strong>
          <p>{{ currentOutcome.capacityMessage }}</p>
        </div>

        <!-- 5. Request / Validation error -->
        <div v-else-if="currentOutcome.errorMessage" class="invoke-notice-box is-bad">
          <strong>调用未完成</strong>
          <p>{{ currentOutcome.errorMessage }}</p>
        </div>

        <!-- 6. Terminal Run Result -->
        <div v-else-if="currentOutcome.run" class="invoke-done-state">
          <!-- Separated Business Outcome Banner -->
          <div
            v-if="terminalBusinessOutcome"
            class="invoke-biz-banner"
            :class="terminalBusinessOutcome === 'NG' ? 'is-ng' : 'is-ok'"
            data-invoke-biz-outcome
          >
            <span>业务结果</span>
            <strong>{{ terminalBusinessOutcome }}</strong>
          </div>

          <!-- Generic summary counters -->
          <div v-if="terminalMetrics.length > 0" class="invoke-metrics-grid">
            <div v-for="m in terminalMetrics" :key="m.label" class="invoke-metric-cell">
              <span>{{ m.label }}</span>
              <strong :class="`is-${m.tone}`">{{ m.value }}</strong>
            </div>
          </div>

          <TabList
            :model-value="resultTab"
            :tabs="resultTabs"
            label="结果视图"
            variant="underline"
            @update:model-value="(val) => (resultTab = val as 'result' | 'json')"
          />

          <div v-if="resultTab === 'result'" class="invoke-result-body">
            <div class="invoke-result-split">
              <div class="invoke-result-viewer">
                <WorkflowRuntimeBodyViewer
                  v-if="terminalBody"
                  :project-id="projectId"
                  :status-code="terminalStatusCode"
                  :body="terminalBody"
                />
                <div v-else-if="currentOutcome.run.error" class="invoke-err-detail">
                  <strong>{{ currentOutcome.run.error.code }}</strong>
                  <p>{{ currentOutcome.run.error.message }}</p>
                </div>
                <p v-else class="invoke-muted">无可渲染图像输出，请切换 JSON 查看完整结构。</p>
              </div>
              <dl class="invoke-meta-side">
                <div>
                  <dt>执行编号</dt>
                  <dd class="invoke-mono-copy">
                    <span>{{ shortRunId(currentOutcome.run.workflow_run_id) }}</span>
                    <button
                      type="button"
                      class="invoke-copy-mini"
                      title="复制完整执行编号"
                      @click="copyText(currentOutcome.run.workflow_run_id)"
                    >
                      <Copy :size="12" />
                    </button>
                  </dd>
                </div>
                <div>
                  <dt>执行时间</dt>
                  <dd>{{ formatSystemDateTime(currentOutcome.run.finished_at || currentOutcome.run.created_at) }}</dd>
                </div>
                <div>
                  <dt>耗时</dt>
                  <dd>{{ formatRunDuration(currentOutcome.run.started_at || currentOutcome.run.created_at, currentOutcome.run.finished_at) }}</dd>
                </div>
              </dl>
            </div>
          </div>

          <div v-else class="invoke-result-json">
            <p v-if="terminalJsonPreview.truncated" class="invoke-truncate-hint">
              JSON 共 {{ terminalJsonPreview.totalLines }} 行，当前仅显示前 {{ terminalJsonPreview.shownLines }} 行。
            </p>
            <pre class="invoke-json-pre">{{ terminalJsonPreview.text }}</pre>
          </div>

          <div class="invoke-result-footer">
            <Button variant="secondary" size="sm" @click="emit('view-run-record', currentOutcome.run)">
              查看记录
            </Button>
            <Button variant="secondary" size="sm" @click="copyResultJson">
              {{ resultCopyFeedback || '复制结果' }}
            </Button>
          </div>
        </div>
      </section>
    </div>

    <!-- Confirm: Prepare new invoke after unknown sync receipt -->
    <ConfirmDialog
      v-if="prepareConfirmOpen"
      title="准备新的调用？"
      cancel-label="返回检查"
      confirm-label="准备新调用"
      confirm-variant="primary"
      @cancel="prepareConfirmOpen = false"
      @confirm="confirmPrepareNewInvoke"
    >
      <div class="invoke-confirm-box">
        <div class="invoke-confirm-target">
          <span class="invoke-muted">运行实例</span>
          <strong>{{ selectedRuntime?.display_name || selectedRuntimeId }}</strong>
        </div>
        <p class="invoke-confirm-warn">上次调用可能已执行，再次调用可能重复保存或计数。</p>
        <p class="invoke-confirm-note">确认后仅准备输入，不会立即调用。</p>
      </div>
    </ConfirmDialog>

    <!-- Confirm: Cancel async execution -->
    <ConfirmDialog
      v-if="cancelConfirmRun"
      title="取消执行？"
      :message="`确定提交取消执行请求吗？编号 ${cancelConfirmRun.workflow_run_id}，最终状态以后端回执为准。`"
      confirm-label="确认取消执行"
      cancel-label="继续等待"
      confirm-variant="danger"
      :busy="cancellingRun"
      @cancel="cancelConfirmRun = null"
      @confirm="confirmCancelRun"
    />
  </div>
</template>

<script setup lang="ts">
import { AlertTriangle, Copy, FileText, Image as ImageIcon, RefreshCw, Upload, X, XCircle } from '@lucide/vue'
import { computed, reactive, ref, watch } from 'vue'

import { getErrorMessage } from '@/shared/api/error'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import TabList, { type TabListItem } from '@/shared/ui/navigation/TabList.vue'
import { useWorkflowResourceStream } from '../composables/useWorkflowResourceStream'
import { buildWorkflowRuntimeInputSample, type ImageRefSampleTransportKind } from '../runtime-input-samples'
import {
  cancelWorkflowRun,
  createWorkflowRun,
  getWorkflowRun,
  invokeWorkflowAppRuntime,
} from '../services/workflow-runtime.service'
import type {
  FlowApplication,
  FlowApplicationBinding,
  WorkflowAppRuntime,
  WorkflowGraphTemplate,
  WorkflowJsonObject,
  WorkflowRun,
} from '../types'
import {
  extractBusinessOutcome,
  extractRunMetrics,
  extractRunResponseBody,
  extractRunResponseStatusCode,
  formatBoundedJson,
  formatRecordModeLabel,
  formatRunDetailHeaderState,
  formatRunDuration,
  formatRunStateLabel,
  isCapacityError,
  isDisconnectOrUnknownReceiptError,
  isTerminalRunState,
  readRunRecordMode,
  readRuntimeRecordMode,
  runStateDotTone,
} from '../utils/workflow-run-display'
import type { WorkflowAppRequestExamples } from '../workflow-app-request-examples'
import WorkflowRuntimeBodyViewer from './WorkflowRuntimeBodyViewer.vue'

interface ParsedInputDef {
  bindingId: string
  displayName: string
  payloadTypeId: string
  required: boolean
}

interface FormFieldState {
  imageMode: 'upload' | 'json'
  file: File | null
  files: File[]
  previewUrl: string
  dimensions: string
  textValue: string
  jsonText: string
}

interface RuntimeOutcomeState {
  run: WorkflowRun | null
  runningRun: WorkflowRun | null
  unknownReceipt: boolean
  inputUnlockedAfterUnknown: boolean
  capacityMessage: string
  errorMessage: string
}

const props = defineProps<{
  projectId: string
  applicationId: string
  application: FlowApplication | null
  graph: WorkflowGraphTemplate | null
  runtimes: WorkflowAppRuntime[]
  selectedRuntimeId: string
  selectedRuntimeVersionLabel: string
  contract: WorkflowJsonObject | null
  canWrite: boolean
  requestExamples: WorkflowAppRequestExamples | null
}>()

const emit = defineEmits<{
  'select-runtime': [runtimeId: string]
  'open-examples': []
  'open-runtime-config': [runtime: WorkflowAppRuntime]
  'open-runtime-details': [runtime: WorkflowAppRuntime]
  'view-run-record': [run: WorkflowRun]
  'run-completed': [run: WorkflowRun]
}>()

const submitMode = ref<'sync' | 'async'>('sync')
const inputTab = ref<'form' | 'json'>('form')
const resultTab = ref<'result' | 'json'>('result')
const imageRefSampleTransportKind = ref<ImageRefSampleTransportKind>('storage')
const runtimePayloadText = ref('{}')
const formStates = reactive<Record<string, FormFieldState>>({})
const formValidationError = ref<string | null>(null)
const submittingRuntimeId = ref<string | null>(null)
const fetchingRun = ref(false)
const cancellingRun = ref(false)
const prepareConfirmOpen = ref(false)
const cancelConfirmRun = ref<WorkflowRun | null>(null)
const resultCopyFeedback = ref('')
const fileDragOverBindingId = ref<string | null>(null)

// 按实例隔离调用结果，防止切实例时污染其它实例的结果面板
const outcomesByRuntimeId = ref<Record<string, RuntimeOutcomeState>>({})
const latestInvokeTokenByRuntimeId = ref<Record<string, number>>({})
let nextInvokeToken = 1

const inputTabs: TabListItem[] = [
  { id: 'form', label: '表单' },
  { id: 'json', label: 'JSON' },
]

const resultTabs: TabListItem[] = [
  { id: 'result', label: '结果' },
  { id: 'json', label: 'JSON' },
]

const imageRefTransportOptions = [
  { value: 'storage', label: '对象存储引用 (storage)' },
  { value: 'local-path', label: '服务端本地路径 (local-path)' },
]

const selectedRuntime = computed(
  () => props.runtimes.find((rt) => rt.workflow_runtime_id === props.selectedRuntimeId) ?? null,
)

const runtimeOptions = computed(() =>
  props.runtimes.map((rt) => ({
    value: rt.workflow_runtime_id,
    label: rt.display_name || rt.workflow_runtime_id,
  })),
)

const recordMode = computed(() => readRuntimeRecordMode(selectedRuntime.value))

const runtimeDotTone = computed(() => {
  const s = selectedRuntime.value?.observed_state ?? ''
  if (s === 'running') return 'ok'
  if (s === 'failed') return 'bad'
  if (s === 'starting' || s === 'stopping') return 'warn'
  return 'neutral'
})

const runtimeStateText = computed(() => {
  const s = selectedRuntime.value?.observed_state ?? ''
  if (s === 'running') return '运行中'
  if (s === 'stopped' || s === 'created') return '已停止'
  if (s === 'starting') return '启动中'
  if (s === 'stopping') return '停止中'
  if (s === 'failed') return '异常'
  return s || '未知'
})

const parsedContractInputs = computed<ParsedInputDef[]>(() => {
  const contractInputs = props.contract?.inputs
  if (Array.isArray(contractInputs)) {
    return contractInputs
      .filter((item): item is WorkflowJsonObject => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
      .map((item) => {
        const bindingId = typeof item.binding_id === 'string' ? item.binding_id : ''
        const displayName =
          (typeof item.display_name === 'string' && item.display_name.trim())
          || (typeof item.title === 'string' && item.title.trim())
          || bindingId
        const payloadTypeId = typeof item.payload_type_id === 'string' ? item.payload_type_id : 'value.v1'
        return {
          bindingId,
          displayName,
          payloadTypeId,
          required: item.required !== false,
        }
      })
      .filter((item) => Boolean(item.bindingId))
  }
  const templateInputs = new Map((props.graph?.template_inputs ?? []).map((i) => [i.input_id, i]))
  return (props.application?.bindings ?? [])
    .filter((b: FlowApplicationBinding) => b.direction === 'input')
    .map((b: FlowApplicationBinding) => {
      const meta = b.metadata ?? {}
      const tpl = templateInputs.get(b.template_port_id)
      const payloadTypeId =
        (typeof b.config.payload_type_id === 'string' && b.config.payload_type_id)
        || (typeof meta.payload_type_id === 'string' && meta.payload_type_id)
        || tpl?.payload_type_id
        || 'value.v1'
      const displayName =
        (typeof meta.display_name === 'string' && meta.display_name.trim())
        || b.binding_id
      return {
        bindingId: b.binding_id,
        displayName,
        payloadTypeId,
        required: b.required,
      }
    })
})

const hasImageRefInput = computed(() =>
  parsedContractInputs.value.some((i) => i.payloadTypeId === 'image-ref.v1' || i.bindingId === 'request_image_ref'),
)

const isCurrentSubmitting = computed(
  () => Boolean(selectedRuntime.value && submittingRuntimeId.value === selectedRuntime.value.workflow_runtime_id),
)

const currentOutcome = computed<RuntimeOutcomeState | null>(() => {
  const rid = props.selectedRuntimeId
  return rid ? outcomesByRuntimeId.value[rid] ?? null : null
})

const isInputLocked = computed(() => {
  if (isCurrentSubmitting.value) return true
  if (currentOutcome.value?.unknownReceipt && !currentOutcome.value.inputUnlockedAfterUnknown) {
    return true
  }
  return false
})

const canSubmitInvoke = computed(() => {
  if (!props.canWrite || !selectedRuntime.value || isInputLocked.value) return false
  if (submitMode.value === 'async' && recordMode.value === 'none') return false
  return true
})

const terminalBusinessOutcome = computed(() => extractBusinessOutcome(currentOutcome.value?.run))
const terminalMetrics = computed(() => extractRunMetrics(currentOutcome.value?.run))
const terminalBody = computed(() => extractRunResponseBody(currentOutcome.value?.run))
const terminalStatusCode = computed(() => extractRunResponseStatusCode(currentOutcome.value?.run))
const terminalJsonPreview = computed(() =>
  formatBoundedJson(
    currentOutcome.value?.run
      ? {
          workflow_run_id: currentOutcome.value.run.workflow_run_id,
          state: currentOutcome.value.run.state,
          outputs: currentOutcome.value.run.outputs,
          template_outputs: currentOutcome.value.run.template_outputs,
          error: currentOutcome.value.run.error,
          metadata: currentOutcome.value.run.metadata,
        }
      : {},
  ),
)

function getFormState(bindingId: string): FormFieldState {
  if (!formStates[bindingId]) {
    formStates[bindingId] = {
      imageMode: 'upload',
      file: null,
      files: [],
      previewUrl: '',
      dimensions: '',
      textValue: '',
      jsonText: '{}',
    }
  }
  return formStates[bindingId]
}

function buildSamplePayloadObject(): WorkflowJsonObject {
  const sample: WorkflowJsonObject = {}
  for (const input of parsedContractInputs.value) {
    sample[input.bindingId] = buildWorkflowRuntimeInputSample(
      input.payloadTypeId,
      input.bindingId,
      imageRefSampleTransportKind.value,
    )
  }
  return sample
}

function populateFormFromPayload(payload: WorkflowJsonObject): void {
  for (const input of parsedContractInputs.value) {
    const state = getFormState(input.bindingId)
    const val = payload[input.bindingId]
    if (input.payloadTypeId === 'text.v1' && val && typeof val === 'object' && !Array.isArray(val)) {
      const t = (val as WorkflowJsonObject).text
      state.textValue = typeof t === 'string' ? t : ''
    }
    state.jsonText = JSON.stringify(val ?? {}, null, 2)
  }
}

function resetAllInputs(): void {
  formValidationError.value = null
  const sample = buildSamplePayloadObject()
  runtimePayloadText.value = JSON.stringify(sample, null, 2)
  for (const key of Object.keys(formStates)) {
    const st = formStates[key]
    if (st.previewUrl) URL.revokeObjectURL(st.previewUrl)
    st.file = null
    st.files = []
    st.previewUrl = ''
    st.dimensions = ''
  }
  populateFormFromPayload(sample)
}

watch(
  () => [props.applicationId, props.contract, parsedContractInputs.value.length] as const,
  () => {
    resetAllInputs()
  },
  { immediate: true },
)

watch(recordMode, (nextMode) => {
  if (nextMode === 'none' && submitMode.value === 'async') {
    submitMode.value = 'sync'
  }
})

function selectAsyncMode(): void {
  if (recordMode.value === 'none') return
  submitMode.value = 'async'
}

function onTransportChange(val: string | number | boolean | null): void {
  imageRefSampleTransportKind.value = val === 'local-path' ? 'local-path' : 'storage'
  resetAllInputs()
}

function switchInputTab(nextTab: string): void {
  formValidationError.value = null
  if (nextTab === 'json') {
    inputTab.value = 'json'
    return
  }
  try {
    const parsed = JSON.parse(runtimePayloadText.value || '{}') as unknown
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      populateFormFromPayload(parsed as WorkflowJsonObject)
    }
  } catch {
    formValidationError.value = 'JSON 语法格式有误，请修正后再切换。'
    return
  }
  inputTab.value = 'form'
}

function syncFormFieldToPayload(bindingId: string): void {
  try {
    const current = JSON.parse(runtimePayloadText.value || '{}') as Record<string, unknown>
    const fieldJson = JSON.parse(getFormState(bindingId).jsonText || '{}') as unknown
    current[bindingId] = fieldJson
    runtimePayloadText.value = JSON.stringify(current, null, 2)
    formValidationError.value = null
  } catch {
    // Wait until user finishes typing valid JSON
  }
}

function syncTextFieldToPayload(bindingId: string): void {
  try {
    const current = JSON.parse(runtimePayloadText.value || '{}') as Record<string, unknown>
    current[bindingId] = {
      text: getFormState(bindingId).textValue,
      media_type: 'text/plain',
      charset: 'utf-8',
    }
    runtimePayloadText.value = JSON.stringify(current, null, 2)
  } catch {
    // ignore
  }
}

function onImageFileChange(bindingId: string, event: Event): void {
  const inputEl = event.target as HTMLInputElement | null
  const file = inputEl?.files?.[0] ?? null
  const st = getFormState(bindingId)
  if (st.previewUrl) URL.revokeObjectURL(st.previewUrl)
  st.file = file
  st.dimensions = ''
  if (file) {
    const url = URL.createObjectURL(file)
    st.previewUrl = url
    const img = new Image()
    img.onload = () => {
      st.dimensions = `${img.naturalWidth} × ${img.naturalHeight}`
    }
    img.src = url
  } else {
    st.previewUrl = ''
  }
}

function onGenericFilesChange(bindingId: string, event: Event): void {
  const inputEl = event.target as HTMLInputElement | null
  const files = Array.from(inputEl?.files ?? [])
  if (inputEl) inputEl.value = ''
  const st = getFormState(bindingId)
  st.files = files
  st.file = files[0] ?? null
}

function onGenericFilesDragOver(bindingId: string): void {
  if (!isInputLocked.value) fileDragOverBindingId.value = bindingId
}

function onGenericFilesDragLeave(bindingId: string): void {
  if (fileDragOverBindingId.value === bindingId) fileDragOverBindingId.value = null
}

function onGenericFilesDrop(bindingId: string, multiple: boolean, event: DragEvent): void {
  fileDragOverBindingId.value = null
  if (isInputLocked.value) return
  const dropped = Array.from(event.dataTransfer?.files ?? [])
  if (dropped.length === 0) return
  const files = multiple ? dropped : dropped.slice(0, 1)
  const st = getFormState(bindingId)
  st.files = files
  st.file = files[0] ?? null
}

function clearGenericFiles(bindingId: string): void {
  const st = getFormState(bindingId)
  st.files = []
  st.file = null
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result ?? '')
      const comma = result.indexOf(',')
      resolve(comma >= 0 ? result.slice(comma + 1) : result)
    }
    reader.onerror = () => reject(new Error('读取图像文件失败'))
    reader.readAsDataURL(file)
  })
}

async function buildInvokePayload(): Promise<{
  inputBindings: WorkflowJsonObject
  fileUploads: Array<{ bindingId: string; file: File }>
}> {
  let rawObj: Record<string, unknown>
  try {
    const parsed = JSON.parse(runtimePayloadText.value || '{}') as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('输入绑定必须为 JSON 对象')
    }
    const parsedObj = parsed as Record<string, unknown>
    rawObj = isPlainObject(parsedObj.input_bindings) ? { ...parsedObj.input_bindings } : { ...parsedObj }
  } catch (err) {
    throw new Error(err instanceof Error ? err.message : '输入 JSON 格式无效，请检查后重试。')
  }

  const fileUploads: Array<{ bindingId: string; file: File }> = []
  if (inputTab.value === 'form') {
    for (const input of parsedContractInputs.value) {
      const st = getFormState(input.bindingId)
      if (input.payloadTypeId === 'image-ref.v1' || input.payloadTypeId === 'image-base64.v1') {
        if (st.imageMode === 'upload' && st.file) {
          if (input.payloadTypeId === 'image-base64.v1') {
            rawObj[input.bindingId] = {
              image_base64: await fileToBase64(st.file),
              media_type: st.file.type || 'image/png',
            }
          } else {
            if (submitMode.value === 'async') {
              throw new Error(`异步提交不支持文件直传，请将“${input.displayName}”切换为 JSON 引用。`)
            }
            delete rawObj[input.bindingId]
            fileUploads.push({ bindingId: input.bindingId, file: st.file })
          }
          continue
        }
        try {
          rawObj[input.bindingId] = JSON.parse(st.jsonText || '{}') as unknown
        } catch {
          throw new Error(`参数“${input.displayName}”的 JSON 格式有误。`)
        }
      } else if (input.payloadTypeId === 'file-ref.v1' || input.payloadTypeId === 'file-refs.v1') {
        if (st.files.length > 0) {
          if (submitMode.value === 'async') {
            throw new Error(`异步提交不支持多文件表单直传，请切至 JSON 输入。`)
          }
          delete rawObj[input.bindingId]
          for (const f of st.files) fileUploads.push({ bindingId: input.bindingId, file: f })
        }
      } else if (input.payloadTypeId === 'text.v1') {
        rawObj[input.bindingId] = {
          text: st.textValue,
          media_type: 'text/plain',
          charset: 'utf-8',
        }
      } else {
        try {
          rawObj[input.bindingId] = JSON.parse(st.jsonText || '{}') as unknown
        } catch {
          throw new Error(`参数“${input.displayName}”的 JSON 格式有误。`)
        }
      }
    }
  }

  return {
    inputBindings: rawObj as WorkflowJsonObject,
    fileUploads,
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function setOutcome(runtimeId: string, state: RuntimeOutcomeState): void {
  outcomesByRuntimeId.value = {
    ...outcomesByRuntimeId.value,
    [runtimeId]: state,
  }
}

const workflowRunStream = useWorkflowResourceStream<WorkflowRun>({
  kind: 'run',
  getSnapshot: getWorkflowRun,
  onSnapshot: (run) => {
    const rid = run.workflow_runtime_id
    if (isTerminalRunState(run.state)) {
      setOutcome(rid, {
        run,
        runningRun: null,
        unknownReceipt: false,
        inputUnlockedAfterUnknown: false,
        capacityMessage: '',
        errorMessage: '',
      })
      emit('run-completed', run)
    } else {
      setOutcome(rid, {
        run: null,
        runningRun: run,
        unknownReceipt: false,
        inputUnlockedAfterUnknown: false,
        capacityMessage: '',
        errorMessage: '',
      })
    }
  },
  isTerminal: (snapshot) => isTerminalRunState(snapshot.state),
})

async function handleInvoke(): Promise<void> {
  const runtime = selectedRuntime.value
  if (!runtime || !canSubmitInvoke.value) return
  formValidationError.value = null

  let built: { inputBindings: WorkflowJsonObject; fileUploads: Array<{ bindingId: string; file: File }> }
  try {
    built = await buildInvokePayload()
  } catch (err) {
    formValidationError.value = err instanceof Error ? err.message : '输入参数校验失败'
    return
  }

  const runtimeId = runtime.workflow_runtime_id
  const modeAtSubmit = submitMode.value
  const modeRecordAtSubmit = recordMode.value
  const token = nextInvokeToken++
  latestInvokeTokenByRuntimeId.value = {
    ...latestInvokeTokenByRuntimeId.value,
    [runtimeId]: token,
  }
  submittingRuntimeId.value = runtimeId

  try {
    const run =
      modeAtSubmit === 'async'
        ? await createWorkflowRun(runtimeId, {
            inputBindings: built.inputBindings,
            executionMetadata: { source: 'web-ui-app-detail' },
          })
        : await invokeWorkflowAppRuntime(runtimeId, {
            inputBindings: built.inputBindings,
            fileUploads: built.fileUploads,
            executionMetadata: { source: 'web-ui-app-detail' },
          })

    // 防止过期回调覆盖更新后的一次调用状态
    if (latestInvokeTokenByRuntimeId.value[runtimeId] !== token) return

    if (!isTerminalRunState(run.state)) {
      setOutcome(runtimeId, {
        run: null,
        runningRun: run,
        unknownReceipt: false,
        inputUnlockedAfterUnknown: false,
        capacityMessage: '',
        errorMessage: '',
      })
      workflowRunStream.start(run.workflow_run_id)
    } else {
      setOutcome(runtimeId, {
        run,
        runningRun: null,
        unknownReceipt: false,
        inputUnlockedAfterUnknown: false,
        capacityMessage: '',
        errorMessage: '',
      })
      emit('run-completed', run)
    }
  } catch (error) {
    if (latestInvokeTokenByRuntimeId.value[runtimeId] !== token) return
    if (isCapacityError(error)) {
      setOutcome(runtimeId, {
        run: null,
        runningRun: null,
        unknownReceipt: false,
        inputUnlockedAfterUnknown: false,
        capacityMessage: '实例容量已满，未自动排队或重试，请稍后手动重试。',
        errorMessage: '',
      })
    } else if (modeAtSubmit === 'sync' && modeRecordAtSubmit === 'none' && isDisconnectOrUnknownReceiptError(error)) {
      setOutcome(runtimeId, {
        run: null,
        runningRun: null,
        unknownReceipt: true,
        inputUnlockedAfterUnknown: false,
        capacityMessage: '',
        errorMessage: '',
      })
    } else {
      setOutcome(runtimeId, {
        run: null,
        runningRun: null,
        unknownReceipt: false,
        inputUnlockedAfterUnknown: false,
        capacityMessage: '',
        errorMessage: getErrorMessage(error),
      })
    }
  } finally {
    if (submittingRuntimeId.value === runtimeId) {
      submittingRuntimeId.value = null
    }
  }
}

async function refreshRunningRun(run: WorkflowRun): Promise<void> {
  fetchingRun.value = true
  try {
    const latest = await getWorkflowRun(run.workflow_run_id)
    if (isTerminalRunState(latest.state)) {
      setOutcome(latest.workflow_runtime_id, {
        run: latest,
        runningRun: null,
        unknownReceipt: false,
        inputUnlockedAfterUnknown: false,
        capacityMessage: '',
        errorMessage: '',
      })
      emit('run-completed', latest)
    } else {
      setOutcome(latest.workflow_runtime_id, {
        run: null,
        runningRun: latest,
        unknownReceipt: false,
        inputUnlockedAfterUnknown: false,
        capacityMessage: '',
        errorMessage: '',
      })
    }
  } catch (err) {
    formValidationError.value = getErrorMessage(err)
  } finally {
    fetchingRun.value = false
  }
}

async function confirmCancelRun(): Promise<void> {
  const run = cancelConfirmRun.value
  if (!run || cancellingRun.value) return
  cancellingRun.value = true
  try {
    const updated = await cancelWorkflowRun(run.workflow_run_id)
    const existing = outcomesByRuntimeId.value[run.workflow_runtime_id]
    // 竞态保护：如果取消返回前终态已到达（如 succeeded），不得用非成功状态覆盖
    if (existing?.run && isTerminalRunState(existing.run.state) && existing.run.workflow_run_id === run.workflow_run_id) {
      cancelConfirmRun.value = null
      return
    }
    setOutcome(updated.workflow_runtime_id, {
      run: isTerminalRunState(updated.state) ? updated : null,
      runningRun: isTerminalRunState(updated.state) ? null : updated,
      unknownReceipt: false,
      inputUnlockedAfterUnknown: false,
      capacityMessage: '',
      errorMessage: '',
    })
    if (isTerminalRunState(updated.state)) emit('run-completed', updated)
    cancelConfirmRun.value = null
  } catch (err) {
    formValidationError.value = getErrorMessage(err)
    cancelConfirmRun.value = null
  } finally {
    cancellingRun.value = false
  }
}

function confirmPrepareNewInvoke(): void {
  const rid = props.selectedRuntimeId
  const cur = outcomesByRuntimeId.value[rid]
  if (cur) {
    setOutcome(rid, {
      ...cur,
      inputUnlockedAfterUnknown: true,
    })
  }
  prepareConfirmOpen.value = false
}

function shortRunId(id: string): string {
  return id.length > 22 ? `${id.slice(0, 12)}…${id.slice(-6)}` : id
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // ignore
  }
}

async function copyResultJson(): Promise<void> {
  if (!currentOutcome.value?.run) return
  try {
    await navigator.clipboard.writeText(terminalJsonPreview.value.fullText)
    resultCopyFeedback.value = '已复制'
    window.setTimeout(() => {
      resultCopyFeedback.value = ''
    }, 1600)
  } catch {
    // ignore
  }
}
</script>

<style scoped>
.invoke-panel {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.invoke-context-card {
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  padding: 12px 16px;
  display: grid;
  gap: 10px;
}

.invoke-context-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 14px;
}

.invoke-context-row--sub {
  padding-top: 10px;
  border-top: 1px solid var(--am-border);
  justify-content: flex-start;
}

.invoke-context-left,
.invoke-context-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.invoke-label {
  display: inline-flex;
  align-items: center;
  font-size: 13px;
  line-height: 1;
  color: var(--am-text-muted);
}

.invoke-runtime-select {
  display: inline-flex;
  align-items: center;
  min-width: 220px;
}

.invoke-runtime-select :deep(.ui-select__button) {
  min-height: 32px;
  height: 32px;
  padding: 0 10px;
  font-size: 13px;
  line-height: 1;
}

.invoke-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  line-height: 1;
  font-weight: 500;
}

.invoke-status-pill.is-ok .invoke-dot {
  background: var(--am-action-primary);
}

.invoke-status-pill.is-bad {
  color: #dc2626;
}

.invoke-status-pill.is-bad .invoke-dot {
  background: #dc2626;
}

.invoke-status-pill.is-warn .invoke-dot {
  background: #f59e0b;
}

.invoke-status-pill.is-neutral {
  color: var(--am-text-muted);
}

.invoke-status-pill.is-neutral .invoke-dot {
  background: var(--am-text-muted);
}

.invoke-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.invoke-sep {
  display: inline-flex;
  align-items: center;
  line-height: 1;
  color: var(--am-border);
}

.invoke-muted {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  line-height: 1;
  color: var(--am-text-muted);
}

.invoke-muted strong {
  color: var(--am-text-strong);
}

.invoke-link-btn {
  display: inline-flex;
  align-items: center;
  border: none;
  background: transparent;
  padding: 0;
  font-size: 13px;
  line-height: 1;
  font-weight: 500;
  color: var(--am-action-primary);
  cursor: pointer;
}

.invoke-link-btn:hover {
  text-decoration: underline;
}

.invoke-mode-toggle {
  display: inline-flex;
  align-items: center;
  padding: 2px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface-soft);
}

.invoke-mode-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 56px;
  height: 28px;
  border: none;
  border-radius: 5px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 500;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
  transition: background-color 120ms ease, color 120ms ease;
}

.invoke-mode-btn:hover:not(.is-active):not(:disabled) {
  color: var(--am-text);
}

.invoke-mode-btn.is-active {
  background: var(--am-surface);
  color: var(--am-text-strong);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.invoke-mode-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.invoke-async-warn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: var(--am-radius-sm);
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
  font-size: 12px;
}

.invoke-async-warn__text {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.invoke-async-warn__text strong {
  font-weight: 600;
}

.invoke-record-pill {
  margin-left: auto;
  font-size: 12px;
  color: var(--am-text-muted);
}

.invoke-empty-runtime {
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  padding: 28px;
}

.invoke-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
  align-items: stretch;
}

@media (max-width: 1024px) {
  .invoke-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.invoke-card {
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  padding: 16px 18px;
  display: grid;
  gap: 14px;
  min-width: 0;
  min-height: 280px;
  align-content: start;
}

.invoke-card__head {
  display: grid;
  gap: 10px;
}

.invoke-card__head--split {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.invoke-card__head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.invoke-form-body {
  display: grid;
  gap: 14px;
}

.invoke-empty-sub {
  padding: 20px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--am-text-muted);
}

.invoke-input-group {
  display: grid;
  gap: 8px;
}

.invoke-input-label {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 13px;
}

.invoke-binding-id {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 11px;
}

.invoke-req {
  font-size: 11px;
  font-weight: 600;
  color: #d97706;
}

.invoke-radio-row {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 13px;
}

.invoke-radio {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.invoke-hidden-file {
  display: none;
}

.invoke-image-box {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
}

.invoke-file-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px dashed var(--am-border-strong);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
  transition: border-color 140ms ease, background-color 140ms ease;
}

.invoke-file-box.is-dragover {
  border-color: var(--am-action-primary);
  background: var(--am-action-soft);
}

.invoke-file-box.is-disabled {
  opacity: 0.65;
}

.invoke-file-box__main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1 1 auto;
}

.invoke-file-icon {
  flex: none;
  color: var(--am-text-muted);
}

.invoke-file-box__actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
}

.invoke-pick-btn.is-disabled {
  pointer-events: none;
  opacity: 0.6;
}

.invoke-file-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface);
  color: var(--am-text-muted);
  cursor: pointer;
}

.invoke-file-clear:hover:not(:disabled) {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.invoke-image-thumb {
  width: 72px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--am-border);
}

.invoke-image-meta,
.invoke-image-placeholder {
  flex: 1 1 auto;
  min-width: 0;
  display: grid;
  gap: 2px;
  font-size: 12px;
  color: var(--am-text-muted);
}

.invoke-image-meta strong {
  color: var(--am-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.invoke-pick-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface);
  color: var(--am-text-strong);
  font-size: 12px;
  cursor: pointer;
  flex: none;
}

.invoke-pick-btn:hover {
  background: var(--am-hover-surface);
}

.invoke-field-hint {
  font-size: 12px;
  color: var(--am-text-muted);
}

.invoke-text-area,
.invoke-code-area {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  padding: 9px 11px;
  background: var(--am-input);
  color: var(--am-text-strong);
  font-size: 12px;
  resize: vertical;
}

.invoke-code-area {
  font-family: var(--am-font-mono, ui-monospace, monospace);
}

.invoke-code-area--tall {
  min-height: 220px;
}

.invoke-json-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.invoke-form-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 4px;
}

.invoke-result-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.invoke-result-badge.is-ok {
  background: var(--am-row-selected);
  color: var(--am-action-primary);
}

.invoke-result-badge.is-bad {
  background: rgba(220, 38, 38, 0.12);
  color: #dc2626;
}

.invoke-result-badge.is-warn {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.invoke-result-badge.is-neutral {
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
}

.invoke-empty-result,
.invoke-unknown-state {
  padding: 48px 18px;
  text-align: center;
  display: grid;
  justify-items: center;
  gap: 8px;
}

.invoke-empty-icon {
  color: var(--am-text-muted);
  opacity: 0.45;
}

.invoke-empty-result strong,
.invoke-unknown-state h4 {
  margin: 0;
  font-size: 15px;
  color: var(--am-text-strong);
}

.invoke-empty-result p,
.invoke-unknown-state p {
  margin: 0;
  font-size: 13px;
  color: var(--am-text-muted);
  line-height: 1.5;
}

.invoke-unknown-icon {
  color: #d97706;
}

.invoke-unknown-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

.invoke-running-state {
  display: grid;
  gap: 16px;
  padding: 12px 0;
}

.invoke-running-spinner-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 18px;
  font-size: 15px;
}

.invoke-spinner {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2.5px solid var(--am-border);
  border-top-color: var(--am-action-primary);
  animation: invoke-spin 0.9s linear infinite;
}

@keyframes invoke-spin {
  to {
    transform: rotate(360deg);
  }
}

.invoke-kv {
  margin: 0;
  display: grid;
  gap: 4px;
}

.invoke-kv > div {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  gap: 10px;
  font-size: 13px;
  padding: 4px 0;
}

.invoke-kv dt {
  color: var(--am-text-muted);
}

.invoke-kv dd {
  margin: 0;
  color: var(--am-text-strong);
}

.invoke-mono-copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 12px;
}

.invoke-copy-mini {
  border: none;
  background: transparent;
  padding: 2px;
  color: var(--am-text-muted);
  cursor: pointer;
}

.invoke-running-actions,
.invoke-result-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding-top: 6px;
  border-top: 1px solid var(--am-border);
}

.invoke-notice-box {
  padding: 14px 16px;
  border-radius: var(--am-radius-sm);
  display: grid;
  gap: 4px;
  font-size: 13px;
}

.invoke-notice-box.is-warn {
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
}

.invoke-notice-box.is-bad {
  background: rgba(220, 38, 38, 0.08);
  color: #dc2626;
}

.invoke-notice-box p {
  margin: 0;
}

.invoke-done-state {
  display: grid;
  gap: 12px;
}

.invoke-biz-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 14px;
  border-radius: var(--am-radius-sm);
  font-size: 13px;
}

.invoke-biz-banner.is-ok {
  background: var(--am-row-selected);
  color: var(--am-action-primary);
}

.invoke-biz-banner.is-ng {
  background: rgba(220, 38, 38, 0.1);
  color: #dc2626;
}

.invoke-metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  text-align: center;
}

.invoke-metric-cell {
  display: grid;
  gap: 2px;
}

.invoke-metric-cell span {
  font-size: 12px;
  color: var(--am-text-muted);
}

.invoke-metric-cell strong {
  font-size: 18px;
}

.invoke-metric-cell strong.is-ok {
  color: var(--am-action-primary);
}

.invoke-metric-cell strong.is-bad {
  color: #dc2626;
}

.invoke-result-split {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(160px, 1fr);
  gap: 12px;
  align-items: start;
}

@media (max-width: 1200px) {
  .invoke-result-split {
    grid-template-columns: minmax(0, 1fr);
  }
}

.invoke-meta-side {
  margin: 0;
  display: grid;
  gap: 8px;
  font-size: 12px;
}

.invoke-meta-side dt {
  color: var(--am-text-muted);
  margin-bottom: 2px;
}

.invoke-meta-side dd {
  margin: 0;
  color: var(--am-text-strong);
}

.invoke-err-detail {
  padding: 12px;
  border-radius: var(--am-radius-sm);
  background: rgba(220, 38, 38, 0.06);
  color: #dc2626;
  font-size: 12px;
}

.invoke-err-detail p {
  margin: 4px 0 0;
}

.invoke-truncate-hint {
  margin: 0 0 6px;
  font-size: 12px;
  color: #d97706;
}

.invoke-json-pre {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 12px;
  max-height: 300px;
  overflow: auto;
}

.invoke-confirm-box {
  display: grid;
  gap: 10px;
}

.invoke-confirm-target {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
  font-size: 13px;
}

.invoke-confirm-warn {
  margin: 0;
  font-size: 13px;
  color: var(--am-text-strong);
}

.invoke-confirm-note {
  margin: 0;
  font-size: 12px;
  color: var(--am-text-muted);
}
</style>
