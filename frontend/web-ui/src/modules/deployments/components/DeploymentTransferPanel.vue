<template>
  <InlineError v-if="!visible" :message="error" />
  <Teleport to="body">
    <ConfirmDialog
      v-if="visible && !opened"
      :title="tr('importInstance')"
      :confirm-label="tr('selectFile')"
      :cancel-label="tr('close')"
      confirm-variant="primary"
      size="wide"
      scroll-body
      :confirm-disabled="!!uploading || busy"
      @cancel="visible = false"
      @confirm="emit('chooseFile')"
    >
      <div class="transfer-form">
        <ol class="transfer-stepper" aria-hidden="true">
          <li class="is-current"><span>1</span><strong>{{ trOpt('stepFile', '文件', 'File') }}</strong></li>
          <li><span>2</span><strong>{{ trOpt('stepConfigMapping', '配置与映射', 'Configuration & mapping') }}</strong></li>
          <li><span>3</span><strong>{{ trOpt('stepCheck', '检查', 'Check') }}</strong></li>
          <li><span>4</span><strong>{{ trOpt('stepResult', '结果', 'Result') }}</strong></li>
        </ol>

        <div v-if="error" class="transfer-feedback">
          <InlineError :message="error" />
          <Button variant="secondary" size="sm" @click="error = ''">{{ tr('clear') }}</Button>
        </div>

        <section class="transfer-step-block">
          <h4 class="transfer-step-block__title">{{ trOpt('selectPackageTitle', '选择部署实例包', 'Select deployment package') }}</h4>
          <div v-if="uploading" class="transfer-package-card">
            <div class="transfer-package-card__info">
              <span class="transfer-package-card__icon" aria-hidden="true">
                <FileArchive :size="20" />
              </span>
              <div class="transfer-summary">
                <strong>{{ uploading.name }}</strong>
                <span>{{ bytes(uploading.size) }}</span>
              </div>
              <Button variant="secondary" size="sm" @click="abortUpload">{{ tr('cancel') }}</Button>
            </div>
            <LoadingPanel compact :title="tr('uploading')" :description="`${uploading.name} · ${bytes(uploading.size)}`" />
          </div>
          <div v-else class="transfer-package-card">
            <div class="transfer-package-card__info">
              <span class="transfer-package-card__icon" aria-hidden="true">
                <FileArchive :size="20" />
              </span>
              <div class="transfer-summary">
                <strong>{{ tr('selectFile') }}</strong>
                <span>{{ trOpt('selectPackageHint', '支持 .zip 离线部署实例包，包含模型权重、运行产物、契约与配置。', 'Supports .zip offline deployment packages containing model weights, runtime artifacts, contract, and configuration.') }}</span>
              </div>
              <Button variant="secondary" size="sm" :disabled="busy" @click="emit('chooseFile')">{{ tr('selectFile') }}</Button>
            </div>
          </div>
        </section>

        <section class="transfer-step-block">
          <h4 class="transfer-step-block__title">{{ trOpt('packageSummaryTitle', '包摘要', 'Package summary') }}</h4>
          <div v-if="pendingImports.length" class="transfer-pending-list">
            <div v-for="item in pendingImports" :key="item.operation_id" class="transfer-row">
              <div class="transfer-summary">
                <strong>{{ item.file_name || item.display_name || item.summary?.deployment.display_name || (item.direction === 'import' ? tr('importInstance') : tr('exportInstance')) }}</strong>
                <LoadingPanel v-if="transferIsActive(item.state)" compact :title="transferStateLabel(item.state)" :description="item.progress_bytes ? bytes(item.progress_bytes) : tr('preparing')" />
                <span v-else role="status">{{ transferStateLabel(item.state) }}</span>
                <span v-if="item.error" class="transfer-error">{{ item.error }}</span>
              </div>
              <Button v-if="['ready', 'needs_attention', 'failed'].includes(item.state) && item.plan" variant="secondary" size="sm" @click="open(item)">{{ tr('continue') }}</Button>
              <Button v-if="!['importing', 'completed', 'failed', 'cancelled', 'expired'].includes(item.state)" variant="secondary" size="sm" :disabled="busy" @click="cancel(item)">{{ tr('cancel') }}</Button>
              <Button v-if="item.state === 'failed'" variant="secondary" size="sm" :disabled="busy" :loading="dismissingId === item.operation_id" @click="dismiss(item)">{{ tr('clear') }}</Button>
            </div>
          </div>
          <div v-else-if="!uploading" class="transfer-summary-placeholder">
            <FileSearch :size="24" aria-hidden="true" />
            <strong>{{ trOpt('noCheckTitle', '未运行检查', 'Check not run') }}</strong>
            <p>{{ trOpt('noCheckHint', '选择部署实例包后，先分析文件和运行要求。', 'Select a deployment package to analyze files and runtime requirements.') }}</p>
          </div>
        </section>
      </div>
    </ConfirmDialog>

    <ConfirmDialog
      v-if="visible && opened"
      :title="tr('importInstance')"
      :confirm-label="needsAnalysis ? tr('check') : tr('import')"
      :cancel-label="tr('close')"
      confirm-variant="primary"
      size="wide"
      scroll-body
      :busy="busy"
      :confirm-disabled="transferIsActive(opened.state) || (!dirty && !opened.plan?.can_import)"
      @cancel="visible = false; openedId = null"
      @confirm="confirm"
    >
      <div class="transfer-form">
        <ol class="transfer-stepper" aria-hidden="true">
          <li class="is-complete"><span>1</span><strong>{{ trOpt('stepFile', '文件', 'File') }}</strong></li>
          <li :class="{ 'is-current': needsAnalysis && opened.state !== 'importing', 'is-complete': !needsAnalysis || opened.state === 'completed' }"><span>2</span><strong>{{ trOpt('stepConfigMapping', '配置与映射', 'Configuration & mapping') }}</strong></li>
          <li :class="{ 'is-current': !needsAnalysis && !transferIsActive(opened.state) && opened.state !== 'completed', 'is-complete': transferIsActive(opened.state) || opened.state === 'completed' }"><span>3</span><strong>{{ trOpt('stepCheck', '检查', 'Check') }}</strong></li>
          <li :class="{ 'is-current': transferIsActive(opened.state) || opened.state === 'completed' }"><span>4</span><strong>{{ trOpt('stepResult', '结果', 'Result') }}</strong></li>
        </ol>

        <div v-if="error" class="transfer-feedback">
          <InlineError :message="error" />
          <Button variant="secondary" size="sm" @click="error = ''">{{ tr('clear') }}</Button>
        </div>
        <div v-if="opened.error" class="transfer-feedback">
          <InlineError :message="opened.error" />
          <Button v-if="opened.state === 'failed'" variant="secondary" size="sm" :disabled="busy" :loading="dismissingId === opened.operation_id" @click="dismiss(opened)">{{ tr('clear') }}</Button>
        </div>

        <div class="transfer-package-banner">
          <div class="transfer-package-banner__head">
            <span class="transfer-package-card__icon" aria-hidden="true">
              <FileArchive :size="20" />
            </span>
            <div class="transfer-summary">
              <strong>{{ opened.file_name || opened.display_name || opened.summary?.deployment.display_name || tr('importInstance') }}</strong>
              <span v-if="opened.total_bytes || opened.upload_bytes">{{ bytes(opened.total_bytes || opened.upload_bytes || 0) }}</span>
            </div>
          </div>
          <div v-if="opened.summary" class="summary-grid transfer-package-banner__grid">
            <div><span>{{ tr('model') }}</span><strong>{{ opened.summary.model.model_name }}</strong></div>
            <div><span>{{ tr('task') }}</span><strong>{{ modelTaskLabel(opened.summary.model.task_type, zh) }}</strong></div>
            <div><span>{{ tr('backend') }}</span><strong>{{ formatDeploymentBackend(opened.summary.deployment.runtime_backend) }} · {{ opened.summary.inference.runtime_precision.toUpperCase() }}</strong></div>
            <div><span>{{ tr('input') }}</span><strong>{{ opened.summary.inference.input_size.width }} × {{ opened.summary.inference.input_size.height }}</strong></div>
            <div><span>{{ tr('categories') }}</span><strong>{{ opened.summary.category_count }}</strong></div>
          </div>
        </div>

        <template v-if="opened.state !== 'completed'">
          <section class="transfer-step-block">
            <h4 class="transfer-step-block__title">{{ trOpt('basicConfig', '基本配置', 'Basic configuration') }}</h4>
            <div class="form-grid">
              <label class="field">
                <span>{{ tr('name') }}</span>
                <input v-model="options.display_name" maxlength="128" @input="dirty = true">
              </label>
              <label class="field">
                <span>{{ tr('device') }}</span>
                <SelectField :model-value="options.device_name || ''" :options="deviceOptions" @update:model-value="value => { options.device_name = String(value); dirty = true }" />
              </label>
              <label class="field">
                <span>{{ trOpt('callMode', '调用模式', 'Call mode') }}</span>
                <input :value="callModeSyncLabel" readonly>
              </label>
              <label class="field">
                <span>{{ tr('count') }}</span>
                <input v-model.number="options.instance_count" type="number" min="1" max="64" @input="dirty = true">
              </label>
            </div>
            <label v-if="opened.plan?.issues.some(issue => issue.code === 'id_conflict') || options.create_copy" class="transfer-check">
              <input v-model="options.create_copy" type="checkbox" @change="dirty = true">{{ tr('copy') }}
            </label>
          </section>

          <section v-if="Object.keys(configuration).length" class="transfer-section transfer-section--expanded">
            <div class="transfer-section__header">
              <h4>{{ tr('configuration') }}</h4>
              <Button variant="secondary" size="sm" :disabled="busy" @click="resetDeviceConfiguration">{{ tr('recommended') }}</Button>
            </div>
            <div class="configuration-content">
              <p class="configuration-hint">{{ tr('preserve') }}</p>
              <fieldset v-for="(fields, group) in configuration" :key="group" class="configuration-group">
                <legend>{{ groupLabel(String(group)) }}</legend>
                <div class="form-grid">
                  <label v-for="(value, key) in fields" :key="key" :class="typeof value === 'boolean' ? 'configuration-toggle' : 'field'">
                    <span>{{ fieldLabel(String(key)) }}</span>
                    <input v-if="typeof value === 'boolean'" type="checkbox" :checked="value" @change="setConfiguration(String(group), String(key), ($event.target as HTMLInputElement).checked)">
                    <input v-else :value="Array.isArray(value) ? value.join(',') : value ?? ''" :readonly="key === 'kind' || key === 'instance_count'" @change="setConfiguration(String(group), String(key), ($event.target as HTMLInputElement).value)">
                  </label>
                </div>
              </fieldset>
            </div>
          </section>

          <ul v-if="opened.plan?.issues.length" class="transfer-issues">
            <li v-for="issue in opened.plan.issues" :key="issue.reason" class="transfer-error">{{ issue.reason }}</li>
          </ul>
        </template>

        <section v-if="opened.plan" class="transfer-step-block">
          <h4 class="transfer-step-block__title">{{ tr('mapping') }}</h4>
          <div class="resource-table transfer-mapping">
            <table>
              <thead>
                <tr>
                  <th scope="col">{{ trOpt('resourceCol', '资源', 'Resource') }}</th>
                  <th scope="col">{{ trOpt('packageSourceCol', '包内来源', 'Package source') }}</th>
                  <th scope="col">{{ trOpt('importTargetCol', '导入目标', 'Import target') }}</th>
                  <th scope="col">{{ trOpt('handlingCol', '处理方式', 'Handling') }}</th>
                  <th scope="col">{{ trOpt('verificationCol', '校验', 'Check') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(value, key) in opened.plan.mapping" :key="key">
                  <th scope="row">
                    {{ resourceLabel(String(key)) }}<small v-if="isReusedResource(String(key))">{{ tr('reuse') }}</small>
                  </th>
                  <td>{{ opened.plan.original[key] || '—' }}</td>
                  <td>{{ value || '—' }}</td>
                  <td>
                    <span class="transfer-handling-pill" :class="{ 'is-reused': isReusedResource(String(key)) }">
                      {{ isReusedResource(String(key)) ? trOpt('handlingReuse', '复用', 'Reuse') : trOpt('handlingCreate', '新建', 'Create') }}
                    </span>
                  </td>
                  <td>
                    <span class="transfer-verify-badge" :class="{ 'is-reused': isReusedResource(String(key)) }">
                      <CheckCircle2 v-if="isReusedResource(String(key))" :size="14" aria-hidden="true" />
                      <PlusCircle v-else :size="14" aria-hidden="true" />
                      <span>{{ isReusedResource(String(key)) ? trOpt('verifyMatched', '身份与文件摘要一致', 'Identity and checksum match') : trOpt('verifyNewInstance', '将创建新实例', 'Will create new instance') }}</span>
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="transfer-mapping-note">
            <Info :size="14" aria-hidden="true" />
            <span>{{ trOpt('mappingReuseNote', '同名不能独立作为复用依据。', 'Identical names alone do not qualify for reuse.') }}</span>
          </p>
        </section>

        <LoadingPanel v-if="transferIsActive(opened.state)" compact :title="transferStateLabel(opened.state)" :description="opened.progress_bytes ? bytes(opened.progress_bytes) : tr('preparing')" />
      </div>
    </ConfirmDialog>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, toRaw, watch } from 'vue'
import { CheckCircle2, FileArchive, FileSearch, Info, PlusCircle } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import { buildDeploymentDeviceOptions } from '../deployment-device-support'
import { formatDeploymentBackend } from '../deployment-presentation'
import { modelTaskLabel } from '@/modules/models/model-evaluation-types'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import LoadingPanel from '@/shared/ui/feedback/LoadingPanel.vue'
import { i18n, translate } from '@/platform/i18n'
const tr = (key: string) => translate(`deploymentTransfer.${key}`)
const zh = computed(() => String(i18n.global.locale.value || '').startsWith('zh'))
const trOpt = (key: string, fallbackZh: string, fallbackEn: string) => {
  const full = `deploymentTransfer.${key}`
  return i18n.global.te(full) ? translate(full) : (zh.value ? fallbackZh : fallbackEn)
}
const callModeSyncLabel = computed(() => (
  i18n.global.te('deploymentOps.runtimeModes.sync')
    ? translate('deploymentOps.runtimeModes.sync')
    : trOpt('callModeSync', '同步', 'Sync')
))
import { getDeploymentRuntimeCapabilities } from '../services/deployment.service'
import { cancelTransfer, changeTransfer, dismissTransfer, listTransfers, transferIsActive, transferStateLabel, uploadDeployment, type DeploymentTransfer, type TransferOptions } from '../services/deployment-transfer.service'

const props = defineProps<{ projectId: string | null; devices?: Record<string, unknown> | null }>()
const emit = defineEmits<{ settled: []; chooseFile: [] }>()
const items = ref<DeploymentTransfer[]>([])
const visible = ref(false)
const dismissingId = ref<string | null>(null)
const pendingImports = computed(() => items.value.filter(item => item.direction === 'import' && !['completed', 'cancelled', 'expired'].includes(item.state)))
const error = ref('')
const busy = ref(false)
const uploading = ref<{ name: string; size: number } | null>(null)
let uploadController: AbortController | null = null
const openedId = ref<string | null>(null)
const opened = computed(() => items.value.find(item => item.operation_id === openedId.value))
const options = ref<TransferOptions>({})
const configuration = ref<Record<string, Record<string, unknown>>>({})
const dirty = ref(false)
const needsAnalysis = computed(() => dirty.value || opened.value?.state !== 'ready')
const deviceOptions = computed(() => {
  const values = buildDeploymentDeviceOptions(props.devices, opened.value?.summary?.deployment.runtime_backend, { automaticDefault: tr('automatic'), openvinoAutoDefault: 'AUTO', openvinoGpu: 'GPU' }).filter(item => item.value)
  const source = options.value.device_name
  if (source && !values.some(item => item.value === source)) values.unshift({ value: source, label: `${source}${tr('sourceDevice')}` })
  return values
})
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0
let localRevision = 0
const bytes = (value: number) => `${(value / 1024 / 1024).toFixed(1)} MB`
const fieldLabel = (key: string) => {
  const mapped: Record<string, string> = {
    instance_count: tr('count'),
    performance_goal: tr('performanceGoal'),
    keep_warm_enabled: tr('keepWarm'),
    keep_warm_interval_seconds: tr('keepWarmInterval'),
    warmup_dummy_inference_count: tr('warmupCount'),
    warmup_dummy_image_size: tr('warmupSize'),
    performance_hint: tr('performanceHint'),
    inference_num_threads: tr('threads'),
    num_streams: tr('streams'),
    kind: tr('backendKind'),
    execution_scope: tr('executionScope'),
    overflow_policy: tr('overflowPolicy'),
    isolation_level: tr('isolationLevel'),
    scheduling_core_type: tr('coreType'),
    enable_hyper_threading: tr('hyperThreading'),
    enable_cpu_pinning: tr('cpuPinning'),
  }
  if (mapped[key]) return mapped[key]
  const workspaceKey = `deploymentWorkspace.drawer.runtimeFields.${key}`
  return i18n.global.te(workspaceKey) ? translate(workspaceKey) : key
}
const groupLabel = (key: string) => ({ execution: tr('execution'), lifecycle: tr('lifecycle'), backend_options: tr('backendOptions') }[key] || key)
const resourceLabel = (key: string) => ({ model: tr('model'), version: tr('modelVersion'), build: tr('modelBuild'), deployment: tr('deployment') }[key] || key)
const isReusedResource = (key: string) => Boolean(opened.value?.plan?.reused?.includes(key))
function setConfiguration(group: string, key: string, value: unknown) {
  const previous = configuration.value[group]?.[key]
  if (typeof value === 'string') {
    if (value === '') value = null
    else if (Array.isArray(previous)) value = value.split(',').map(Number)
    else if (/^-?\d+(\.\d+)?$/.test(value)) value = Number(value)
  }
  configuration.value[group]![key] = value
  dirty.value = true
}
function store(item: DeploymentTransfer) { localRevision++; items.value = [...items.value.filter(row => row.operation_id !== item.operation_id), item] }
function exportFor(id: string) { return items.value.filter(item => item.direction === 'export' && item.deployment_id === id).at(-1) }
function beginImport() {
  if (uploading.value || pendingImports.value.length || error.value) { visible.value = true; return }
  emit('chooseFile')
}
function openImportDialog() {
  visible.value = true
  openedId.value = null
  error.value = ''
}
async function resetDeviceConfiguration() {
  const backend = opened.value?.summary?.deployment.runtime_backend
  if (!backend || !options.value.device_name) return
  await perform(async (current) => {
    const result = await getDeploymentRuntimeCapabilities(backend, options.value.device_name!)
    if (!current()) return
    configuration.value.backend_options = structuredClone(result.default_runtime_configuration.backend_options) as unknown as Record<string, unknown>
    dirty.value = true
  })
}
async function perform(action: (current: () => boolean) => Promise<void>) {
  const epoch = generation
  const current = () => epoch === generation
  busy.value = true; error.value = ''
  try { await action(current) }
  catch (cause) { if (current()) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (current()) busy.value = false }
}
function open(item: DeploymentTransfer) {
  visible.value = true
  openedId.value = item.operation_id
  const plan = item.plan!
  configuration.value = structuredClone(toRaw(plan.runtime_configuration)) as Record<string, Record<string, unknown>>
  options.value = { display_name: plan.display_name, device_name: plan.device_name, instance_count: Number(configuration.value.execution?.instance_count || 1), create_copy: false }
  dirty.value = false; error.value = ''
}
async function refresh(epoch = generation) {
  if (!props.projectId) return
  const project = props.projectId
  const revision = localRevision
  try {
    const previous = new Map(items.value.map(item => [item.operation_id, item.state]))
    const result = await listTransfers(project)
    if (epoch !== generation || revision !== localRevision) return
    items.value = result
    if (result.some(item => item.direction === 'import' && item.state === 'completed' && previous.has(item.operation_id) && previous.get(item.operation_id) !== 'completed')) {
      emit('settled')
      if (result.some(item => item.operation_id === openedId.value && item.state === 'completed')) { visible.value = false; openedId.value = null }
    }
    const ready = result.find(item => item.operation_id === awaitingUpload && item.plan)
    if (ready) { awaitingUpload = null; if (visible.value) open(ready) }
  } catch (cause) { if (epoch === generation) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (epoch === generation) timer = setTimeout(() => void refresh(epoch), 1500) }
}
let awaitingUpload: string | null = null
async function upload(file: File) {
  if (!props.projectId || uploadController) return
  const project = props.projectId
  visible.value = true; openedId.value = null
  const controller = new AbortController()
  uploadController = controller
  uploading.value = { name: file.name, size: file.size }
  await perform(async (current) => {
    try {
      const item = await uploadDeployment(project, file, controller.signal)
      if (!current()) return
      store(item)
      if (controller.signal.aborted) {
        const cancelled = await cancelTransfer(project, item.operation_id)
        if (current()) store(cancelled)
      }
      else awaitingUpload = item.operation_id
    } catch (cause) {
      if (!controller.signal.aborted) throw cause
      if (current()) error.value = tr('uploadInterrupted')
    } finally {
      if (uploadController === controller) { uploadController = null; uploading.value = null }
    }
  })
}
function abortUpload() { uploadController?.abort() }
async function confirm() {
  const item = opened.value
  if (!item || !props.projectId) return
  if (item.state === 'completed') { openedId.value = null; return }
  const project = props.projectId
  await perform(async (current) => {
    if (needsAnalysis.value) {
      if (!Number.isInteger(options.value.instance_count) || Number(options.value.instance_count) < 1 || Number(options.value.instance_count) > 64) throw new Error(tr('invalidCount'))
      const analyzed = await changeTransfer(project, item.operation_id, 'analyze', { ...options.value, runtime_configuration: configuration.value })
      if (!current()) return
      store(analyzed)
      dirty.value = false
    } else {
      const committed = await changeTransfer(project, item.operation_id, 'commit', { analysis_revision: item.analysis_revision, idempotency_key: item.operation_id })
      if (current()) store(committed)
    }
  })
}
const cancel = (item: DeploymentTransfer) => perform(async (current) => {
  const cancelled = await cancelTransfer(props.projectId!, item.operation_id)
  if (current()) store(cancelled)
})
async function dismiss(item: DeploymentTransfer) {
  if (!props.projectId || busy.value || item.state !== 'failed') return
  const project = props.projectId
  dismissingId.value = item.operation_id
  await perform(async (current) => {
    try {
      await dismissTransfer(project, item.operation_id)
      if (!current()) return
      localRevision++
      items.value = items.value.filter(row => row.operation_id !== item.operation_id)
      if (openedId.value === item.operation_id) openedId.value = null
      if (awaitingUpload === item.operation_id) awaitingUpload = null
    } finally {
      if (current()) dismissingId.value = null
    }
  })
}
watch(() => props.projectId, () => { abortUpload(); uploadController = null; uploading.value = null; generation++; clearTimeout(timer); items.value = []; busy.value = false; dismissingId.value = null; visible.value = false; openedId.value = null; awaitingUpload = null; error.value = ''; void refresh() }, { immediate: true })
onBeforeUnmount(() => { abortUpload(); generation++; clearTimeout(timer) })
defineExpose({ items, busy, upload, beginImport, openImportDialog, open, refresh, cancel, dismiss, exportFor, store })
</script>

<style scoped>
.transfer-row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--am-border); }
.transfer-row:last-child { border-bottom: 0; }
.transfer-summary { display: grid; gap: 3px; flex: 1; min-width: 0; overflow-wrap: anywhere; }
.transfer-summary > strong { font-size: 14px; }
.transfer-summary > span { font-size: 12px; color: var(--am-text-muted); }
.transfer-error { color: var(--am-danger-text) !important; }
.transfer-feedback { display: flex; align-items: flex-start; gap: 10px; }
.transfer-feedback > :first-child { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.transfer-row > .ui-button, .transfer-feedback > .ui-button { flex-shrink: 0; }
.transfer-form { display: grid; gap: 16px; }
.transfer-stepper { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 0; padding: 10px 12px; list-style: none; border: 1px solid var(--am-border); border-radius: 8px; background: var(--am-surface-muted); font-size: 12px; }
.transfer-stepper li { display: flex; align-items: center; gap: 6px; color: var(--am-text-muted); }
.transfer-stepper li span { display: grid; place-items: center; width: 20px; height: 20px; flex-shrink: 0; border-radius: 999px; border: 1px solid var(--am-border); background: var(--am-surface); font-weight: 700; }
.transfer-stepper li.is-current { color: var(--am-action-primary-strong); }
.transfer-stepper li.is-current span { border-color: var(--am-action-primary); background: var(--am-action-primary); color: #fff; }
.transfer-stepper li.is-complete { color: var(--am-text); }
.transfer-stepper li.is-complete span { border-color: var(--am-action-primary); color: var(--am-action-primary); }

.transfer-step-block { display: grid; gap: 10px; min-width: 0; }
.transfer-step-block__title { margin: 0; font-size: 14px; font-weight: 700; color: var(--am-text-strong); }

.transfer-package-card,
.transfer-package-banner {
  display: grid;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-muted);
}

.transfer-package-card__info,
.transfer-package-banner__head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.transfer-package-card__icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
  color: var(--am-text-muted);
}

.transfer-pending-list {
  padding: 0 14px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
}

.transfer-summary-placeholder {
  display: grid;
  justify-items: center;
  gap: 6px;
  padding: 24px 16px;
  border: 1px dashed var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
  color: var(--am-text-muted);
  text-align: center;
}

.transfer-summary-placeholder strong {
  font-size: 14px;
  color: var(--am-text);
}

.transfer-summary-placeholder p {
  margin: 0;
  font-size: 13px;
}

.transfer-package-banner__grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px 12px;
  padding: 10px 0 0;
  border-top: 1px solid var(--am-border);
}

.transfer-package-banner__grid > div {
  display: grid;
  gap: 2px;
}

.transfer-package-banner__grid span {
  font-size: 12px;
  color: var(--am-text-muted);
}

.transfer-package-banner__grid strong {
  font-size: 13px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.transfer-section { border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); min-width: 0; }
.transfer-section__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px 8px;
}
.transfer-section__header h4 { margin: 0; font-size: 14px; font-weight: 700; color: var(--am-text-strong); }
.configuration-content { display: grid; gap: 14px; padding: 0 16px 16px; }
.configuration-hint { margin: 0; color: var(--am-text-muted); font-size: 13px; line-height: 1.5; }
.configuration-group { min-width: 0; margin: 0; padding: 14px 0 0; border: 0; border-top: 1px solid var(--am-border); }
.configuration-group legend { padding: 0 8px 0 0; font-size: 13px; font-weight: 650; }
.transfer-form .form-grid { align-items: start; gap: 14px; }
.transfer-form .field { min-width: 0; }
.transfer-form .field > span { overflow-wrap: anywhere; }
.configuration-toggle { display: flex; align-items: center; justify-content: space-between; align-self: end; min-height: 40px; gap: 12px; font-size: 13px; font-weight: 650; }
.configuration-toggle input { width: 16px; height: 16px; min-height: 16px; flex: 0 0 16px; margin: 0; }
.transfer-check { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.transfer-issues { margin: 0; padding-left: 18px; display: grid; gap: 4px; font-size: 13px; }

.transfer-mapping { border: 1px solid var(--am-border); border-radius: 8px; overflow-x: auto; }
.transfer-mapping table { width: 100%; min-width: 560px; table-layout: fixed; border-collapse: collapse; }
.transfer-mapping th:nth-child(1) { width: 16%; }
.transfer-mapping th:nth-child(2) { width: 23%; }
.transfer-mapping th:nth-child(3) { width: 23%; }
.transfer-mapping th:nth-child(4) { width: 14%; }
.transfer-mapping th:nth-child(5) { width: 24%; }
.transfer-mapping th, .transfer-mapping td { overflow-wrap: anywhere; vertical-align: middle; padding: 10px 12px; font-size: 13px; }
.transfer-mapping small { display: block; margin-top: 2px; color: var(--am-text-muted); font-weight: 400; }

.transfer-handling-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--am-border);
  background: var(--am-surface-muted);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.transfer-handling-pill.is-reused {
  border-color: var(--am-action-primary);
  color: var(--am-action-primary-strong);
}

.transfer-verify-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--am-text-muted);
}

.transfer-verify-badge.is-reused {
  color: var(--am-action-primary-strong);
}

.transfer-mapping-note {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 12px;
  color: var(--am-text-muted);
}

@media (max-width: 640px) {
  .transfer-form .form-grid,
  .transfer-package-banner__grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
