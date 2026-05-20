<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">Integrations</p>
        <h1>TriggerSource</h1>
        <p class="page-description">把外部协议事件映射到 Workflow App 的 input bindings，并通过绑定的 WorkflowAppRuntime 创建正式运行。</p>
      </div>
      <Button variant="secondary" :disabled="loading" @click="loadPage">
        <RefreshCw :size="16" />
        刷新
      </Button>
    </header>

    <InlineError :message="errorMessage" />
    <p v-if="statusMessage" class="result-note">{{ statusMessage }}</p>

    <section class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">Runtime</p>
          <h2>选择运行时</h2>
        </div>
        <StatusBadge :tone="selectedRuntime?.observed_state === 'running' ? 'success' : 'neutral'">
          {{ selectedRuntime?.observed_state ?? '未选择' }}
        </StatusBadge>
      </div>
      <EmptyState v-if="!loading && runtimes.length === 0" title="还没有 WorkflowAppRuntime" description="先在应用页创建并启动 runtime，再配置 TriggerSource。" />
      <div v-else class="form-grid">
        <label class="field field--wide">
          <span>WorkflowAppRuntime</span>
          <select v-model="selectedRuntimeId" @change="loadSelectedRuntimeApp">
            <option v-for="runtime in runtimes" :key="runtime.workflow_runtime_id" :value="runtime.workflow_runtime_id">
              {{ runtime.display_name || runtime.workflow_runtime_id }} / {{ runtime.application_id }} / {{ runtime.observed_state }}
            </option>
          </select>
        </label>
      </div>
      <div v-if="selectedRuntime" class="summary-grid">
        <div>
          <span>runtime_id</span>
          <strong>{{ selectedRuntime.workflow_runtime_id }}</strong>
        </div>
        <div>
          <span>application</span>
          <strong>{{ selectedRuntime.application_id }}</strong>
        </div>
        <div>
          <span>desired / observed</span>
          <strong>{{ selectedRuntime.desired_state }} / {{ selectedRuntime.observed_state }}</strong>
        </div>
        <div>
          <span>bindings</span>
          <strong>{{ appInputBindings.length }} input</strong>
        </div>
      </div>
    </section>

    <form class="form-panel" @submit.prevent="submitTriggerSource">
      <div class="section-heading">
        <div>
          <p class="page-kicker">Mapping</p>
          <h2>协议事件到应用输入的映射</h2>
        </div>
        <Button variant="primary" type="submit" :disabled="saving || !selectedRuntime || appInputBindings.length === 0">
          <Save :size="16" />
          创建 TriggerSource
        </Button>
      </div>

      <div class="form-grid">
        <label class="field">
          <span>trigger_source_id</span>
          <input v-model="triggerSourceId" />
        </label>
        <label class="field">
          <span>display_name</span>
          <input v-model="displayName" />
        </label>
        <label class="field">
          <span>trigger_kind</span>
          <select v-model="triggerKind">
            <option value="zeromq-topic">zeromq-topic</option>
            <option value="webhook">webhook</option>
            <option value="mqtt-topic">mqtt-topic</option>
            <option value="plc-signal">plc-signal</option>
          </select>
        </label>
        <label class="field">
          <span>submit_mode</span>
          <select v-model="submitMode">
            <option value="async">async</option>
            <option value="sync">sync</option>
          </select>
        </label>
        <label class="field field--wide">
          <span>endpoint / topic</span>
          <input v-model="endpoint" placeholder="tcp://127.0.0.1:5555" />
        </label>
        <label class="field">
          <span>result_binding</span>
          <select v-model="resultBinding">
            <option v-for="binding in appOutputBindings" :key="binding.binding_id" :value="binding.binding_id">
              {{ binding.binding_id }} / {{ getBindingPayloadTypeId(binding) || 'unknown' }}
            </option>
            <option value="workflow_result">workflow_result</option>
          </select>
        </label>
        <label class="field">
          <span>result_mode</span>
          <select v-model="resultMode">
            <option value="accepted-then-query">accepted-then-query</option>
            <option value="sync-reply">sync-reply</option>
          </select>
        </label>
      </div>

      <div class="trigger-mapping-list">
        <article v-for="row in mappingRows" :key="row.bindingId" class="trigger-mapping-row">
          <div class="trigger-mapping-row__target">
            <strong>{{ row.bindingId }}</strong>
            <span>{{ row.payloadTypeId || 'unknown' }} / {{ row.required ? '必填' : '可选' }}</span>
          </div>
          <label class="field">
            <span>映射方式</span>
            <select v-model="row.mode">
              <option value="source">事件字段</option>
              <option value="static">固定值</option>
              <option value="skip">不映射</option>
            </select>
          </label>
          <label v-if="row.mode === 'source'" class="field trigger-mapping-row__source">
            <span>source path</span>
            <input v-model="row.sourcePath" placeholder="payload.request_image" />
          </label>
          <label v-else-if="row.mode === 'static'" class="field trigger-mapping-row__source">
            <span>固定值</span>
            <input v-model="row.staticValue" placeholder="按字符串或数字提交" />
          </label>
          <p v-else class="trigger-mapping-row__hint">该 binding 不参与当前 TriggerSource。</p>
        </article>
      </div>
    </form>

    <section class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">Existing</p>
          <h2>已有 TriggerSource</h2>
        </div>
        <StatusBadge tone="neutral">{{ triggerSources.length }}</StatusBadge>
      </div>
      <EmptyState v-if="!loading && triggerSources.length === 0" title="还没有 TriggerSource" description="创建后会出现在这里，后续可继续接启停和 health 操作。" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>TriggerSource</th>
              <th>runtime</th>
              <th>kind</th>
              <th>state</th>
              <th>mapping</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="source in triggerSources" :key="source.trigger_source_id">
              <td>
                <strong>{{ source.display_name || source.trigger_source_id }}</strong>
                <span>{{ source.trigger_source_id }}</span>
              </td>
              <td>{{ source.workflow_runtime_id }}</td>
              <td>{{ source.trigger_kind }}</td>
              <td><StatusBadge :tone="source.observed_state === 'running' ? 'success' : 'neutral'">{{ source.observed_state }}</StatusBadge></td>
              <td>{{ Object.keys(source.input_binding_mapping).join(', ') || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw, Save } from '@lucide/vue'

import { useProjectStore } from '@/app/stores/project.store'
import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { getWorkflowApp, type WorkflowAppDocument } from '@/workflows/workflow-editor/services/workflow-app.service'
import { listWorkflowAppRuntimes } from '@/workflows/workflow-editor/services/workflow-runtime.service'
import type { FlowApplicationBinding, WorkflowAppRuntime } from '@/workflows/workflow-editor/types'
import { createWorkflowTriggerSource, listWorkflowTriggerSources, type InputBindingMappingItem, type WorkflowTriggerSource } from '../services/trigger-source.service'

interface MappingRow {
  bindingId: string
  payloadTypeId: string
  required: boolean
  mode: 'source' | 'static' | 'skip'
  sourcePath: string
  staticValue: string
}

const projectStore = useProjectStore()

const loading = ref(false)
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const statusMessage = ref<string | null>(null)
const runtimes = ref<WorkflowAppRuntime[]>([])
const triggerSources = ref<WorkflowTriggerSource[]>([])
const workflowApp = ref<WorkflowAppDocument | null>(null)
const selectedRuntimeId = ref('')
const triggerSourceId = ref('')
const displayName = ref('')
const triggerKind = ref('zeromq-topic')
const submitMode = ref('async')
const endpoint = ref('tcp://127.0.0.1:5555')
const resultBinding = ref('workflow_result')
const resultMode = ref('accepted-then-query')
const mappingRows = ref<MappingRow[]>([])

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const selectedRuntime = computed(() => runtimes.value.find((runtime) => runtime.workflow_runtime_id === selectedRuntimeId.value) ?? null)
const appBindings = computed(() => workflowApp.value?.applicationDocument.application.bindings ?? [])
const appInputBindings = computed(() => appBindings.value.filter((binding) => binding.direction === 'input'))
const appOutputBindings = computed(() => appBindings.value.filter((binding) => binding.direction === 'output'))
const templateInputById = computed(() => new Map((workflowApp.value?.graphDocument.template.template_inputs ?? []).map((input) => [input.input_id, input])))
const templateOutputById = computed(() => new Map((workflowApp.value?.graphDocument.template.template_outputs ?? []).map((output) => [output.output_id, output])))

function getBindingPayloadTypeId(binding: FlowApplicationBinding): string {
  const configPayloadType = binding.config.payload_type_id
  if (typeof configPayloadType === 'string' && configPayloadType.trim()) return configPayloadType.trim()
  const metadataPayloadType = binding.metadata.payload_type_id
  if (typeof metadataPayloadType === 'string' && metadataPayloadType.trim()) return metadataPayloadType.trim()
  const templatePort = binding.direction === 'input' ? templateInputById.value.get(binding.template_port_id) : templateOutputById.value.get(binding.template_port_id)
  return templatePort?.payload_type_id ?? ''
}

function defaultSourcePath(binding: FlowApplicationBinding): string {
  if (binding.binding_id === 'request_image_ref') return 'payload.request_image'
  if (binding.binding_id === 'deployment_request') return 'payload.deployment_request'
  return `payload.${binding.binding_id}`
}

function sanitizeIdentifier(value: string): string {
  return value.replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase() || 'trigger-source'
}

function buildMappingRows(): void {
  mappingRows.value = appInputBindings.value.map((binding) => ({
    bindingId: binding.binding_id,
    payloadTypeId: getBindingPayloadTypeId(binding),
    required: binding.required,
    mode: 'source',
    sourcePath: defaultSourcePath(binding),
    staticValue: '',
  }))
}

function applyRuntimeDefaults(): void {
  const runtime = selectedRuntime.value
  if (!runtime) return
  const suffix = sanitizeIdentifier(runtime.workflow_runtime_id)
  triggerSourceId.value = `zeromq-${suffix}`
  displayName.value = `ZeroMQ ${runtime.display_name || runtime.application_id}`
}

async function loadSelectedRuntimeApp(): Promise<void> {
  const runtime = selectedRuntime.value
  workflowApp.value = null
  mappingRows.value = []
  if (!runtime) return
  try {
    workflowApp.value = await getWorkflowApp(selectedProjectId.value, runtime.application_id)
    resultBinding.value = appOutputBindings.value[0]?.binding_id ?? 'workflow_result'
    buildMappingRows()
    applyRuntimeDefaults()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取 workflow app 失败'
  }
}

async function loadPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  statusMessage.value = null
  try {
    const [runtimeResult, triggerSourceResult] = await Promise.all([
      listWorkflowAppRuntimes({ projectId: selectedProjectId.value, limit: 100 }),
      listWorkflowTriggerSources({ projectId: selectedProjectId.value, limit: 100 }),
    ])
    runtimes.value = runtimeResult.items
    triggerSources.value = triggerSourceResult.items
    selectedRuntimeId.value = selectedRuntimeId.value || runtimes.value[0]?.workflow_runtime_id || ''
    await loadSelectedRuntimeApp()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取 TriggerSource 页面失败'
  } finally {
    loading.value = false
  }
}

function buildTransportConfig(): Record<string, unknown> {
  if (triggerKind.value === 'zeromq-topic') return { bind_endpoint: endpoint.value.trim() }
  return { endpoint: endpoint.value.trim() }
}

function buildInputBindingMapping(): Record<string, InputBindingMappingItem> {
  const mapping: Record<string, InputBindingMappingItem> = {}
  for (const row of mappingRows.value) {
    if (row.mode === 'skip') continue
    if (row.mode === 'static') {
      mapping[row.bindingId] = {
        value: parseScalarValue(row.staticValue),
        required: row.required,
        payload_type_id: row.payloadTypeId || null,
      }
    } else if (row.sourcePath.trim()) {
      mapping[row.bindingId] = {
        source: row.sourcePath.trim(),
        required: row.required,
        payload_type_id: row.payloadTypeId || null,
      }
    }
  }
  return mapping
}

function parseScalarValue(value: string): unknown {
  const trimmedValue = value.trim()
  if (trimmedValue === 'true') return true
  if (trimmedValue === 'false') return false
  if (trimmedValue === 'null') return null
  if (trimmedValue !== '' && !Number.isNaN(Number(trimmedValue))) return Number(trimmedValue)
  return value
}

async function submitTriggerSource(): Promise<void> {
  if (!selectedRuntime.value) return
  saving.value = true
  errorMessage.value = null
  statusMessage.value = null
  try {
    const triggerSource = await createWorkflowTriggerSource({
      projectId: selectedProjectId.value,
      triggerSourceId: triggerSourceId.value.trim(),
      displayName: displayName.value.trim() || triggerSourceId.value.trim(),
      triggerKind: triggerKind.value,
      workflowRuntimeId: selectedRuntime.value.workflow_runtime_id,
      submitMode: submitMode.value,
      enabled: false,
      transportConfig: buildTransportConfig(),
      inputBindingMapping: buildInputBindingMapping(),
      resultMapping: {
        result_binding: resultBinding.value,
        result_mode: resultMode.value,
      },
      resultMode: resultMode.value,
      metadata: { source: 'web-ui-trigger-source-page' },
    })
    statusMessage.value = `已创建 TriggerSource：${triggerSource.trigger_source_id}`
    const triggerSourceResult = await listWorkflowTriggerSources({ projectId: selectedProjectId.value, limit: 100 })
    triggerSources.value = triggerSourceResult.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建 TriggerSource 失败'
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadPage()
})
</script>
