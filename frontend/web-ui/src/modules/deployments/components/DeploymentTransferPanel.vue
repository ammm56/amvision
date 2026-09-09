<template>
  <InlineError v-if="!visible" :message="error" />
  <Teleport to="body">
  <ConfirmDialog v-if="visible && !opened" :title="tr('importInstance')" :confirm-label="tr('selectFile')" :cancel-label="tr('close')" confirm-variant="primary" size="medium" :confirm-disabled="!!uploading || busy" @cancel="visible = false" @confirm="emit('chooseFile')">
    <div v-if="error" class="transfer-feedback">
      <InlineError :message="error" />
      <Button variant="secondary" size="sm" @click="error = ''">{{ tr('clear') }}</Button>
    </div>
    <div v-if="uploading" class="transfer-row">
      <LoadingPanel compact :title="tr('uploading')" :description="`${uploading.name} · ${bytes(uploading.size)}`" />
      <Button variant="secondary" size="sm" @click="abortUpload">{{ tr('cancel') }}</Button>
    </div>
    <div v-for="item in pendingImports" :key="item.operation_id" class="transfer-row">
      <div class="transfer-summary">
        <strong>{{ item.display_name || item.summary?.deployment.display_name || (item.direction === 'import' ? tr('importInstance') : tr('exportInstance')) }}</strong>
        <LoadingPanel v-if="transferIsActive(item.state)" compact :title="transferStateLabel(item.state)" :description="item.progress_bytes ? bytes(item.progress_bytes) : tr('preparing')" /><span v-else role="status">{{ transferStateLabel(item.state) }}</span>
        <span v-if="item.error" class="transfer-error">{{ item.error }}</span>
      </div>
      <Button v-if="['ready', 'needs_attention', 'failed'].includes(item.state) && item.plan" variant="secondary" size="sm" @click="open(item)">{{ tr('continue') }}</Button>
      <Button v-if="!['importing', 'completed', 'failed', 'cancelled', 'expired'].includes(item.state)" variant="secondary" size="sm" :disabled="busy" @click="cancel(item)">{{ tr('cancel') }}</Button>
      <Button v-if="item.state === 'failed'" variant="secondary" size="sm" :disabled="busy" :loading="dismissingId === item.operation_id" @click="dismiss(item)">{{ tr('clear') }}</Button>
    </div>
  </ConfirmDialog>
    <ConfirmDialog v-if="visible && opened" :title="tr('importInstance')" :confirm-label="needsAnalysis ? tr('check') : tr('import')" :cancel-label="tr('close')" confirm-variant="primary" size="medium" :busy="busy" :confirm-disabled="transferIsActive(opened.state) || (!dirty && !opened.plan?.can_import)" @cancel="visible = false; openedId = null" @confirm="confirm">
      <div class="transfer-form">
        <div v-if="error" class="transfer-feedback">
          <InlineError :message="error" />
          <Button variant="secondary" size="sm" @click="error = ''">{{ tr('clear') }}</Button>
        </div>
        <div v-if="opened.error" class="transfer-feedback">
          <InlineError :message="opened.error" />
          <Button v-if="opened.state === 'failed'" variant="secondary" size="sm" :disabled="busy" :loading="dismissingId === opened.operation_id" @click="dismiss(opened)">{{ tr('clear') }}</Button>
        </div>
        <div v-if="opened.summary" class="summary-grid">
          <div><span>{{ tr('model') }}</span><strong>{{ opened.summary.model.model_name }}</strong></div>
          <div><span>{{ tr('task') }}</span><strong>{{ opened.summary.model.task_type }}</strong></div>
          <div><span>{{ tr('backend') }}</span><strong>{{ opened.summary.deployment.runtime_backend }} · {{ opened.summary.inference.runtime_precision }}</strong></div>
          <div><span>{{ tr('input') }}</span><strong>{{ opened.summary.inference.input_size.width }} × {{ opened.summary.inference.input_size.height }}</strong></div>
          <div><span>{{ tr('categories') }}</span><strong>{{ opened.summary.category_count }}</strong></div>
        </div>
        <template v-if="opened.state !== 'completed'">
          <label class="field"><span>{{ tr('name') }}</span><input v-model="options.display_name" maxlength="128" @input="dirty = true"></label>
          <div class="form-grid">
            <label class="field"><span>{{ tr('device') }}</span><SelectField :model-value="options.device_name || ''" :options="deviceOptions" @update:model-value="value => { options.device_name = String(value); dirty = true }" /></label>
            <label class="field"><span>{{ tr('count') }}</span><input v-model.number="options.instance_count" type="number" min="1" max="64" @input="dirty = true"></label>
          </div>
          <label v-if="opened.plan?.issues.some(issue => issue.code === 'id_conflict') || options.create_copy" class="transfer-check"><input v-model="options.create_copy" type="checkbox" @change="dirty = true">{{ tr('copy') }}</label>
          <details><summary>{{ tr('configuration') }}</summary>
            <p>{{ tr('preserve') }}</p>
            <Button variant="secondary" size="sm" :disabled="busy" @click="resetDeviceConfiguration">{{ tr('recommended') }}</Button>
            <div v-for="(fields, group) in configuration" :key="group" class="form-grid">
              <label v-for="(value, key) in fields" :key="key" class="field"><span>{{ fieldLabel(String(key)) }}</span>
                <input v-if="typeof value === 'boolean'" type="checkbox" :checked="value" @change="setConfiguration(String(group), String(key), ($event.target as HTMLInputElement).checked)">
                <input v-else :value="Array.isArray(value) ? value.join(',') : value ?? ''" :readonly="key === 'kind' || key === 'instance_count'" @change="setConfiguration(String(group), String(key), ($event.target as HTMLInputElement).value)">
              </label>
            </div>
          </details>
          <ul v-if="opened.plan?.issues.length"><li v-for="issue in opened.plan.issues" :key="issue.reason" class="transfer-error">{{ issue.reason }}</li></ul>
        </template>
        <details v-if="opened.plan"><summary>{{ tr('mapping') }}</summary><dl class="transfer-mapping"><template v-for="(value, key) in opened.plan.mapping" :key="key"><dt>{{ key }}{{ opened.plan.reused.includes(String(key)) ? tr('reuse') : '' }}</dt><dd>{{ opened.plan.original[key] }} → {{ value }}</dd></template></dl></details>
        <LoadingPanel v-if="transferIsActive(opened.state)" compact :title="transferStateLabel(opened.state)" :description="opened.progress_bytes ? bytes(opened.progress_bytes) : tr('preparing')" />
      </div>
    </ConfirmDialog>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, toRaw, watch } from 'vue'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import { buildDeploymentDeviceOptions } from '../deployment-device-support'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import LoadingPanel from '@/shared/ui/feedback/LoadingPanel.vue'
import { translate } from '@/platform/i18n'
const tr = (key: string) => translate(`deploymentTransfer.${key}`)
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
const fieldLabel = (key: string) => ({ instance_count: tr('count'), performance_goal: '性能目标', keep_warm_enabled: '保温', keep_warm_interval_seconds: '保温间隔（秒）', warmup_dummy_inference_count: '预热次数', warmup_dummy_image_size: '预热尺寸', performance_hint: '性能模式', inference_num_threads: '线程数', num_streams: '流数', kind: '后端配置', execution_scope: '执行范围', overflow_policy: '队列满时策略' }[key] || key)
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
defineExpose({ upload, beginImport, exportFor, store })
</script>

<style scoped>
.transfer-row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--am-border); }
.transfer-summary { display: grid; gap: 4px; flex: 1; min-width: 0; overflow-wrap: anywhere; }
.transfer-summary > span { font-size: 12px; color: var(--am-text-muted); }
.transfer-error { color: var(--am-danger-text) !important; }
.transfer-feedback { display: flex; align-items: flex-start; gap: 10px; }
.transfer-feedback > :first-child { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.transfer-row > .ui-button, .transfer-feedback > .ui-button { flex-shrink: 0; }
.transfer-form { display: grid; gap: 16px; }
.transfer-form .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 0; gap: 12px; }
.transfer-form .summary-grid > div:first-child { grid-column: 1 / -1; }
.transfer-form .summary-grid strong { font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.transfer-form details { padding: 8px 0; }
.transfer-form summary { cursor: pointer; }
.transfer-check { display: flex; align-items: center; gap: 8px; }
.transfer-mapping { font-size: 12px; overflow-wrap: anywhere; }
.transfer-mapping dd { margin: 4px 0 12px; }
</style>
