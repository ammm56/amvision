<template>
  <section v-if="importOpen" class="package-wizard">
    <div class="package-toolbar"><Button @click="closeImport">{{ zh ? '返回' : 'Back' }}</Button><h2>{{ zh ? '导入模型' : 'Import model' }}</h2></div>
    <ol class="package-steps">
      <li v-for="(label, index) in steps" :key="label" :aria-current="index + 1 === step ? 'step' : undefined" :class="{ 'is-complete': index + 1 < step, 'is-failed': index === 3 && registrationFailure }">
        <span><Check v-if="index + 1 < step" :size="16" /><X v-else-if="index === 3 && registrationFailure" :size="16" /><template v-else>{{ index + 1 }}</template></span>{{ index === 3 && registrationFailure ? (zh ? '失败' : 'Failed') : label }}
      </li>
    </ol>
    <template v-if="registrationFailure">
      <ModelPackageRegistrationFailure :record="registrationFailure" :project-name="projectName || projectId" :zh="zh" />
      <InlineError :message="error" />
    </template>
    <section v-else class="resource-section package-content">
      <template v-if="step === 1">
        <h3>{{ zh ? '上传模型包' : 'Upload model package' }}</h3>
        <p>{{ zh ? '目标项目：' : 'Target project: ' }}<strong>{{ projectName || projectId }}</strong></p>
        <p class="package-muted">{{ zh ? '选择 AMVAR 导出的模型包 ZIP。上传后还需检查，检查通过后才能登记。' : 'Choose an AMVAR model-package ZIP. Uploaded files must pass inspection before registration.' }}</p>
        <FilePicker :model-value="file" :label="zh ? 'ZIP 文件' : 'ZIP file'" icon="archive" accept=".zip,application/zip" :disabled="busy" @update:model-value="setFile" />
      </template>
      <template v-else>
        <div v-if="step !== 4" class="package-file"><FileArchive :size="23" /><div><strong>{{ current?.file_name || file?.name }}</strong><span>{{ step === 2 && current?.model && !pending && current.state !== 'failed' ? packageStatus('ready', zh) : packageStatus(current?.state || '', zh) }} · {{ formatSize(current?.upload_bytes) }} <template v-if="current?.created_at">· {{ current.uploaded_at ? (zh ? '上传时间' : 'Uploaded') : (zh ? '提交时间' : 'Submitted') }} {{ formatSystemDateTime(current.uploaded_at || current.created_at, 'minutes') }}</template></span></div></div>
        <template v-if="step === 2">
          <ModelPackageImportCheck v-if="current" :record="current" :zh="zh" :pending="pending" />
        </template>
        <template v-else-if="step === 3">
          <div v-if="classConflict" class="package-conflict-target">
            <span>{{ zh ? '当前目标：' : 'Current target: ' }}<strong>{{ current?.plan?.name }}</strong></span>
            <Button size="sm" variant="ghost" :disabled="pending || busy" @click="checked = ''; resolution = ''; resolutionName = ''">{{ zh ? '更改目标' : 'Change target' }}</Button>
          </div>
          <fieldset v-else class="package-destination" :disabled="busy || pending">
            <section>
              <h3>{{ zh ? '导入方式' : 'Import mode' }}</h3>
              <div class="package-modes">
                <label><input v-model="mode" type="radio" name="model-import-mode" value="new" /> {{ zh ? '新建模型' : 'New model' }}</label>
                <label><input v-model="mode" type="radio" name="model-import-mode" value="existing" /> {{ zh ? '添加到已有模型' : 'Add to a model' }}</label>
              </div>
              <label v-if="mode === 'new'" class="field"><span>{{ zh ? '模型名称' : 'Model name' }}</span><input v-model.trim="name" maxlength="128" /></label>
              <label v-else class="field"><span>{{ zh ? '目标模型' : 'Target model' }}</span><Select :aria-label="zh ? '目标模型' : 'Target model'" :disabled="busy || pending || targetsLoading" :model-value="target" :options="targets" @update:model-value="target = String($event || '')" />
                <small class="package-muted">{{ zh ? '登记为新的本地版本，保留已有版本。' : 'Registers a new local version and keeps the existing versions.' }}</small></label>
              <div v-if="mode === 'existing' && targetsError" class="package-read-error">
                <InlineError :message="targetsError" /><Button size="sm" type="button" :loading="targetsLoading" @click="loadTargets">{{ zh ? '重试加载目标' : 'Retry loading targets' }}</Button>
              </div>
              <label class="field"><span>{{ zh ? '说明' : 'Description' }}</span><textarea v-model.trim="description" maxlength="2000" rows="2" /></label>
            </section>
            <section>
              <h3>{{ zh ? '版本信息' : 'Version information' }}</h3>
              <p>{{ current?.model?.task_type }} · {{ current?.model?.model_type }}</p>
              <p>{{ zh ? '来源版本' : 'Source version' }} · {{ current?.source_version_id }}</p>
              <h3>{{ zh ? '模型产物' : 'Artifacts' }}</h3>
              <ul class="package-artifacts">
                <li v-for="entry in current?.files" :key="`${entry.owner}/${entry.path}`">{{ entry.path.split('/').at(-1) }} · {{ formatSize(entry.byte_size) }}</li>
              </ul>
            </section>
          </fieldset>
          <InlineError :message="current?.error || null" />
          <div v-if="issues.length" class="package-issues" role="alert"><p v-for="issue in issues" :key="issue.code">{{ issue.reason }}</p></div>
          <h3>{{ classConflict ? (zh ? '类别对照（不可重排）' : 'Class comparison (read only)') : (zh ? '类别顺序' : 'Class order') }}</h3>
          <div class="resource-table package-category-table"><table>
            <thead><tr><th scope="col">{{ zh ? '索引' : 'Index' }}</th><th v-if="classConflict" scope="col">{{ zh ? '已有模型' : 'Existing model' }}</th><th scope="col">{{ zh ? '模型包' : 'Package' }}</th><th v-if="classConflict" scope="col">{{ zh ? '差异' : 'Difference' }}</th></tr></thead>
            <tbody><tr v-for="row in classRows" :key="row.index" :class="{ 'is-conflict': row.differs }"><td>{{ row.index }}</td><td v-if="classConflict">{{ row.expected ?? '—' }}</td><td>{{ row.incoming ?? '—' }}</td><td v-if="classConflict">{{ row.differs ? (zh ? '类别不一致' : 'Classes differ') : (zh ? '一致' : 'Match') }}</td></tr></tbody>
          </table></div>
          <fieldset v-if="classConflict" class="package-resolution" :disabled="busy || pending">
            <legend>{{ zh ? '解决方案' : 'Resolve conflict' }}</legend>
            <div><label><input v-model="resolution" type="radio" name="package-resolution" value="new" />{{ zh ? '新建独立模型' : 'Create a separate model' }}</label>
              <label class="field">{{ zh ? '新模型名称' : 'New model name' }}<input v-model.trim="resolutionName" :disabled="resolution !== 'new'" maxlength="128" /></label></div>
            <div><label><input v-model="resolution" type="radio" name="package-resolution" value="replace" />{{ zh ? '返回更换文件' : 'Go back and replace file' }}</label>
              <p class="package-muted">{{ zh ? '保留原模型，选择另一份模型包。' : 'Keep the original model and choose another package.' }}</p></div>
          </fieldset>
        </template>
        <template v-else>
          <ModelPackageImportResult v-if="current" :record="current" :project-id="projectId" :project-name="projectName || projectId" :zh="zh" />
        </template>
      </template>
      <InlineError :message="error" />
    </section>
    <div v-if="recordError" class="package-read-error">
      <InlineError :message="recordError" /><Button size="sm" :loading="!!checkingId" @click="retryCurrent">{{ zh ? '重试读取状态' : 'Retry reading status' }}</Button>
    </div>
    <div class="package-actions">
      <Button v-if="step === 2 || step === 3" :disabled="busy || pending" @click="previous">{{ zh ? '上一步' : 'Previous' }}</Button>
      <div class="package-actions__end">
        <Button @click="closeImport">{{ step === 4 ? (zh ? '返回记录' : 'Back to records') : (zh ? '关闭' : 'Close') }}</Button>
        <Button v-if="step === 1" variant="primary" :disabled="!file" :loading="busy" @click="upload">{{ zh ? '检查模型包' : 'Check package' }}</Button>
        <Button v-if="step === 2 && current?.state === 'failed'" @click="copyCheckError">{{ zh ? '复制错误信息' : 'Copy error details' }}</Button>
        <Button v-if="step === 2 && current?.state === 'failed'" variant="primary" @click="reset">{{ zh ? '重新选择文件' : 'Choose another file' }}</Button>
        <Button v-if="step === 2" variant="primary" :disabled="!canEnterDestination" @click="enterDestination">{{ zh ? '下一步：信息' : 'Next: Information' }}</Button>
        <Button v-if="step === 3 && classConflict" :disabled="busy || pending || !resolution || (resolution === 'new' && !resolutionName)" @click="resolveClassConflict">{{ resolution === 'replace' ? (zh ? '返回文件' : 'Back to file') : (zh ? '检查新模型名称' : 'Check new model name') }}</Button>
        <Button v-else-if="step === 3 && !destinationChecked" variant="primary" :disabled="pending || !destinationValid" :loading="busy" @click="analyze">{{ zh ? '检查目标' : 'Check destination' }}</Button>
        <Button v-if="step === 3" variant="primary" :disabled="!destinationChecked || pending" :loading="busy && destinationChecked" @click="commit">{{ zh ? '确认导入' : 'Confirm import' }}</Button>
        <Button v-if="registrationFailure" variant="primary" :loading="busy" @click="recheckImport">{{ registrationFailure.can_recheck ? (zh ? '重新检查' : 'Recheck') : (zh ? '重新上传' : 'Upload again') }}</Button>
        <RouterLink v-if="step === 4 && current?.result" class="ui-button ui-button--primary ui-button--md" :to="{ path: '/models', query: { tab: 'versions', model: current.result.model_id, version: current.result.model_version_id } }" @click="closeImport">{{ zh ? '查看版本' : 'View version' }}</RouterLink>
        <span v-if="copyStatus" role="status">{{ copyStatus }}</span>
      </div>
    </div>
  </section>
  <section v-else class="resource-section package-records">
    <div class="package-toolbar">
      <h2>{{ zh ? '模型包导入记录' : 'Model package import records' }}</h2>
      <div class="package-records__actions">
        <Button size="sm" :loading="busy && !exportRecordsOpen" @click="load"><RefreshCw :size="15" />{{ zh ? '刷新' : 'Refresh' }}</Button>
        <Button size="sm" variant="primary" @click="$emit('create-import')"><Upload :size="16" />{{ zh ? '导入模型包' : 'Import model package' }}</Button>
      </div>
    </div>
    <InlineError :message="error" />
    <div class="resource-table">
      <table><thead><tr><th>{{ zh ? '模型名称' : 'Model name' }}</th><th>{{ zh ? '来源' : 'Source' }}</th><th>{{ zh ? '状态' : 'Status' }}</th><th>{{ zh ? '创建时间' : 'Created' }}</th><th>{{ zh ? '操作' : 'Actions' }}</th></tr></thead>
        <tbody>
          <tr v-for="item in visibleImports" :key="item.operation_id">
            <td :title="item.result?.model_version_id || item.file_name">
              <strong>{{ item.plan?.name || item.model?.model_name || item.file_name || '—' }}</strong>
              <small v-if="item.result?.model_version_id">{{ versionNames?.get(item.result.model_version_id) || '—' }}</small>
            </td>
            <td>{{ zh ? '模型包导入' : 'Model package' }}<small v-if="item.file_name" :title="item.file_name">{{ item.file_name }}</small></td>
            <td><StatusBadge :tone="importTone(item)" with-dot>{{ packageStatus(item.state, zh) }}</StatusBadge></td>
            <td>{{ formatSystemDateTime(item.created_at, 'minutes') }}</td>
            <td><Button size="sm" variant="ghost" class="package-records__detail" @click="openRecord(item)">{{ zh ? '详情' : 'Details' }}</Button></td>
          </tr>
          <tr v-if="!imports.length && !error"><td colspan="5" role="status">{{ busy ? (zh ? '正在加载导入记录…' : 'Loading import records…') : (zh ? '暂无模型包导入记录' : 'No model package imports') }}</td></tr>
        </tbody>
      </table>
    </div>
    <ModelListPagination v-if="imports.length" :page="currentImportPage" :page-size="importPageSize" :item-count="visibleImports.length" :total="imports.length" :zh="zh"
      @page="importPage = $event" @page-size="importPageSize = $event; importPage = 1" />
    <SideDrawer panel-class="model-drawer package-records-drawer" :open="exportRecordsOpen || !!current"
      :title="exportRecordsOpen ? (zh ? (current ? '导出记录详情' : '模型包导出记录') : (current ? 'Export record details' : 'Model package exports')) : (zh ? '模型包导入详情' : 'Model package import details')"
      :close-label="zh ? '关闭' : 'Close'" @close="closeRecords">
      <template v-if="exportRecordsOpen">
        <ModelPackageExportHistory v-show="!current" :records="exports" :zh="zh" :busy="busy" :downloading="downloadingId"
          @refresh="load" @open="openRecord" @download="download" />
        <ModelPackageExportResult v-if="current?.direction === 'export'" :record="current" :project-id="projectId" :zh="zh" :busy="busy" :checking="checkingId === current.operation_id" :actions-blocked="!!recordError"
          :close-label="zh ? '返回记录' : 'Back to records'" @close="closeDetail" @download="download(current)" @regenerate="regenerate" />
        <InlineError :message="error" />
      </template>
      <div v-else-if="current" class="package-content">
        <ModelPackageImportResult :record="current" :project-id="projectId" :project-name="projectName || projectId" :zh="zh" :allow-delete="deletableImport" @delete="deleteRecordOpen = true" />
        <InlineError :message="error" />
      </div>
      <div v-if="recordError" class="package-read-error">
        <InlineError :message="recordError" /><Button size="sm" :loading="!!checkingId" @click="retryCurrent">{{ zh ? '重试读取状态' : 'Retry reading status' }}</Button>
      </div>
      <template v-if="(exportRecordsOpen && !current) || (!exportRecordsOpen && current)" #footer>
        <div class="package-records__drawer-footer">
          <Button @click="closeRecords">{{ zh ? '关闭' : 'Close' }}</Button>
          <RouterLink v-if="current?.result" class="ui-button ui-button--primary ui-button--md" :to="{ path: '/models', query: { tab: 'versions', model: current.result.model_id, version: current.result.model_version_id } }">{{ zh ? '查看版本' : 'View version' }}</RouterLink>
        </div>
      </template>
    </SideDrawer>
  </section>
  <Teleport to="body"><ConfirmDialog v-if="deleteRecordOpen" :title="zh ? '删除导入记录？' : 'Delete import record?'"
    :message="zh ? '会删除此记录并清理上传暂存文件，已登记的模型和产物会保留。' : 'The record and temporary upload will be removed. Registered models and artifacts will be kept.'"
    :details="error || undefined" :busy="busy" :confirm-label="zh ? '删除记录' : 'Delete record'" :cancel-label="zh ? '取消' : 'Cancel'"
    @cancel="deleteRecordOpen = false; error = ''" @confirm="deleteImportRecord" /></Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Check, FileArchive, RefreshCw, Upload, X } from '@lucide/vue'
import ModelPackageRegistrationFailure from './ModelPackageRegistrationFailure.vue'
import ModelPackageExportHistory from './ModelPackageExportHistory.vue'
import ModelPackageExportResult from './ModelPackageExportResult.vue'
import { modelDisplayName } from '../model-display-name'
import ModelPackageImportCheck from './ModelPackageImportCheck.vue'
import ModelPackageImportResult from './ModelPackageImportResult.vue'
import ModelListPagination from './ModelListPagination.vue'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import Select from '@/shared/ui/components/Select.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import StatusBadge, { type StatusBadgeTone } from '@/shared/ui/data-display/StatusBadge.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { ApiError } from '@/shared/api/error'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { listProjectModelCatalog } from '../services/model.service'
import {
  analyzeModelPackage, canDownloadModelPackage, canRegenerateModelPackage, deleteModelPackageImport, downloadModelPackage, exportModelPackage, getModelPackage, importModelPackage, listModelPackages,
  packagePending, packageStatus, uploadModelPackage, type ModelPackageRecord,
} from '../services/model-package.service'

const props = defineProps<{ projectId: string; projectName?: string; importOpen: boolean; exportRecordsOpen?: boolean; zh: boolean; versionNames?: Map<string, string> }>()
const emit = defineEmits<{ 'update:importOpen': [open: boolean]; 'update:exportRecordsOpen': [open: boolean]; 'create-import': [] }>()
const items = ref<ModelPackageRecord[]>([])
const imports = computed(() => items.value.filter(row => row.direction === 'import'))
const importPage = ref(1)
const importPageSize = ref(20)
const currentImportPage = computed(() => Math.min(importPage.value, Math.max(1, Math.ceil(imports.value.length / importPageSize.value))))
const visibleImports = computed(() => imports.value.slice((currentImportPage.value - 1) * importPageSize.value, currentImportPage.value * importPageSize.value))
function importTone(item: ModelPackageRecord): StatusBadgeTone {
  if (item.state === 'completed') return 'success'
  if (item.state === 'failed') return 'danger'
  if (item.state === 'needs_attention') return 'warning'
  return packagePending(item.state) ? 'info' : 'neutral'
}
const exports = computed(() => items.value.filter(row => row.direction === 'export'))
const current = ref<ModelPackageRecord | null>(null)
const file = ref<File | null>(null)
const step = ref(1)
const mode = ref<'new' | 'existing'>('new')
const name = ref('')
const target = ref('')
const description = ref('')
const targets = ref<Array<{ label: string; value: string }>>([])
const targetsError = ref('')
const targetsLoading = ref(false)
const checked = ref('')
const resolution = ref<'' | 'new' | 'replace'>('')
const resolutionName = ref('')
const copyStatus = ref('')
const deleteRecordOpen = ref(false)
const busy = ref(false)
const checkingId = ref('')
const downloadingId = ref('')
const error = ref('')
const recordError = ref('')
const steps = computed(() => props.zh ? ['文件', '检查', '信息', '结果'] : ['File', 'Check', 'Information', 'Result'])
const registrationFailure = computed(() => step.value === 4 && current.value?.state === 'failed' && current.value.failure_stage ? current.value : null)
const pending = computed(() => !!current.value && packagePending(current.value.state))
const canEnterDestination = computed(() => !busy.value && !!current.value?.model && ['ready', 'needs_attention'].includes(current.value.state))
const deletableImport = computed(() => current.value?.direction === 'import' && ['completed', 'failed', 'expired', 'cancelled'].includes(current.value.state))
const destination = computed(() => ({
  target_model_id: mode.value === 'existing' ? target.value : undefined,
  model_name: mode.value === 'new' ? name.value : undefined,
  description: description.value,
}))
const destinationKey = computed(() => JSON.stringify(destination.value))
const destinationChecked = computed(() => !!checked.value && checked.value === destinationKey.value
  && current.value?.state === 'ready' && !!current.value.plan?.can_import && !!current.value.analysis_revision)
const issues = computed(() => checked.value === destinationKey.value ? current.value?.plan?.issues ?? [] : [])
const classConflict = computed(() => issues.value.find(issue => issue.code === 'category_order'))
const classRows = computed(() => {
  const incoming = current.value?.categories ?? []
  const expected = classConflict.value?.expected ?? []
  return Array.from({ length: Math.max(incoming.length, expected.length) }, (_, index) => ({
    index, incoming: incoming[index], expected: expected[index],
    differs: !!classConflict.value && incoming[index] !== expected[index],
  }))
})
const destinationValid = computed(() => mode.value === 'new' ? !!name.value.trim() : !!target.value)
let revision = 0
let timer: ReturnType<typeof setTimeout>

function formatSize(bytes: number | undefined): string { return bytes === undefined ? '—' : `${(bytes / 2 ** 20).toFixed(1)} MB` }
function setFile(value: File | File[] | null): void { file.value = Array.isArray(value) ? value[0] ?? null : value }

async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value || !props.projectId) return
  const request = revision
  busy.value = true
  error.value = ''
  try { await action() }
  catch (cause) { if (request === revision) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (request === revision) busy.value = false }
}

async function load(): Promise<void> {
  const request = revision
  await perform(async () => {
    const data = await listModelPackages(props.projectId)
    if (request === revision) items.value = data
  })
}

function update(data: ModelPackageRecord): void {
  current.value = data
  updateList(data)
}

function updateList(data: ModelPackageRecord): void {
  const index = items.value.findIndex(row => row.operation_id === data.operation_id)
  if (index === -1) items.value.unshift(data)
  else items.value[index] = data
}

async function refresh(id: string, request: number): Promise<void> {
  if (request !== revision || id !== current.value?.operation_id || checkingId.value === id) return
  checkingId.value = id
  let poll = true
  try {
    const data = await getModelPackage(props.projectId, id)
    if (request !== revision || id !== current.value?.operation_id) return
    recordError.value = ''
    update(data)
    if (props.importOpen && step.value === 4 && data.state === 'needs_attention') step.value = 3
  } catch (cause) {
    if (request === revision && id === current.value?.operation_id) {
      recordError.value = cause instanceof Error ? cause.message : String(cause)
      poll = !(cause instanceof ApiError && [401, 403, 404].includes(cause.status))
    }
  } finally {
    if (request === revision && checkingId.value === id) checkingId.value = ''
  }
  if (poll && request === revision && id === current.value?.operation_id && pending.value) timer = setTimeout(() => void refresh(id, request), 1800)
}

function retryCurrent(): void {
  if (!current.value) return
  clearTimeout(timer)
  void refresh(current.value.operation_id, revision)
}

function track(data: ModelPackageRecord): void {
  clearTimeout(timer)
  recordError.value = ''
  update(data)
  if (pending.value) void refresh(data.operation_id, revision)
}

function upload(): void {
  const selected = file.value
  const request = revision
  if (selected) void perform(async () => {
    const data = await uploadModelPackage(props.projectId, selected)
    if (request === revision) { step.value = 2; track(data) }
  })
}

function enterDestination(): void {
  if (!canEnterDestination.value || !current.value?.model) return
  step.value = 3
  if (!name.value) name.value = current.value.model.model_name
  void loadTargets()
}

async function loadTargets(): Promise<void> {
  const request = revision
  if (targetsLoading.value || !current.value) return
  targetsLoading.value = true
  targetsError.value = ''
  try {
    const page = await listProjectModelCatalog({ projectId: props.projectId, taskType: current.value?.model?.task_type, offset: 0, limit: 100 })
    if (request !== revision) return
    const choices = page.items.map(model => ({ label: modelDisplayName(model), value: model.model_id }))
    const plan = current.value?.plan
    if (plan?.target_model_id && !choices.some(choice => choice.value === plan.target_model_id)) choices.unshift({ label: plan.name, value: plan.target_model_id })
    targets.value = choices
  } catch (cause) {
    if (request === revision) targetsError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (request === revision) targetsLoading.value = false
  }
}

function analyze(): void {
  const id = current.value?.operation_id
  const request = revision
  const key = destinationKey.value
  if (id && destinationValid.value && !pending.value) void perform(async () => {
    const data = await analyzeModelPackage(props.projectId, id, destination.value)
    if (request === revision) { checked.value = key; resolution.value = ''; resolutionName.value = ''; track(data) }
  })
}

function commit(): void {
  const row = current.value
  const request = revision
  if (row?.analysis_revision && destinationChecked.value) void perform(async () => {
    const data = await importModelPackage(props.projectId, row.operation_id, row.analysis_revision!)
    if (request === revision) { step.value = 4; track(data) }
  })
}

function resolveClassConflict(): void {
  if (!classConflict.value || busy.value || pending.value) return
  if (resolution.value === 'replace') { reset(); return }
  if (resolution.value !== 'new' || !resolutionName.value.trim()) return
  name.value = resolutionName.value
  mode.value = 'new'
  target.value = ''
  analyze()
}

async function copyCheckError(): Promise<void> {
  const row = current.value
  if (!row || row.state !== 'failed') return
  const request = revision
  const report = [row.file_name, row.import_check?.member, row.import_check?.message || row.error].filter(Boolean).join('\n')
  try {
    await navigator.clipboard.writeText(report)
    if (request === revision) copyStatus.value = props.zh ? '已复制' : 'Copied'
  } catch {
    if (request === revision) copyStatus.value = props.zh ? '无法自动复制，可在错误详情中选中文本。' : 'Copy is unavailable. Select the text in Error details.'
  }
}

function deleteImportRecord(): void {
  const row = current.value
  if (!row || !deletableImport.value || !deleteRecordOpen.value) return
  const request = revision
  void perform(async () => {
    await deleteModelPackageImport(props.projectId, row.operation_id)
    if (request === revision) {
      items.value = items.value.filter(item => item.operation_id !== row.operation_id)
      closeDetail()
    }
  })
}

function recheckImport(): void {
  const row = registrationFailure.value
  if (!row) return
  if (!row.can_recheck || !row.plan) { reset(); return }
  const request = revision
  const project = props.projectId
  const plan = row.plan
  const options = {
    target_model_id: plan.target_model_id ?? undefined,
    model_name: plan.target_model_id ? undefined : plan.name,
    description: row.import_description ?? '',
  }
  void perform(async () => {
    let data: ModelPackageRecord
    try {
      data = await analyzeModelPackage(project, row.operation_id, options)
    } catch (cause) {
      if (request !== revision) return
      const latest = await getModelPackage(project, row.operation_id)
      if (request !== revision) return
      if (latest.state === 'failed' && latest.can_recheck === false) { reset(); return }
      throw cause
    }
    if (request !== revision) return
    mode.value = plan.target_model_id ? 'existing' : 'new'
    target.value = plan.target_model_id ?? ''
    name.value = plan.name
    description.value = options.description
    if (plan.target_model_id) targets.value = [{ label: plan.name, value: plan.target_model_id }]
    checked.value = destinationKey.value
    step.value = 3
    track(data)
    void loadTargets()
  })
}

function openRecord(row: ModelPackageRecord): void {
  if (busy.value) return
  error.value = ''
  if (row.direction === 'import' && row.state === 'failed' && row.failure_stage) {
    emit('update:importOpen', true)
    step.value = 4
    track(row)
    return
  }
  if (row.direction === 'import' && ['ready', 'needs_attention', 'pending_analysis', 'analyzing', 'failed'].includes(row.state)) {
    emit('update:importOpen', true)
    step.value = 2
  }
  if (row.direction === 'import' && ['pending_import', 'importing'].includes(row.state)) {
    emit('update:importOpen', true)
    step.value = 4
  }
  if (row.direction === 'export') {
    clearTimeout(timer)
    current.value = row
    void refresh(row.operation_id, revision)
  } else track(row)
}

function regenerate(): void {
  const previous = current.value
  const options = previous?.export_options
  const request = revision
  if (previous && options && canRegenerateModelPackage(previous)) void perform(async () => {
    const row = await exportModelPackage(props.projectId, options)
    if (request === revision) track(row)
  })
}

function download(row: ModelPackageRecord): void {
  if (!canDownloadModelPackage(row)) return
  const request = revision
  const project = props.projectId
  void perform(async () => {
    downloadingId.value = row.operation_id
    try {
      await downloadModelPackage(project, row)
    } catch (cause) {
      const latest = await getModelPackage(project, row.operation_id)
      if (revision !== request) return
      if (current.value?.operation_id === latest.operation_id) update(latest)
      else updateList(latest)
      if (canDownloadModelPackage(latest)) throw cause
    } finally { if (revision === request) downloadingId.value = '' }
  })
}

function closeDetail(): void {
  revision++
  clearTimeout(timer)
  current.value = null
  deleteRecordOpen.value = false
  checkingId.value = ''
  downloadingId.value = ''
  busy.value = false
  error.value = ''
  recordError.value = ''
  targetsError.value = ''
  targetsLoading.value = false
}

function closeRecords(): void {
  closeDetail()
  emit('update:exportRecordsOpen', false)
}

function reset(): void {
  closeDetail()
  file.value = null
  step.value = 1
  mode.value = 'new'
  target.value = ''
  targets.value = []
  description.value = ''
  checked.value = ''
  resolution.value = ''
  resolutionName.value = ''
  copyStatus.value = ''
  busy.value = false
  error.value = ''
}

function closeImport(): void { reset(); emit('update:importOpen', false); void load() }
function previous(): void {
  if (step.value === 2) reset()
  else step.value = 2
}
watch(() => props.projectId, () => { reset(); items.value = []; importPage.value = 1; void load() }, { immediate: true })
watch(() => props.exportRecordsOpen, open => { if (open) { closeDetail(); void load() } else if (current.value?.direction === 'export') closeDetail() })
onBeforeUnmount(reset)
</script>

<style scoped>
.package-destination,.package-resolution { min-width:0; border:0; margin:0; padding:0; }
.package-conflict-target { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; overflow-wrap:anywhere; }
.package-resolution { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.package-resolution legend { padding:0 0 8px; font-weight:600; }
.package-resolution > div { display:grid; align-content:start; gap:8px; border:1px solid var(--am-border); border-radius:6px; padding:12px; }
.package-resolution label { display:flex; align-items:center; gap:8px; }
.package-resolution label.field { display:grid; }
.package-muted { color:var(--am-text-muted); }
.package-category-table table { table-layout:fixed; }
.package-category-table :is(th,td) { white-space:normal; overflow-wrap:anywhere; padding-block:8px; }
@media (max-width:700px) { .package-resolution { grid-template-columns:minmax(0,1fr); } }
.package-wizard, .package-content, .package-destination section { display:grid; gap:14px; min-width:0; }
.package-toolbar, .package-actions, .package-actions__end, .package-modes { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.package-records .package-toolbar { justify-content:space-between; margin-bottom:14px; }
.package-records__actions { display:flex; flex-wrap:wrap; gap:10px; }
.package-read-error { display:flex; flex-wrap:wrap; gap:8px; align-items:center; min-width:0; overflow-wrap:anywhere; }
.package-records small { display:block; max-width:100%; overflow:hidden; color:var(--am-text-muted); text-overflow:ellipsis; white-space:nowrap; }
.package-records .package-records__detail { color:var(--am-action-primary-strong); }
.package-records__drawer-footer { display:flex; justify-content:flex-end; inline-size:100%; flex-wrap:wrap; gap:10px; }
:global(.package-records-drawer.side-drawer) { width:min(max(545px, 46vw), 760px, calc(100vw - 36px)); }
.package-toolbar h2, .package-content :is(h3,p) { margin:0; }
.package-steps { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; list-style:none; margin:0; padding:0; }
.package-steps li { display:flex; align-items:center; gap:10px; color:var(--am-text-muted); }
.package-steps li:not(:last-child)::after { content:''; flex:1; height:1px; background:var(--am-border); }
.package-steps li span { flex:none; display:grid; place-items:center; width:32px; height:32px; border:1px solid var(--am-border); border-radius:50%; }
.package-steps [aria-current] span { color:var(--am-brand-on-primary); background:var(--am-brand-primary); }
.package-steps .is-complete span { color:var(--am-success-text); border-color:var(--am-success-border); }
.package-steps .is-failed span { color:var(--am-danger-text); background:var(--am-danger-surface); border-color:var(--am-danger-border); }
.package-steps .is-failed { color:var(--am-danger-text); }
.package-file { display:flex; align-items:center; gap:12px; padding:14px; border-radius:6px; background:var(--am-surface-soft); }
.package-file span { display:block; color:var(--am-text-muted); }
.package-file strong, .package-content :is(dd,p,td), .package-artifacts li { overflow-wrap:anywhere; }
.package-destination { display:grid; grid-template-columns:minmax(0,3fr) minmax(0,2fr); gap:16px; }
.package-destination section { align-content:start; padding:14px; border:1px solid var(--am-border); border-radius:6px; }
.package-modes input { accent-color:var(--am-brand-primary); }
.package-artifacts { margin:0; padding-inline-start:18px; }
.package-actions { justify-content:space-between; position:sticky; bottom:0; z-index:1; padding:10px; background:var(--am-surface-raised); border-radius:6px; }
.package-actions .ui-button--primary:disabled:not(.is-loading) { color:var(--am-text-muted); background:var(--am-surface-muted); border-color:var(--am-border); }
.package-actions__end { margin-inline-start:auto; }
.is-conflict { background:var(--am-danger-surface); color:var(--am-danger-text); }
.package-issues { background:var(--am-warning-surface); color:var(--am-warning-text); border:1px solid var(--am-warning-border); border-radius:6px; padding:10px; }
@media (max-width:760px) { .package-destination { grid-template-columns:1fr; } }
</style>
