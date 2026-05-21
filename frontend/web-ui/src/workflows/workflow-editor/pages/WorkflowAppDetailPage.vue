<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">Workflow App</p>
        <h1>{{ application?.display_name || applicationId }}</h1>
        <p class="page-description">{{ application?.description || '查看应用合同、HTTP 调用、runtime 和触发入口。' }}</p>
      </div>
      <div class="page-actions">
        <RouterLink to="/workflows/apps" class="ui-button ui-button--secondary ui-button--md">
          <ArrowLeft :size="16" />
          返回列表
        </RouterLink>
        <RouterLink :to="graphEditorPath" class="ui-button ui-button--secondary ui-button--md">
          <Workflow :size="16" />
          打开图编辑
        </RouterLink>
        <Button variant="secondary" :disabled="loading" @click="loadPage">
          <RefreshCw :size="16" />
          刷新
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />
    <p v-if="statusMessage" class="result-note">{{ statusMessage }}</p>

    <EmptyState v-if="!loading && !workflowApp" title="未找到 Workflow App" description="应用可能已删除，或当前项目没有访问权限。" />

    <template v-else-if="workflowApp">
      <section class="resource-section">
        <div class="section-heading">
          <div>
            <p class="page-kicker">Summary</p>
            <h2>应用摘要</h2>
          </div>
          <StatusBadge :tone="selectedRuntime?.observed_state === 'running' ? 'success' : 'neutral'">
            {{ selectedRuntime?.observed_state ?? 'no-runtime' }}
          </StatusBadge>
        </div>
        <div class="summary-grid">
          <div>
            <span>application_id</span>
            <strong>{{ application?.application_id }}</strong>
          </div>
          <div>
            <span>template</span>
            <strong>{{ application?.template_ref.template_id }} / {{ application?.template_ref.template_version }}</strong>
          </div>
          <div>
            <span>input / output</span>
            <strong>{{ inputBindings.length }} / {{ outputBindings.length }}</strong>
          </div>
          <div>
            <span>runtimes / triggers</span>
            <strong>{{ runtimes.length }} / {{ relatedTriggerSources.length }}</strong>
          </div>
        </div>
      </section>

      <section class="resource-section">
        <div class="section-heading">
          <div>
            <p class="page-kicker">Contract</p>
            <h2>App Contract</h2>
          </div>
          <StatusBadge tone="neutral">{{ bindings.length }} bindings</StatusBadge>
        </div>
        <div class="resource-table">
          <table>
            <thead>
              <tr>
                <th>方向</th>
                <th>binding</th>
                <th>payload type</th>
                <th>required</th>
                <th>template port</th>
                <th>kind</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="binding in bindings" :key="`${binding.direction}:${binding.binding_id}`">
                <td>{{ binding.direction }}</td>
                <td>
                  <strong>{{ binding.binding_id }}</strong>
                  <span>{{ binding.config.endpoint || binding.metadata.endpoint || '-' }}</span>
                </td>
                <td>{{ getBindingPayloadTypeId(binding) || 'unknown' }}</td>
                <td>{{ binding.required ? '必填' : '可选' }}</td>
                <td>{{ binding.template_port_id }}</td>
                <td>{{ binding.binding_kind }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="resource-section">
        <div class="section-heading">
          <div>
            <p class="page-kicker">Runtime</p>
            <h2>运行时</h2>
          </div>
          <div class="table-actions table-actions--wrap">
            <Button v-if="canWriteWorkflows" variant="primary" :disabled="runtimeActionBusy" @click="createRuntime">
              <Plus :size="16" />
              创建 runtime
            </Button>
            <RouterLink v-if="selectedRuntime" :to="triggerSourceCreatePath(selectedRuntime.workflow_runtime_id)" class="ui-button ui-button--secondary ui-button--md">
              <PlugZap :size="16" />
              添加触发入口
            </RouterLink>
          </div>
        </div>
        <EmptyState v-if="runtimes.length === 0" title="还没有 WorkflowAppRuntime" description="创建 runtime 后可启动、查看 health，并作为 TriggerSource 的目标。" />
        <div v-else class="resource-table">
          <table>
            <thead>
              <tr>
                <th>runtime</th>
                <th>state</th>
                <th>health / error</th>
                <th>updated</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="runtime in runtimes" :key="runtime.workflow_runtime_id" :class="{ 'is-selected': runtime.workflow_runtime_id === selectedRuntimeId }">
                <td>
                  <strong>{{ runtime.display_name || runtime.workflow_runtime_id }}</strong>
                  <span>{{ runtime.workflow_runtime_id }}</span>
                </td>
                <td>
                  <StatusBadge :tone="runtimeTone(runtime.observed_state)">{{ runtime.desired_state }} / {{ runtime.observed_state }}</StatusBadge>
                </td>
                <td>
                  <strong>{{ runtime.heartbeat_at ? `heartbeat ${formatSystemDateTime(runtime.heartbeat_at)}` : 'no heartbeat' }}</strong>
                  <span>{{ formatError(runtime.last_error) || formatSummary(runtime.health_summary) || '-' }}</span>
                </td>
                <td>{{ formatSystemDateTime(runtime.updated_at) }}</td>
                <td>
                  <div class="table-actions table-actions--wrap">
                    <Button size="sm" variant="ghost" @click="selectRuntime(runtime.workflow_runtime_id)">
                      <MousePointer2 :size="14" />
                      选择
                    </Button>
                    <Button v-if="canWriteWorkflows" size="sm" variant="secondary" :disabled="busyRuntimeId === runtime.workflow_runtime_id" @click="controlRuntime(runtime, 'start')">
                      <Play :size="14" />
                      启动
                    </Button>
                    <Button v-if="canWriteWorkflows" size="sm" variant="secondary" :disabled="busyRuntimeId === runtime.workflow_runtime_id" @click="controlRuntime(runtime, 'stop')">
                      <Square :size="14" />
                      停止
                    </Button>
                    <Button v-if="canWriteWorkflows" size="sm" variant="secondary" :disabled="busyRuntimeId === runtime.workflow_runtime_id" @click="controlRuntime(runtime, 'restart')">
                      <RotateCw :size="14" />
                      重启
                    </Button>
                    <Button size="sm" variant="secondary" :disabled="busyRuntimeId === runtime.workflow_runtime_id" @click="refreshRuntimeHealth(runtime)">
                      <Activity :size="14" />
                      health
                    </Button>
                    <RouterLink :to="triggerSourceCreatePath(runtime.workflow_runtime_id)">添加触发</RouterLink>
                    <Button v-if="canWriteWorkflows" size="sm" variant="danger" :disabled="busyRuntimeId === runtime.workflow_runtime_id || runtime.observed_state === 'running'" @click="deleteRuntime(runtime)">
                      <Trash2 :size="14" />
                      删除
                    </Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="resource-section">
        <div class="section-heading">
          <div>
            <p class="page-kicker">HTTP</p>
            <h2>HTTP 调用</h2>
          </div>
          <StatusBadge :tone="selectedRuntime ? 'info' : 'neutral'">{{ selectedRuntime?.workflow_runtime_id ?? 'select-runtime' }}</StatusBadge>
        </div>
        <div v-if="selectedRuntime" class="form-grid">
          <div class="field field--wide">
            <span>接口</span>
            <pre class="json-view">POST /api/v1/workflows/app-runtimes/{{ selectedRuntime.workflow_runtime_id }}/runs
POST /api/v1/workflows/app-runtimes/{{ selectedRuntime.workflow_runtime_id }}/invoke
GET /api/v1/workflows/runs/{workflow_run_id}</pre>
          </div>
          <label class="field field--wide">
            <span>input_bindings JSON</span>
            <textarea v-model="runtimePayloadText" rows="8" spellcheck="false" />
          </label>
          <div class="table-actions table-actions--wrap field--wide">
            <Button variant="secondary" @click="resetSamplePayload">
              <Copy :size="16" />
              生成示例输入
            </Button>
            <Button v-if="canWriteWorkflows" variant="primary" :disabled="runtimeActionBusy" @click="submitRun('async')">
              <Send :size="16" />
              创建异步 run
            </Button>
            <Button v-if="canWriteWorkflows" variant="secondary" :disabled="runtimeActionBusy" @click="submitRun('sync')">
              <Zap :size="16" />
              同步 invoke
            </Button>
          </div>
        </div>
        <EmptyState v-else title="未选择 runtime" description="创建或选择 runtime 后可查看 HTTP endpoint 和测试调用。" />
      </section>

      <section class="resource-section">
        <div class="section-heading">
          <div>
            <p class="page-kicker">Run Receipt</p>
            <h2>最近调用回执</h2>
          </div>
          <div class="table-actions table-actions--wrap">
            <Button variant="secondary" :disabled="fetchingLastRun || !lastRun" @click="refreshLastRun">
              <RefreshCw :size="16" />
              获取异步结果
            </Button>
            <StatusBadge :tone="lastRun ? runTone(lastRun.state) : 'neutral'">{{ lastRun?.state ?? 'none' }}</StatusBadge>
          </div>
        </div>
        <EmptyState v-if="!lastRun" title="还没有本页发起的 WorkflowRun" description="通过上方 HTTP 调用面板发起后，会显示 run 状态、输出和错误摘要。" />
        <div v-else class="summary-grid">
          <div>
            <span>workflow_run_id</span>
            <strong>{{ lastRun.workflow_run_id }}</strong>
          </div>
          <div>
            <span>state</span>
            <strong>{{ lastRun.state }}</strong>
          </div>
          <div>
            <span>runtime</span>
            <strong>{{ lastRun.workflow_runtime_id }}</strong>
          </div>
          <div>
            <span>finished</span>
            <strong>{{ lastRun.finished_at ? formatSystemDateTime(lastRun.finished_at) : '-' }}</strong>
          </div>
        </div>
        <pre v-if="lastRun" class="json-view">{{ lastRunReceiptText }}</pre>
      </section>

      <section class="resource-section">
        <div class="section-heading">
          <div>
            <p class="page-kicker">Integrations</p>
            <h2>触发入口</h2>
          </div>
          <RouterLink v-if="selectedRuntime" :to="triggerSourceCreatePath(selectedRuntime.workflow_runtime_id)" class="ui-button ui-button--primary ui-button--md">
            <PlugZap :size="16" />
            添加触发入口
          </RouterLink>
        </div>
        <EmptyState v-if="relatedTriggerSources.length === 0" title="还没有 TriggerSource" description="从 runtime 上下文添加后，会按外部协议把事件映射到应用输入。" />
        <div v-else class="resource-table">
          <table>
            <thead>
              <tr>
                <th>TriggerSource</th>
                <th>runtime</th>
                <th>state</th>
                <th>health</th>
                <th>last_error</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="source in relatedTriggerSources" :key="source.trigger_source_id">
                <td>
                  <strong>{{ source.display_name || source.trigger_source_id }}</strong>
                  <span>{{ source.trigger_kind }} / {{ Object.keys(source.input_binding_mapping).join(', ') || '-' }}</span>
                </td>
                <td>{{ source.workflow_runtime_id }}</td>
                <td><StatusBadge :tone="source.observed_state === 'running' ? 'success' : 'neutral'">{{ source.enabled ? 'enabled' : 'disabled' }} / {{ source.observed_state }}</StatusBadge></td>
                <td>{{ formatSummary(source.health_summary) || '-' }}</td>
                <td>{{ formatError(source.last_error) || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import {
  Activity,
  ArrowLeft,
  Copy,
  MousePointer2,
  Play,
  PlugZap,
  Plus,
  RefreshCw,
  RotateCw,
  Send,
  Square,
  Trash2,
  Workflow,
  Zap,
} from '@lucide/vue'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { listWorkflowTriggerSources, type WorkflowTriggerSource } from '@/modules/integrations/services/trigger-source.service'
import { getWorkflowApp, type WorkflowAppDocument } from '../services/workflow-app.service'
import {
  createWorkflowAppRuntime,
  createWorkflowRun,
  deleteWorkflowAppRuntime,
  getWorkflowAppRuntimeHealth,
  getWorkflowRun,
  invokeWorkflowAppRuntime,
  restartWorkflowAppRuntime,
  startWorkflowAppRuntime,
  stopWorkflowAppRuntime,
} from '../services/workflow-runtime.service'
import type { FlowApplicationBinding, WorkflowAppRuntime, WorkflowJsonObject, WorkflowRun } from '../types'

type RuntimeControlAction = 'start' | 'stop' | 'restart'
type RunSubmitMode = 'async' | 'sync'

const route = useRoute()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()

const loading = ref(false)
const errorMessage = ref<string | null>(null)
const statusMessage = ref<string | null>(null)
const workflowApp = ref<WorkflowAppDocument | null>(null)
const triggerSources = ref<WorkflowTriggerSource[]>([])
const selectedRuntimeId = ref('')
const busyRuntimeId = ref<string | null>(null)
const runtimePayloadText = ref('{}')
const lastRun = ref<WorkflowRun | null>(null)
const fetchingLastRun = ref(false)

const applicationId = computed(() => String(route.params.applicationId ?? ''))
const selectedProjectId = computed(() => projectStore.selectedProjectId)
const canWriteWorkflows = computed(() => sessionStore.hasScopes(['workflows:write']))
const application = computed(() => workflowApp.value?.applicationDocument.application ?? null)
const graph = computed(() => workflowApp.value?.graphDocument.template ?? null)
const bindings = computed(() => application.value?.bindings ?? [])
const inputBindings = computed(() => bindings.value.filter((binding) => binding.direction === 'input'))
const outputBindings = computed(() => bindings.value.filter((binding) => binding.direction === 'output'))
const runtimes = computed(() => workflowApp.value?.runtimes ?? [])
const selectedRuntime = computed(() => runtimes.value.find((runtime) => runtime.workflow_runtime_id === selectedRuntimeId.value) ?? workflowApp.value?.primaryRuntime ?? runtimes.value[0] ?? null)
const runtimeActionBusy = computed(() => busyRuntimeId.value !== null || loading.value)
const graphEditorPath = computed(() => `/workflows/graph/apps/${encodeURIComponent(applicationId.value)}`)
const templateInputById = computed(() => new Map((graph.value?.template_inputs ?? []).map((input) => [input.input_id, input])))
const templateOutputById = computed(() => new Map((graph.value?.template_outputs ?? []).map((output) => [output.output_id, output])))
const relatedTriggerSources = computed(() => {
  const runtimeIds = new Set(runtimes.value.map((runtime) => runtime.workflow_runtime_id))
  return triggerSources.value.filter((source) => runtimeIds.has(source.workflow_runtime_id))
})
const lastRunReceiptText = computed(() => {
  if (!lastRun.value) return ''
  return JSON.stringify(
    {
      workflow_run_id: lastRun.value.workflow_run_id,
      state: lastRun.value.state,
      outputs: lastRun.value.outputs,
      template_outputs: lastRun.value.template_outputs,
      error_message: lastRun.value.error_message,
      metadata: lastRun.value.metadata,
    },
    null,
    2,
  )
})

function getBindingPayloadTypeId(binding: FlowApplicationBinding): string {
  const configPayloadType = binding.config.payload_type_id
  if (typeof configPayloadType === 'string' && configPayloadType.trim()) return configPayloadType.trim()
  const metadataPayloadType = binding.metadata.payload_type_id
  if (typeof metadataPayloadType === 'string' && metadataPayloadType.trim()) return metadataPayloadType.trim()
  const templatePort = binding.direction === 'input' ? templateInputById.value.get(binding.template_port_id) : templateOutputById.value.get(binding.template_port_id)
  return templatePort?.payload_type_id ?? ''
}

function runtimeTone(state: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (state === 'running') return 'success'
  if (state === 'failed') return 'danger'
  if (state === 'starting' || state === 'stopping') return 'warning'
  return 'neutral'
}

function runTone(state: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (state === 'succeeded') return 'success'
  if (state === 'failed' || state === 'timeout') return 'danger'
  if (state === 'running' || state === 'queued') return 'warning'
  if (state === 'cancelled') return 'neutral'
  return 'info'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function formatError(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function formatSummary(value: WorkflowJsonObject | null | undefined): string {
  if (!value || Object.keys(value).length === 0) return ''
  const healthState = value.state ?? value.status ?? value.adapter_running ?? value.healthy
  if (healthState !== undefined) return String(healthState)
  return JSON.stringify(value)
}

function sampleValueForPayloadType(payloadTypeId: string, bindingId: string): unknown {
  if (bindingId.includes('deployment_request')) return { request_id: 'manual-test', source: 'web-ui' }
  if (payloadTypeId.includes('image-ref')) return { object_key: 'workflows/inputs/sample.png' }
  if (payloadTypeId.includes('image-base64')) return 'data:image/png;base64,...'
  if (payloadTypeId.includes('boolean')) return false
  if (payloadTypeId.includes('number') || payloadTypeId.includes('float') || payloadTypeId.includes('integer')) return 0
  if (payloadTypeId.includes('object') || payloadTypeId.includes('json')) return {}
  if (payloadTypeId.includes('array') || payloadTypeId.includes('list')) return []
  return ''
}

function buildSampleInputBindings(): WorkflowJsonObject {
  const sampleInputBindings: WorkflowJsonObject = {}
  for (const binding of inputBindings.value) {
    const payloadTypeId = getBindingPayloadTypeId(binding)
    const shouldInclude = binding.required || binding.binding_id.includes('request_image') || binding.binding_id.includes('deployment_request')
    if (shouldInclude) sampleInputBindings[binding.binding_id] = sampleValueForPayloadType(payloadTypeId, binding.binding_id)
  }
  return sampleInputBindings
}

function resetSamplePayload(): void {
  runtimePayloadText.value = JSON.stringify(buildSampleInputBindings(), null, 2)
}

function parseInputBindings(): WorkflowJsonObject {
  const parsedValue = JSON.parse(runtimePayloadText.value || '{}') as unknown
  if (!isRecord(parsedValue)) throw new Error('input_bindings 必须是 JSON object')
  const candidate = parsedValue.input_bindings
  if (candidate !== undefined) {
    if (!isRecord(candidate)) throw new Error('input_bindings 必须是 JSON object')
    return candidate
  }
  return parsedValue
}

function selectRuntime(runtimeId: string): void {
  selectedRuntimeId.value = runtimeId
}

function replaceRuntime(updatedRuntime: WorkflowAppRuntime): void {
  if (!workflowApp.value) return
  const runtimeIndex = workflowApp.value.runtimes.findIndex((runtime) => runtime.workflow_runtime_id === updatedRuntime.workflow_runtime_id)
  if (runtimeIndex >= 0) workflowApp.value.runtimes.splice(runtimeIndex, 1, updatedRuntime)
  else workflowApp.value.runtimes.unshift(updatedRuntime)
  workflowApp.value.primaryRuntime = workflowApp.value.runtimes.find((runtime) => runtime.observed_state === 'running') ?? workflowApp.value.runtimes[0] ?? null
}

function triggerSourceCreatePath(runtimeId?: string): string {
  const query = new URLSearchParams({ application_id: applicationId.value, mode: 'create' })
  if (runtimeId) query.set('runtime_id', runtimeId)
  return `/integrations/trigger-sources?${query.toString()}`
}

async function loadPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  statusMessage.value = null
  try {
    const [appDocument, triggerSourceResult] = await Promise.all([
      getWorkflowApp(selectedProjectId.value, applicationId.value),
      listWorkflowTriggerSources({ projectId: selectedProjectId.value, limit: 100 }),
    ])
    workflowApp.value = appDocument
    triggerSources.value = triggerSourceResult.items
    const queryRuntimeId = typeof route.query.runtime_id === 'string' ? route.query.runtime_id : ''
    selectedRuntimeId.value = appDocument.runtimes.some((runtime) => runtime.workflow_runtime_id === queryRuntimeId)
      ? queryRuntimeId
      : appDocument.primaryRuntime?.workflow_runtime_id ?? appDocument.runtimes[0]?.workflow_runtime_id ?? ''
    resetSamplePayload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取 Workflow App 详情失败'
  } finally {
    loading.value = false
  }
}

async function createRuntime(): Promise<void> {
  if (!application.value || !canWriteWorkflows.value) return
  busyRuntimeId.value = 'new'
  errorMessage.value = null
  try {
    const runtime = await createWorkflowAppRuntime({
      projectId: selectedProjectId.value,
      applicationId: application.value.application_id,
      displayName: `${application.value.display_name || application.value.application_id} runtime`,
      metadata: { source: 'web-ui-app-detail' },
    })
    replaceRuntime(runtime)
    selectedRuntimeId.value = runtime.workflow_runtime_id
    statusMessage.value = `已创建 runtime：${runtime.workflow_runtime_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建 runtime 失败'
  } finally {
    busyRuntimeId.value = null
  }
}

async function controlRuntime(runtime: WorkflowAppRuntime, action: RuntimeControlAction): Promise<void> {
  if (!canWriteWorkflows.value) return
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    const actions = {
      start: startWorkflowAppRuntime,
      stop: stopWorkflowAppRuntime,
      restart: restartWorkflowAppRuntime,
    }
    const updatedRuntime = await actions[action](runtime.workflow_runtime_id)
    replaceRuntime(updatedRuntime)
    statusMessage.value = `runtime ${action} 已提交：${updatedRuntime.workflow_runtime_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : `runtime ${action} 失败`
  } finally {
    busyRuntimeId.value = null
  }
}

async function refreshRuntimeHealth(runtime: WorkflowAppRuntime): Promise<void> {
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    const updatedRuntime = await getWorkflowAppRuntimeHealth(runtime.workflow_runtime_id)
    replaceRuntime(updatedRuntime)
    statusMessage.value = `已更新 runtime health：${updatedRuntime.workflow_runtime_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取 runtime health 失败'
  } finally {
    busyRuntimeId.value = null
  }
}

async function deleteRuntime(runtime: WorkflowAppRuntime): Promise<void> {
  if (!workflowApp.value || !canWriteWorkflows.value || runtime.observed_state === 'running') return
  const confirmed = window.confirm(`删除 runtime ${runtime.workflow_runtime_id}？`)
  if (!confirmed) return
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    await deleteWorkflowAppRuntime(runtime.workflow_runtime_id)
    workflowApp.value.runtimes = workflowApp.value.runtimes.filter((item) => item.workflow_runtime_id !== runtime.workflow_runtime_id)
    workflowApp.value.primaryRuntime = workflowApp.value.runtimes.find((item) => item.observed_state === 'running') ?? workflowApp.value.runtimes[0] ?? null
    selectedRuntimeId.value = workflowApp.value.primaryRuntime?.workflow_runtime_id ?? workflowApp.value.runtimes[0]?.workflow_runtime_id ?? ''
    statusMessage.value = `已删除 runtime：${runtime.workflow_runtime_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除 runtime 失败'
  } finally {
    busyRuntimeId.value = null
  }
}

async function submitRun(mode: RunSubmitMode): Promise<void> {
  const runtime = selectedRuntime.value
  if (!runtime || !canWriteWorkflows.value) return
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    const inputBindings = parseInputBindings()
    const run = mode === 'async'
      ? await createWorkflowRun(runtime.workflow_runtime_id, { inputBindings, executionMetadata: { source: 'web-ui-app-detail' } })
      : await invokeWorkflowAppRuntime(runtime.workflow_runtime_id, { inputBindings, executionMetadata: { source: 'web-ui-app-detail' } })
    lastRun.value = run
    statusMessage.value = `已创建 WorkflowRun：${run.workflow_run_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调用 runtime 失败'
  } finally {
    busyRuntimeId.value = null
  }
}

async function refreshLastRun(): Promise<void> {
  const run = lastRun.value
  if (!run) return
  fetchingLastRun.value = true
  errorMessage.value = null
  try {
    lastRun.value = await getWorkflowRun(run.workflow_run_id)
    statusMessage.value = `已获取 WorkflowRun 结果：${run.workflow_run_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '获取 WorkflowRun 结果失败'
  } finally {
    fetchingLastRun.value = false
  }
}

onMounted(loadPage)
</script>