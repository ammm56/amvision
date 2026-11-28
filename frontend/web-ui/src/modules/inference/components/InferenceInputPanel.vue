<template>
  <aside class="inf-input-card">
    <header class="inf-input-card__head">
      <h2>输入参数</h2>
    </header>

    <div class="inf-input-card__body">
      <div class="inf-field">
        <span class="inf-field__label">输入来源</span>
        <SelectField
          :model-value="sourceMode"
          :options="sourceOptions"
          :disabled="disabled"
          aria-label="输入来源"
          @update:model-value="handleSourceSelect"
        />
      </div>

      <div v-if="sourceMode === 'upload'" class="inf-source-block">
        <input
          ref="fileInputRef"
          type="file"
          accept="image/*"
          class="inf-hidden-input"
          @change="handleFileInputChange"
        />

        <div
          v-if="!uploadedFile"
          class="inf-dropzone"
          :class="{ 'is-dragover': isDragging, 'is-disabled': disabled }"
          role="button"
          tabindex="0"
          @click="triggerFileBrowse"
          @keydown.enter.prevent="triggerFileBrowse"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="handleFileDrop"
        >
          <ImageIcon :size="26" class="inf-dropzone__icon" />
          <span class="inf-dropzone__text">选择或拖入图片</span>
          <Button size="sm" variant="secondary" :disabled="disabled" @click.stop="triggerFileBrowse">
            选择文件
          </Button>
        </div>

        <div v-else class="inf-selected-file">
          <div class="inf-selected-file__thumb">
            <img v-if="previewThumbUrl" :src="previewThumbUrl" :alt="uploadedFile.name" />
            <ImageIcon v-else :size="18" />
          </div>
          <div class="inf-selected-file__meta">
            <strong :title="uploadedFile.name">{{ uploadedFile.name }}</strong>
            <span>{{ formatFileMeta(uploadedFile.size, imageWidth, imageHeight) }}</span>
          </div>
          <div class="inf-selected-file__actions">
            <button type="button" class="inf-mini-btn" :disabled="disabled" @click="triggerFileBrowse">
              更换
            </button>
            <button type="button" class="inf-mini-btn" :disabled="disabled" @click="clearUploadedFile">
              移除
            </button>
          </div>
        </div>
      </div>

      <div v-else-if="sourceMode === 'existing'" class="inf-source-block">
        <div v-if="!selectedFileLabel" class="inf-dropzone" @click="pickerOpen = true">
          <FolderOpen :size="24" class="inf-dropzone__icon" />
          <span class="inf-dropzone__text">从项目文件或数据集选择</span>
          <Button size="sm" variant="secondary" :disabled="disabled" @click.stop="pickerOpen = true">
            选择图片
          </Button>
        </div>

        <div v-else class="inf-selected-file">
          <div class="inf-selected-file__thumb">
            <img v-if="previewThumbUrl" :src="previewThumbUrl" :alt="selectedFileLabel" />
            <ImageIcon v-else :size="18" />
          </div>
          <div class="inf-selected-file__meta">
            <strong :title="selectedFileLabel">{{ selectedFileLabel }}</strong>
            <span>{{ formatFileMeta(selectedFileSizeBytes, imageWidth, imageHeight) }}</span>
          </div>
          <div class="inf-selected-file__actions">
            <button type="button" class="inf-mini-btn" :disabled="disabled" @click="pickerOpen = true">
              更换
            </button>
            <button
              type="button"
              class="inf-mini-icon-btn"
              title="清除已选文件"
              :disabled="disabled"
              @click="clearExistingFile"
            >
              <X :size="13" />
            </button>
          </div>
        </div>
      </div>

      <div v-else-if="sourceMode === 'uri'" class="inf-source-block">
        <label class="inf-field">
          <span class="inf-field__label">文件 URI</span>
          <input
            :value="inputUri"
            type="text"
            class="inf-text-input"
            :class="{ 'is-error': Boolean(sourceError) }"
            placeholder="projects/project-1/inputs/sample.jpg"
            :disabled="disabled"
            @input="emit('update:inputUri', ($event.target as HTMLInputElement).value)"
          />
        </label>
        <div v-if="sourceError" class="inf-source-error">
          <div class="inf-source-error__msg">
            <AlertCircle :size="14" />
            <span>{{ sourceError }}</span>
          </div>
          <div class="inf-source-error__actions">
            <Button size="sm" variant="secondary" @click="emit('recheck-input')">重新检查</Button>
            <Button size="sm" variant="secondary" @click="switchToUpload">更换来源</Button>
          </div>
        </div>
      </div>

      <div v-else class="inf-source-block">
        <label class="inf-field">
          <span class="inf-field__label">Base64 图像</span>
          <textarea
            :value="imageBase64"
            rows="3"
            class="inf-textarea"
            :class="{ 'is-error': Boolean(base64Error || sourceError) }"
            placeholder="data:image/jpeg;base64,..."
            :disabled="disabled"
            @input="emit('update:imageBase64', ($event.target as HTMLTextAreaElement).value)"
          />
        </label>
        <div v-if="base64Error || sourceError" class="inf-source-error">
          <div class="inf-source-error__msg">
            <AlertCircle :size="14" />
            <span>{{ base64Error || sourceError }}</span>
          </div>
          <div class="inf-source-error__actions">
            <Button size="sm" variant="secondary" @click="switchToUpload">更换来源</Button>
          </div>
        </div>
      </div>

      <div class="inf-field">
        <span class="inf-field__label">调用方式</span>
        <SelectField
          :model-value="invocationMode"
          :options="invocationOptions"
          :disabled="disabled"
          aria-label="调用方式"
          @update:model-value="handleInvocationModeSelect"
        />
      </div>

      <label v-if="invocationMode === 'async'" class="inf-field">
        <span class="inf-field__label">任务名称</span>
        <input
          :value="asyncTaskName"
          type="text"
          class="inf-text-input"
          placeholder="可选，默认使用文件名"
          :disabled="disabled"
          @input="emit('update:asyncTaskName', ($event.target as HTMLInputElement).value)"
        />
      </label>

      <div class="inf-field">
        <label v-if="taskType === 'classification'" class="inf-field">
          <span class="inf-field__label">Top-K</span>
          <input
            type="number"
            class="inf-text-input inf-num-input"
            min="1"
            max="100"
            step="1"
            :value="topK"
            :disabled="disabled"
            @input="emitNumber('update:topK', $event, 1, 100)"
          />
        </label>

        <label v-else class="inf-field">
          <span class="inf-field__label">{{ taskType === 'pose' ? '对象置信度阈值' : '置信度阈值' }}</span>
          <input
            type="number"
            class="inf-text-input inf-num-input"
            min="0"
            max="1"
            step="0.01"
            :value="scoreThreshold"
            :disabled="disabled"
            @input="emitNumber('update:scoreThreshold', $event, 0, 1)"
          />
        </label>
      </div>

      <div class="inf-advanced">
        <button
          type="button"
          class="inf-advanced__trigger"
          :aria-expanded="advancedExpanded"
          @click="advancedExpanded = !advancedExpanded"
        >
          <span>高级设置</span>
          <ChevronUp v-if="advancedExpanded" :size="15" />
          <ChevronDown v-else :size="15" />
        </button>

        <div v-if="advancedExpanded" class="inf-advanced__body">
          <div v-if="deploymentInputSize" class="inf-field">
            <span class="inf-field__label">输入尺寸</span>
            <div class="inf-dims-readonly">
              <input type="text" class="inf-text-input" :value="deploymentInputSize.width" readonly />
              <span>×</span>
              <input type="text" class="inf-text-input" :value="deploymentInputSize.height" readonly />
            </div>
            <small class="inf-field__hint">来自部署配置，不可修改</small>
          </div>

          <label v-if="taskType === 'segmentation'" class="inf-field">
            <span class="inf-field__label">掩码阈值</span>
            <input
              type="number"
              class="inf-text-input inf-num-input"
              min="0"
              max="1"
              step="0.01"
              :value="maskThreshold"
              :disabled="disabled"
              @input="emitNumber('update:maskThreshold', $event, 0, 1)"
            />
          </label>

          <label v-if="taskType === 'pose'" class="inf-field">
            <span class="inf-field__label">关键点阈值</span>
            <input
              type="number"
              class="inf-text-input inf-num-input"
              min="0"
              max="1"
              step="0.01"
              :value="keypointConfidenceThreshold"
              :disabled="disabled"
              @input="emitNumber('update:keypointConfidenceThreshold', $event, 0, 1)"
            />
          </label>

          <p
            v-if="!deploymentInputSize && taskType !== 'segmentation' && taskType !== 'pose'"
            class="inf-field__hint"
          >
            当前任务无额外可调请求参数
          </p>
        </div>
      </div>

      <div class="inf-save-block">
        <label class="inf-checkbox">
          <input
            type="checkbox"
            :checked="saveResult"
            :disabled="disabled"
            @change="emit('update:saveResult', ($event.target as HTMLInputElement).checked)"
          />
          <span>{{ invocationMode === 'async' ? '保存预览图与结果' : '保存结果' }}</span>
        </label>

        <label v-if="invocationMode === 'sync' && saveResult" class="inf-inline-field">
          <span>结果名称</span>
          <input
            :value="resultName"
            type="text"
            class="inf-text-input inf-text-input--sm"
            placeholder="可选，默认使用文件名"
            :disabled="disabled"
            @input="emit('update:resultName', ($event.target as HTMLInputElement).value)"
          />
        </label>
      </div>

      <div v-if="invocationMode === 'async' && !asyncReady" class="inf-mode-notice is-warn">
        <AlertCircle :size="14" />
        <span>异步通道未启动，请先在部署页启动异步进程或切换为同步调用。</span>
      </div>

      <div v-else-if="invocationMode === 'async' && (readOnly || canSubmitAsync === false)" class="inf-mode-notice">
        <AlertCircle :size="14" />
        <span>当前账号为只读权限，无法提交异步任务。</span>
      </div>

      <div v-if="invocationMode === 'async' && asyncError" class="inf-source-error">
        <div class="inf-source-error__msg">
          <AlertCircle :size="14" />
          <span>{{ asyncError }}</span>
        </div>
      </div>
    </div>

    <footer class="inf-input-card__footer">
      <template v-if="timeoutPending && lastRequestId">
        <Button variant="secondary" disabled class="inf-run-btn">
          {{ invocationMode === 'async' ? '提交待确认' : '结果待确认' }}
        </Button>
        <div class="inf-timeout-box">
          <div class="inf-timeout-box__head">
            <Clock :size="14" />
            <div>
              <strong>请求超时</strong>
              <p>{{ invocationMode === 'async' ? '任务可能已在后台受理。' : '服务端可能仍在执行。' }}</p>
            </div>
          </div>
          <div class="inf-timeout-box__actions">
            <Button
              v-if="invocationMode === 'async'"
              size="sm"
              variant="secondary"
              @click="emit('open-tasks')"
            >
              查看任务列表
            </Button>
            <Button
              v-else
              size="sm"
              variant="secondary"
              :loading="lookupLoading"
              @click="emit('lookup-timeout')"
            >
              查询结果
            </Button>
            <Button size="sm" variant="secondary" :disabled="runButtonDisabled" @click="emit('run')">
              {{ invocationMode === 'async' ? '重新提交' : '重新推理' }}
            </Button>
          </div>
          <button
            type="button"
            class="inf-request-id-toggle"
            @click="showRequestId = !showRequestId"
          >
            <span>请求标识</span>
            <ChevronDown :size="13" />
          </button>
          <div v-if="showRequestId" class="inf-request-id-val">
            <code>{{ lastRequestId }}</code>
          </div>
        </div>
      </template>

      <Button
        v-else
        variant="primary"
        class="inf-run-btn"
        :disabled="runButtonDisabled"
        :loading="running"
        data-run-inference
        @click="emit('run')"
      >
        {{ invocationMode === 'async' ? '提交任务' : '立即推理' }}
      </Button>
    </footer>

    <ExistingFilePickerDrawer
      :open="pickerOpen"
      :project-id="projectId"
      :selected-file-id="selectedFileId"
      @close="pickerOpen = false"
      @confirm="handleExistingConfirmed"
    />
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  FolderOpen,
  Image as ImageIcon,
  X,
} from '@lucide/vue'

import type { ModelTaskType } from '@/modules/deployments/services/deployment.service'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ExistingFilePickerDrawer, {
  type ExistingFileSelectionResult,
} from './ExistingFilePickerDrawer.vue'

export type InferenceSourceMode = 'upload' | 'existing' | 'uri' | 'base64'
export type InferenceInvocationMode = 'sync' | 'async'

const props = withDefaults(
  defineProps<{
    projectId: string
    taskType: ModelTaskType
    deploymentInputSize?: { width: number; height: number } | null
    sourceMode: InferenceSourceMode
    invocationMode?: InferenceInvocationMode
    asyncTaskName?: string
    asyncReady?: boolean
    readOnly?: boolean
    canSubmitAsync?: boolean
    asyncError?: string | null
    versionBlocked?: boolean
    uploadedFile: File | null
    selectedFileId: string
    selectedFileLabel: string
    selectedFileSizeBytes?: number | null
    previewThumbUrl?: string | null
    imageWidth?: number | null
    imageHeight?: number | null
    inputUri: string
    imageBase64: string
    sourceError?: string | null
    scoreThreshold: number
    topK: number
    maskThreshold: number
    keypointConfidenceThreshold: number
    saveResult: boolean
    resultName: string
    canRun: boolean
    running?: boolean
    disabled?: boolean
    timeoutPending?: boolean
    lookupLoading?: boolean
    lastRequestId?: string | null
  }>(),
  {
    invocationMode: 'sync',
    asyncTaskName: '',
    asyncReady: false,
    readOnly: false,
    canSubmitAsync: true,
    asyncError: null,
    versionBlocked: false,
  },
)

const emit = defineEmits<{
  'update:sourceMode': [mode: InferenceSourceMode]
  'update:invocationMode': [mode: InferenceInvocationMode]
  'update:asyncTaskName': [value: string]
  'update:uploadedFile': [file: File | null]
  'update:existingSelection': [payload: ExistingFileSelectionResult | null]
  'update:inputUri': [value: string]
  'update:imageBase64': [value: string]
  'update:scoreThreshold': [value: number]
  'update:topK': [value: number]
  'update:maskThreshold': [value: number]
  'update:keypointConfidenceThreshold': [value: number]
  'update:saveResult': [value: boolean]
  'update:resultName': [value: string]
  run: []
  'open-tasks': []
  'lookup-timeout': []
  'recheck-input': []
}>()

const sourceOptions = [
  { label: '上传图片', value: 'upload' },
  { label: '已有文件', value: 'existing' },
  { label: 'URI', value: 'uri' },
  { label: 'Base64', value: 'base64' },
]

const invocationOptions = [
  { label: '同步调用', value: 'sync' },
  { label: '异步任务', value: 'async' },
]

const runButtonDisabled = computed(() => {
  if (!props.canRun || props.disabled || props.versionBlocked) return true
  if (props.invocationMode === 'async') {
    return !props.asyncReady || props.readOnly || props.canSubmitAsync === false
  }
  return false
})

const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)
const pickerOpen = ref(false)
const advancedExpanded = ref(false)
const showRequestId = ref(false)

const base64Error = computed(() => {
  if (props.sourceMode !== 'base64') return null
  const val = props.imageBase64.trim()
  if (!val) return null
  const raw = val.startsWith('data:image/') ? val.split(',')[1] ?? '' : val
  if (raw.length < 16 || /[^A-Za-z0-9+/=\s]/.test(raw)) {
    return 'Base64 格式无效或内容不完整'
  }
  return null
})

function handleSourceSelect(value: string | number | boolean | null): void {
  if (value === 'upload' || value === 'existing' || value === 'uri' || value === 'base64') {
    emit('update:sourceMode', value)
    if (value === 'existing' && !props.selectedFileLabel) {
      pickerOpen.value = true
    }
  }
}

function handleInvocationModeSelect(value: string | number | boolean | null): void {
  if (value === 'sync' || value === 'async') {
    emit('update:invocationMode', value)
  }
}

function triggerFileBrowse(): void {
  if (props.disabled) return
  fileInputRef.value?.click()
}

function handleFileInputChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (file) emit('update:uploadedFile', file)
  input.value = ''
}

function handleFileDrop(event: DragEvent): void {
  isDragging.value = false
  if (props.disabled) return
  const file = event.dataTransfer?.files?.[0] ?? null
  if (file) emit('update:uploadedFile', file)
}

function clearUploadedFile(): void {
  emit('update:uploadedFile', null)
}

function clearExistingFile(): void {
  emit('update:existingSelection', null)
}

function handleExistingConfirmed(payload: ExistingFileSelectionResult): void {
  emit('update:existingSelection', payload)
}

function switchToUpload(): void {
  emit('update:sourceMode', 'upload')
}

function emitNumber(
  eventName:
    | 'update:scoreThreshold'
    | 'update:topK'
    | 'update:maskThreshold'
    | 'update:keypointConfidenceThreshold',
  event: Event,
  min: number,
  max: number,
): void {
  const num = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(num) || num < min || num > max) return
  emit(eventName as never, num)
}

function formatFileMeta(sizeBytes?: number | null, w?: number | null, h?: number | null): string {
  const parts: string[] = []
  if (typeof sizeBytes === 'number' && sizeBytes > 0) {
    if (sizeBytes < 1024) parts.push(`${sizeBytes} B`)
    else if (sizeBytes < 1024 * 1024) parts.push(`${(sizeBytes / 1024).toFixed(1)} KB`)
    else parts.push(`${(sizeBytes / (1024 * 1024)).toFixed(2)} MB`)
  }
  if (typeof w === 'number' && w > 0 && typeof h === 'number' && h > 0) {
    parts.push(`${w} × ${h}`)
  }
  return parts.length > 0 ? parts.join(' · ') : '已就绪'
}
</script>

<style scoped>
.inf-input-card {
  display: flex;
  flex-direction: column;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  min-width: 0;
  min-height: 0;
}

.inf-input-card__head {
  padding: 14px 16px 8px;
}

.inf-input-card__head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.inf-input-card__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 6px 16px 14px;
}

.inf-field {
  display: grid;
  gap: 6px;
}

.inf-field__label {
  font-size: 13px;
  color: var(--am-text-muted);
  font-weight: 500;
}

.inf-field__hint {
  font-size: 12px;
  color: var(--am-text-muted);
  margin: 0;
}

.inf-hidden-input {
  display: none;
}

.inf-source-block {
  display: grid;
  gap: 8px;
}

.inf-dropzone {
  display: grid;
  justify-items: center;
  gap: 8px;
  padding: 20px 12px;
  border: 1px dashed var(--am-border-strong);
  border-radius: 8px;
  background: var(--am-surface-soft);
  cursor: pointer;
  transition: border-color 120ms ease, background-color 120ms ease;
}

.inf-dropzone:hover,
.inf-dropzone.is-dragover {
  border-color: var(--am-action-primary);
  background: var(--am-action-soft);
}

.inf-dropzone__icon {
  color: var(--am-text-muted);
}

.inf-dropzone__text {
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-selected-file {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
}

.inf-selected-file__thumb {
  width: 38px;
  height: 38px;
  border-radius: 6px;
  border: 1px solid var(--am-border);
  background: var(--am-page);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  color: var(--am-text-muted);
}

.inf-selected-file__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.inf-selected-file__meta {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.inf-selected-file__meta strong {
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inf-selected-file__meta span {
  font-size: 12px;
  color: var(--am-text-muted);
  font-variant-numeric: tabular-nums;
}

.inf-selected-file__actions {
  display: grid;
  gap: 4px;
}

.inf-mini-btn {
  height: 24px;
  padding: 0 8px;
  border-radius: 5px;
  border: 1px solid var(--am-border);
  background: var(--am-surface);
  color: var(--am-text);
  font-size: 12px;
  cursor: pointer;
}

.inf-mini-btn:hover:not(:disabled) {
  background: var(--am-hover-surface);
}

.inf-mini-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 5px;
  border: 1px solid var(--am-border);
  background: var(--am-surface);
  color: var(--am-text-muted);
  cursor: pointer;
}

.inf-mini-icon-btn:hover:not(:disabled) {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.inf-text-input,
.inf-textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-input);
  color: var(--am-text-strong);
  font-size: 13px;
  padding: 7px 10px;
}

.inf-text-input {
  height: 36px;
}

.inf-text-input--sm {
  height: 32px;
}

.inf-num-input {
  font-variant-numeric: tabular-nums;
}

.inf-text-input.is-error,
.inf-textarea.is-error {
  border-color: #dc2626;
}

.inf-source-error {
  display: grid;
  gap: 8px;
}

.inf-source-error__msg {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #dc2626;
}

.inf-source-error__actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.inf-advanced {
  border-top: 1px solid var(--am-border);
  padding-top: 10px;
}

.inf-advanced__trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: none;
  background: transparent;
  padding: 2px 0;
  color: var(--am-text-strong);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.inf-advanced__body {
  display: grid;
  gap: 10px;
  padding-top: 10px;
}

.inf-dims-readonly {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 6px;
  color: var(--am-text-muted);
  font-size: 12px;
}

.inf-save-block {
  border-top: 1px solid var(--am-border);
  padding-top: 10px;
  display: grid;
  gap: 8px;
}

.inf-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--am-text-strong);
  cursor: pointer;
}

.inf-inline-field {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-input-card__footer {
  padding: 0 16px 16px;
  display: grid;
  gap: 10px;
}

.inf-mode-notice {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--am-border);
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.inf-mode-notice svg {
  flex: none;
  margin-top: 2px;
}

.inf-mode-notice.is-warn {
  border-color: color-mix(in srgb, #f59e0b 45%, transparent);
  background: color-mix(in srgb, #f59e0b 10%, var(--am-surface));
  color: #b45309;
}

:root[data-theme='dark'] .inf-mode-notice.is-warn {
  color: #fbbf24;
}

.inf-run-btn {
  width: 100%;
  height: 40px;
  font-size: 14px;
  font-weight: 600;
}

.inf-timeout-box {
  display: grid;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--am-border);
}

.inf-timeout-box__head {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: #d97706;
}

.inf-timeout-box__head strong {
  display: block;
  font-size: 13px;
}

.inf-timeout-box__head p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-timeout-box__actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.inf-request-id-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: none;
  border-top: 1px solid var(--am-border);
  padding: 6px 0 0;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 12px;
  cursor: pointer;
}

.inf-request-id-val {
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--am-code-surface);
  font-size: 11px;
  overflow-wrap: anywhere;
}
</style>
