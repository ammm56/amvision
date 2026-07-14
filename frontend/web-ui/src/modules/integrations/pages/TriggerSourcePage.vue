<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">Integrations</p>
        <div class="heading-with-hint">
          <h1>TriggerSource</h1>
          <InfoHint text="从 WorkflowAppRuntime 创建外部协议入口，把协议事件映射到 Workflow App input bindings。" />
        </div>
      </div>
      <div class="page-actions">
        <RouterLink v-if="selectedRuntime" :to="appDetailPath" class="ui-button ui-button--secondary ui-button--md">
          <Workflow :size="16" />
          返回应用
        </RouterLink>
        <Button variant="secondary" :disabled="loading" @click="loadPage">
          <RefreshCw :size="16" />
          刷新
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />
    <p v-if="statusMessage" class="result-note">{{ statusMessage }}</p>

    <form class="form-panel" @submit.prevent="submitTriggerSource">
      <div class="section-heading">
        <div>
          <p class="page-kicker">Create</p>
          <h2>添加触发入口</h2>
        </div>
        <Button variant="primary" type="submit" :disabled="saving || !selectedRuntime">
          <Save :size="16" />
          创建 TriggerSource
        </Button>
      </div>

      <EmptyState v-if="!loading && runtimes.length === 0" title="还没有 WorkflowAppRuntime" description="先在应用详情页创建并启动 runtime，再从该 runtime 添加触发入口。" />

      <template v-else>
        <div class="form-grid">
          <label class="field field--wide">
            <span>WorkflowAppRuntime</span>
            <SelectField :model-value="selectedRuntimeId" :options="runtimeOptions" placeholder="选择 runtime" @update:model-value="selectRuntime" />
          </label>
          <label class="field">
            <span>协议模板</span>
            <SelectField :model-value="protocolTemplateId" :options="protocolTemplateOptions" @update:model-value="selectProtocolTemplate" />
          </label>
          <label class="field">
            <span>创建后启用</span>
            <SelectField :model-value="enableAfterCreate" :options="enableAfterCreateOptions" @update:model-value="setEnableAfterCreate" />
          </label>
        </div>

        <div v-if="selectedRuntime" class="summary-grid">
          <div>
            <span>runtime</span>
            <strong>{{ selectedRuntime.workflow_runtime_id }}</strong>
          </div>
          <div>
            <span>application</span>
            <strong>{{ selectedRuntime.application_id }}</strong>
          </div>
          <div>
            <span>state</span>
            <strong>{{ selectedRuntime.desired_state }} / {{ selectedRuntime.observed_state }}</strong>
          </div>
          <div>
            <span>bindings</span>
            <strong>{{ appInputBindings.length }} input / {{ appOutputBindings.length }} output</strong>
          </div>
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
            <span>{{ selectedProtocolTemplate.endpointLabel }}</span>
            <input v-model="endpoint" />
          </label>
          <label v-if="selectedProtocolTemplate.templateId === 'zeromq-image-trigger'" class="field">
            <span class="field-label">
              pool_name
              <InfoHint text="ZeroMQ 第二帧图片 bytes 写入的 LocalBufferBroker pool；选项来自后端当前配置。" />
            </span>
            <SelectField
              :model-value="localBufferPoolName"
              :options="localBufferPoolOptions"
              :disabled="localBufferPoolOptions.length === 0"
              placeholder="后端未配置 pool"
              @update:model-value="setLocalBufferPoolName"
            />
          </label>
          <label class="field">
            <span>result_binding</span>
            <SelectField :model-value="resultBinding" :options="resultBindingOptions" @update:model-value="setResultBinding" />
          </label>
        </div>

        <div>
          <div class="section-heading">
            <div>
              <p class="page-kicker">Inference</p>
              <div class="heading-with-hint">
                <h2>自动推断</h2>
                <InfoHint text="自动推断会优先使用 metadata 标记。常见双入口图会同时启用 request_image_base64 和 request_image_ref；ZeroMQ 图片 bytes 默认写入 LocalBuffer，再通过 payload.request_image_ref 映射到 request_image_ref。" />
              </div>
            </div>
            <StatusBadge tone="info">{{ selectedProtocolTemplate.displayName }}</StatusBadge>
          </div>
          <div class="summary-grid">
            <div>
              <span>图片输入</span>
              <strong>{{ inferredImageBindingText }}</strong>
            </div>
            <div>
              <span>请求参数</span>
              <strong>{{ inferredRequestBinding?.binding_id ?? '未找到' }}</strong>
            </div>
            <div>
              <span>HTTP 回执</span>
              <strong>{{ resultBinding }}</strong>
            </div>
            <div>
              <span>submit / ack</span>
              <strong>{{ submitMode }} / {{ ackPolicy }}</strong>
            </div>
          </div>
        </div>

        <details>
          <summary class="section-heading">
            <span>
              <span class="page-kicker">Advanced</span>
              <strong>高级设置与手动 mapping</strong>
            </span>
            <Settings2 :size="16" />
          </summary>

          <div class="form-grid">
            <label class="field">
              <span class="field-label">
                submit_mode
                <InfoHint text="sync 会等待 WorkflowRun 完成并把结果写入协议回包；async 只创建 run，结果需要之后按 workflow_run_id 查询。" />
              </span>
              <SelectField :model-value="submitMode" :options="submitModeOptions" @update:model-value="setSubmitMode" />
            </label>
            <label class="field">
              <span class="field-label">
                result_mode
                <InfoHint text="sync-reply 直接返回 result_binding 的输出；accepted-then-query 返回 run id 让调用方查询；async-report/event-only 预留给后续回调或事件流。" />
              </span>
              <SelectField :model-value="resultMode" :options="resultModeOptions" @update:model-value="setResultMode" />
            </label>
            <label class="field">
              <span class="field-label">
                ack_policy
                <InfoHint text="声明协议层确认时机；当前实际等待主要由 submit_mode 决定。同步回包通常使用 ack-after-run-finished。" />
              </span>
              <SelectField :model-value="ackPolicy" :options="ackPolicyOptions" @update:model-value="setAckPolicy" />
            </label>
            <label class="field">
              <span class="field-label">
                reply_timeout_seconds
                <InfoHint text="同步等待 workflow 结果的最长秒数；需要大于 WinForms/SDK 的 ZeroMQ 等待超时。" />
              </span>
              <input v-model="replyTimeoutSeconds" inputmode="numeric" placeholder="空表示默认" />
            </label>
            <label class="field">
              <span class="field-label">
                debounce_window_ms
                <InfoHint text="保存同一触发源短时间重复事件的去抖窗口配置，后续可由 adapter 或调度层执行；空表示不启用。" />
              </span>
              <input v-model="debounceWindowMs" inputmode="numeric" placeholder="空表示不启用" />
            </label>
            <label class="field">
              <span class="field-label">
                idempotency_key_path
                <InfoHint text="从事件中读取幂等键，例如 payload.request_id；同一键可用于避免重复提交。" />
              </span>
              <input v-model="idempotencyKeyPath" placeholder="payload.request_id" />
            </label>
            <label class="field">
              <span class="field-label">
                WorkflowRun 记录
                <InfoHint text="full 保留完整运行记录；minimal 只写最小状态记录；none 不写 WorkflowRun 数据库记录，仅适合同步高速触发。" />
              </span>
              <SelectField :model-value="workflowRunRecordMode" :options="workflowRunRecordModeOptions" @update:model-value="setWorkflowRunRecordMode" />
            </label>
            <label class="field">
              <span class="field-label">
                返回诊断数据
                <InfoHint text="关闭时不在调用结果中返回 timings 和 node_timings；生产高帧率触发建议关闭，排查问题时再开启。" />
              </span>
              <SelectField :model-value="returnDiagnostics" :options="returnDiagnosticsOptions" @update:model-value="setReturnDiagnostics" />
            </label>
          </div>

          <div class="trigger-mapping-list">
            <article v-for="row in mappingRows" :key="row.bindingId" class="trigger-mapping-row">
              <div class="trigger-mapping-row__target">
                <strong>{{ row.bindingId }}</strong>
                <span>{{ row.payloadTypeId || 'unknown' }} / {{ row.required ? '必填' : '可选' }} / {{ row.inferred ? '已推断' : '手动' }}</span>
              </div>
              <label class="field">
                <span>映射方式</span>
                <SelectField :model-value="row.mode" :options="mappingModeOptions" @update:model-value="setMappingMode(row, $event)" />
              </label>
              <label v-if="row.mode === 'source'" class="field trigger-mapping-row__source">
                <span>source path</span>
                <input v-model="row.sourcePath" placeholder="payload.request_image_ref" />
              </label>
              <label v-else-if="row.mode === 'static'" class="field trigger-mapping-row__source">
                <span>固定值</span>
                <input v-model="row.staticValue" placeholder="按字符串、数字或布尔值提交" />
              </label>
              <p v-else class="trigger-mapping-row__hint">该 binding 不参与当前 TriggerSource。</p>
            </article>
          </div>
        </details>
      </template>
    </form>

    <section class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">Existing</p>
          <h2>已有 TriggerSource</h2>
        </div>
        <StatusBadge tone="neutral">{{ totalTriggerSourceCount }}</StatusBadge>
      </div>
      <EmptyState v-if="!loading && triggerSources.length === 0" title="还没有 TriggerSource" description="创建后会显示启停状态、health、last_error 和映射摘要。" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>TriggerSource</th>
              <th>runtime</th>
              <th>kind</th>
              <th>state</th>
              <th>health</th>
              <th>last_error</th>
              <th>操作</th>
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
              <td>
                <StatusBadge :tone="sourceStateTone(source)">{{ source.enabled ? 'enabled' : 'disabled' }} / {{ source.observed_state }}</StatusBadge>
              </td>
              <td>
                <strong>{{ formatHealthSummary(sourceHealth(source)?.health_summary ?? source.health_summary) || '-' }}</strong>
                <span>{{ formatLastTriggered(sourceHealth(source)?.last_triggered_at ?? source.last_triggered_at) }}</span>
              </td>
              <td>{{ formatError(sourceHealth(source)?.last_error ?? source.last_error) || '-' }}</td>
              <td>
                <div class="table-actions table-actions--wrap">
                  <Button v-if="!source.enabled" size="sm" variant="secondary" :disabled="busyTriggerSourceId === source.trigger_source_id" @click="setTriggerSourceEnabled(source, true)">
                    <Power :size="14" />
                    启用
                  </Button>
                  <Button v-else size="sm" variant="secondary" :disabled="busyTriggerSourceId === source.trigger_source_id" @click="setTriggerSourceEnabled(source, false)">
                    <PowerOff :size="14" />
                    停用
                  </Button>
                  <Button size="sm" variant="secondary" :disabled="busyTriggerSourceId === source.trigger_source_id" @click="refreshTriggerSourceHealth(source)">
                    <Activity :size="14" />
                    health
                  </Button>
                  <Button size="sm" variant="danger" :disabled="busyTriggerSourceId === source.trigger_source_id" @click="deleteTriggerSource(source)">
                    <Trash2 :size="14" />
                    删除
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationControls
        v-if="triggerSources.length > 0"
        class="trigger-source-page__pagination"
        :offset="triggerSourcePagination.offset"
        :limit="triggerSourcePagination.limit"
        :item-count="triggerSources.length"
        :total-count="triggerSourcePagination.totalCount"
        :has-more="triggerSourcePagination.hasMore"
        :disabled="loading"
        @previous="loadPreviousTriggerSourcePage"
        @next="loadNextTriggerSourcePage"
      />
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { Activity, Power, PowerOff, RefreshCw, Save, Settings2, Trash2, Workflow } from '@lucide/vue'

import { useProjectStore } from '@/app/stores/project.store'
import type { PaginationMeta } from '@/shared/api/pagination'
import { getSystemConfig } from '@/shared/api/system-config'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import InfoHint from '@/shared/ui/components/InfoHint.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { getWorkflowApp, type WorkflowAppDocument } from '@/workflows/workflow-editor/services/workflow-app.service'
import { listWorkflowAppRuntimes } from '@/workflows/workflow-editor/services/workflow-runtime.service'
import type { FlowApplicationBinding, WorkflowAppRuntime, WorkflowJsonObject } from '@/workflows/workflow-editor/types'
import {
  createWorkflowTriggerSource,
  deleteWorkflowTriggerSource,
  disableWorkflowTriggerSource,
  enableWorkflowTriggerSource,
  getWorkflowTriggerSourceHealth,
  listWorkflowTriggerSources,
  type InputBindingMappingItem,
  type WorkflowTriggerSource,
  type WorkflowTriggerSourceHealth,
} from '../services/trigger-source.service'

type MappingMode = 'source' | 'static' | 'skip'
type ProtocolTemplateId = 'zeromq-image-trigger' | 'webhook-json'
type WorkflowRunRecordMode = 'full' | 'minimal' | 'none'
type SelectValue = string | number | boolean | null

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

interface MappingRow {
  bindingId: string
  payloadTypeId: string
  required: boolean
  mode: MappingMode
  sourcePath: string
  staticValue: string
  inferred: boolean
}

interface ProtocolTemplateOption {
  templateId: ProtocolTemplateId
  displayName: string
  triggerKind: string
  defaultEndpoint: string
  endpointLabel: string
  submitMode: 'async' | 'sync'
  resultMode: string
  ackPolicy: string
  imageBase64SourcePath: string
  imageRefSourcePath: string
  fallbackImageSourcePath: string
  requestSourcePath: string
  defaultInputBinding: string
  defaultReplyTimeoutSeconds: number
  defaultIdempotencyKeyPath: string
}

const protocolTemplates: ProtocolTemplateOption[] = [
  {
    templateId: 'zeromq-image-trigger',
    displayName: 'ZeroMQ 图片触发',
    triggerKind: 'zeromq-topic',
    defaultEndpoint: 'tcp://127.0.0.1:5555',
    endpointLabel: 'bind_endpoint',
    submitMode: 'sync',
    resultMode: 'sync-reply',
    ackPolicy: 'ack-after-run-finished',
    imageBase64SourcePath: 'payload.request_image_base64',
    imageRefSourcePath: 'payload.request_image_ref',
    fallbackImageSourcePath: 'payload.request_image_ref',
    requestSourcePath: 'payload.deployment_request',
    defaultInputBinding: 'request_image_ref',
    defaultReplyTimeoutSeconds: 30,
    defaultIdempotencyKeyPath: 'payload.idempotency_key',
  },
  {
    templateId: 'webhook-json',
    displayName: 'Webhook JSON',
    triggerKind: 'webhook',
    defaultEndpoint: '/workflow-triggers/{trigger_source_id}',
    endpointLabel: 'webhook path',
    submitMode: 'sync',
    resultMode: 'sync-reply',
    ackPolicy: 'ack-after-run-finished',
    imageBase64SourcePath: 'payload.request_image_base64',
    imageRefSourcePath: 'payload.request_image_ref',
    fallbackImageSourcePath: 'payload.request_image_base64',
    requestSourcePath: 'payload.deployment_request',
    defaultInputBinding: 'request_image_base64',
    defaultReplyTimeoutSeconds: 30,
    defaultIdempotencyKeyPath: 'payload.idempotency_key',
  },
]

const enableAfterCreateOptions: SelectOption[] = [
  { label: '否，先保存配置', value: 'false' },
  { label: '是，创建后启用', value: 'true' },
]

const submitModeOptions: SelectOption[] = [
  { label: 'sync', value: 'sync', description: '等待 WorkflowRun 完成并返回结果' },
  { label: 'async', value: 'async', description: '只创建 WorkflowRun，之后查询结果' },
]

const resultModeOptions: SelectOption[] = [
  { label: 'sync-reply', value: 'sync-reply', description: '同步协议回包直接带结果' },
  { label: 'accepted-then-query', value: 'accepted-then-query', description: '回包带 run id，调用方之后查询' },
  { label: 'async-report', value: 'async-report', description: '预留异步回调模式' },
  { label: 'event-only', value: 'event-only', description: '只记录事件，不要求结果回包' },
]

const ackPolicyOptions: SelectOption[] = [
  { label: 'ack-after-run-finished', value: 'ack-after-run-finished', description: 'run 完成后确认' },
  { label: 'ack-after-run-created', value: 'ack-after-run-created', description: 'run 创建后确认' },
  { label: 'ack-after-received', value: 'ack-after-received', description: '收到事件后确认' },
]

const workflowRunRecordModeOptions: SelectOption[] = [
  { label: 'minimal', value: 'minimal', description: '只写最小状态记录，适合高速触发' },
  { label: 'full', value: 'full', description: '保留完整 WorkflowRun 记录' },
  { label: 'none', value: 'none', description: '同步调用不写 WorkflowRun 数据库记录' },
]

const returnDiagnosticsOptions: SelectOption[] = [
  { label: '否', value: 'false', description: '生产默认，不返回 timings 和 node_timings' },
  { label: '是', value: 'true', description: '排查问题时返回耗时诊断' },
]

const mappingModeOptions: SelectOption[] = [
  { label: '事件字段', value: 'source', description: '从外部事件 payload/metadata 中读取' },
  { label: '固定值', value: 'static', description: '每次触发都传同一个值' },
  { label: '不映射', value: 'skip', description: '这个 binding 不参与当前入口' },
]

const route = useRoute()
const projectStore = useProjectStore()

const loading = ref(false)
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const statusMessage = ref<string | null>(null)
const runtimes = ref<WorkflowAppRuntime[]>([])
const triggerSources = ref<WorkflowTriggerSource[]>([])
const triggerSourcePagination = ref<PaginationMeta>(createPaginationState())
const backendServiceConfig = ref<Record<string, unknown>>({})
const workflowApp = ref<WorkflowAppDocument | null>(null)
const selectedRuntimeId = ref('')
const protocolTemplateId = ref<ProtocolTemplateId>('zeromq-image-trigger')
const triggerSourceId = ref('')
const displayName = ref('')
const endpoint = ref('tcp://127.0.0.1:5555')
const localBufferPoolName = ref('')
const submitMode = ref<'async' | 'sync'>('sync')
const resultBinding = ref('core_output_http_response')
const resultMode = ref('sync-reply')
const ackPolicy = ref('ack-after-run-finished')
const replyTimeoutSeconds = ref('30')
const debounceWindowMs = ref('')
const idempotencyKeyPath = ref('')
const workflowRunRecordMode = ref<WorkflowRunRecordMode>('minimal')
const returnDiagnostics = ref('false')
const enableAfterCreate = ref('false')
const mappingRows = ref<MappingRow[]>([])
const busyTriggerSourceId = ref<string | null>(null)
const healthByTriggerSourceId = ref<Record<string, WorkflowTriggerSourceHealth>>({})

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const selectedProtocolTemplate = computed(() => protocolTemplates.find((template) => template.templateId === protocolTemplateId.value) ?? protocolTemplates[0])
const selectedRuntime = computed(() => runtimes.value.find((runtime) => runtime.workflow_runtime_id === selectedRuntimeId.value) ?? null)
const appDetailPath = computed(() => selectedRuntime.value ? `/workflows/apps/${encodeURIComponent(selectedRuntime.value.application_id)}?runtime_id=${encodeURIComponent(selectedRuntime.value.workflow_runtime_id)}` : '/workflows/apps')
const application = computed(() => workflowApp.value?.applicationDocument.application ?? null)
const graph = computed(() => workflowApp.value?.graphDocument.template ?? null)
const appBindings = computed(() => application.value?.bindings ?? [])
const appInputBindings = computed(() => appBindings.value.filter((binding) => binding.direction === 'input'))
const appOutputBindings = computed(() => appBindings.value.filter((binding) => binding.direction === 'output'))
const templateInputById = computed(() => new Map((graph.value?.template_inputs ?? []).map((input) => [input.input_id, input])))
const templateOutputById = computed(() => new Map((graph.value?.template_outputs ?? []).map((output) => [output.output_id, output])))
const inferredImageBindings = computed(() => findImageInputBindings())
const inferredImageBinding = computed(() => inferredImageBindings.value[0] ?? null)
const inferredImageBindingText = computed(() => {
  if (appInputBindings.value.length === 0) return '无需外部输入'
  const bindingIds = inferredImageBindings.value.map((binding) => binding.binding_id)
  return bindingIds.length > 0 ? bindingIds.join(' / ') : '未找到'
})
const inferredRequestBinding = computed(() => findRequestInputBinding())
const runtimeOptions = computed<SelectOption[]>(() => [
  { label: '选择 runtime', value: '' },
  ...runtimes.value.map((runtime) => ({
    label: `${runtime.display_name || runtime.workflow_runtime_id} / ${runtime.application_id} / ${runtime.observed_state}`,
    value: runtime.workflow_runtime_id,
  })),
])
const protocolTemplateOptions = computed<SelectOption[]>(() => protocolTemplates.map((template) => ({
  label: template.displayName,
  value: template.templateId,
  description: template.templateId === 'zeromq-image-trigger' ? 'multipart bytes -> payload.request_image_ref' : 'JSON body -> payload.request_image_base64',
})))
const resultBindingOptions = computed<SelectOption[]>(() => [
  ...appOutputBindings.value.map((binding) => ({
    label: `${binding.binding_id} / ${getBindingPayloadTypeId(binding) || 'unknown'}`,
    value: binding.binding_id,
  })),
  { label: 'workflow_result', value: 'workflow_result' },
])
const totalTriggerSourceCount = computed(() => triggerSourcePagination.value.totalCount ?? triggerSources.value.length)
const localBufferBrokerConfig = computed(() => {
  const value = backendServiceConfig.value.local_buffer_broker
  return isRecord(value) ? value : {}
})
const configuredLocalBufferPoolNames = computed(() => {
  const pools = localBufferBrokerConfig.value.pools
  if (!Array.isArray(pools)) return []
  return pools
    .map((pool) => {
      if (!isRecord(pool)) return ''
      const poolName = pool.pool_name
      return typeof poolName === 'string' ? poolName.trim() : ''
    })
    .filter((poolName): poolName is string => poolName.length > 0)
})
const localBufferDefaultPoolName = computed(() => {
  const defaultPoolName = localBufferBrokerConfig.value.default_pool_name
  return typeof defaultPoolName === 'string' ? defaultPoolName.trim() : ''
})
const localBufferPoolOptions = computed<SelectOption[]>(() => configuredLocalBufferPoolNames.value.map((poolName) => ({
  label: poolName,
  value: poolName,
})))

function readQueryString(name: string): string {
  const value = route.query[name]
  if (Array.isArray(value)) return value[0] ?? ''
  return typeof value === 'string' ? value : ''
}

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

async function selectRuntime(value: SelectValue): Promise<void> {
  selectedRuntimeId.value = selectValueToString(value)
  await loadSelectedRuntimeApp()
}

function selectProtocolTemplate(value: SelectValue): void {
  const nextValue = selectValueToString(value)
  protocolTemplateId.value = nextValue === 'webhook-json' ? 'webhook-json' : 'zeromq-image-trigger'
  applyProtocolTemplateDefaults()
}

function setEnableAfterCreate(value: SelectValue): void {
  enableAfterCreate.value = selectValueToString(value) === 'true' ? 'true' : 'false'
}

function setResultBinding(value: SelectValue): void {
  resultBinding.value = selectValueToString(value)
}

function setLocalBufferPoolName(value: SelectValue): void {
  const nextValue = selectValueToString(value).trim()
  localBufferPoolName.value = nextValue
}

function syncLocalBufferPoolSelection(): void {
  const configuredPoolNames = configuredLocalBufferPoolNames.value
  const currentPoolName = localBufferPoolName.value.trim()
  if (currentPoolName && configuredPoolNames.includes(currentPoolName)) return
  if (localBufferDefaultPoolName.value && configuredPoolNames.includes(localBufferDefaultPoolName.value)) {
    localBufferPoolName.value = localBufferDefaultPoolName.value
    return
  }
  localBufferPoolName.value = configuredPoolNames[0] ?? ''
}

function resolveLocalBufferPoolName(): string {
  const selectedPoolName = localBufferPoolName.value.trim()
  if (selectedPoolName) return selectedPoolName
  if (localBufferDefaultPoolName.value) return localBufferDefaultPoolName.value
  return configuredLocalBufferPoolNames.value[0] ?? ''
}

function setSubmitMode(value: SelectValue): void {
  submitMode.value = selectValueToString(value) === 'async' ? 'async' : 'sync'
  if (submitMode.value === 'async' && workflowRunRecordMode.value === 'none') {
    workflowRunRecordMode.value = 'minimal'
  }
}

function setResultMode(value: SelectValue): void {
  resultMode.value = selectValueToString(value) || 'sync-reply'
}

function setAckPolicy(value: SelectValue): void {
  ackPolicy.value = selectValueToString(value) || 'ack-after-run-finished'
}

function setWorkflowRunRecordMode(value: SelectValue): void {
  const nextValue = selectValueToString(value)
  workflowRunRecordMode.value = nextValue === 'full' || nextValue === 'none' ? nextValue : 'minimal'
  if (submitMode.value === 'async' && workflowRunRecordMode.value === 'none') {
    workflowRunRecordMode.value = 'minimal'
  }
}

function setReturnDiagnostics(value: SelectValue): void {
  returnDiagnostics.value = selectValueToString(value) === 'true' ? 'true' : 'false'
}

function setMappingMode(row: MappingRow, value: SelectValue): void {
  const nextValue = selectValueToString(value)
  row.mode = nextValue === 'static' || nextValue === 'skip' ? nextValue : 'source'
}

function getBindingPayloadTypeId(binding: FlowApplicationBinding): string {
  const configPayloadType = binding.config.payload_type_id
  if (typeof configPayloadType === 'string' && configPayloadType.trim()) return configPayloadType.trim()
  const metadataPayloadType = binding.metadata.payload_type_id
  if (typeof metadataPayloadType === 'string' && metadataPayloadType.trim()) return metadataPayloadType.trim()
  const templatePort = binding.direction === 'input' ? templateInputById.value.get(binding.template_port_id) : templateOutputById.value.get(binding.template_port_id)
  return templatePort?.payload_type_id ?? ''
}

function sanitizeIdentifier(value: string): string {
  return value.replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase() || 'trigger-source'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseOptionalNumber(value: string): number | null {
  const trimmedValue = value.trim()
  if (!trimmedValue) return null
  const parsedValue = Number(trimmedValue)
  return Number.isFinite(parsedValue) ? parsedValue : null
}

function readMetadataBindingId(metadata: WorkflowJsonObject | undefined, key: string): string {
  const value = metadata?.[key]
  return typeof value === 'string' ? value.trim() : ''
}

function findInputBindingById(bindingId: string): FlowApplicationBinding | null {
  if (!bindingId) return null
  return appInputBindings.value.find((binding) => binding.binding_id === bindingId) ?? null
}

function findBindingFromMetadata(key: string): FlowApplicationBinding | null {
  const appMetadataBinding = findInputBindingById(readMetadataBindingId(application.value?.metadata, key))
  if (appMetadataBinding) return appMetadataBinding
  const runtimeMetadataBinding = findInputBindingById(readMetadataBindingId(selectedRuntime.value?.metadata, key))
  if (runtimeMetadataBinding) return runtimeMetadataBinding
  for (const binding of appInputBindings.value) {
    const metadataValue = binding.metadata[key]
    if (metadataValue === true) return binding
    if (typeof metadataValue === 'string') {
      const matchedBinding = findInputBindingById(metadataValue)
      if (matchedBinding) return matchedBinding
    }
  }
  return null
}

function isImageBase64Binding(binding: FlowApplicationBinding): boolean {
  const payloadTypeId = getBindingPayloadTypeId(binding)
  return binding.binding_id === 'request_image_base64' || payloadTypeId.includes('image-base64')
}

function isImageRefBinding(binding: FlowApplicationBinding): boolean {
  const payloadTypeId = getBindingPayloadTypeId(binding)
  return binding.binding_id === 'request_image_ref' || payloadTypeId.includes('image-ref')
}

function isImageInputBinding(binding: FlowApplicationBinding): boolean {
  return isImageBase64Binding(binding) || isImageRefBinding(binding) || binding.binding_id.includes('image')
}

function addUniqueBinding(bindings: FlowApplicationBinding[], binding: FlowApplicationBinding | null): void {
  if (!binding || bindings.some((item) => item.binding_id === binding.binding_id)) return
  bindings.push(binding)
}

function findImageInputBindings(): FlowApplicationBinding[] {
  const bindings: FlowApplicationBinding[] = []
  const metadataBinding = findBindingFromMetadata('trigger_source_input_binding')
  const imageBase64Binding = appInputBindings.value.find(isImageBase64Binding) ?? null
  const imageRefBinding = appInputBindings.value.find(isImageRefBinding) ?? null
  if (selectedProtocolTemplate.value.templateId === 'zeromq-image-trigger') {
    addUniqueBinding(bindings, imageRefBinding)
    if (metadataBinding && isImageRefBinding(metadataBinding)) addUniqueBinding(bindings, metadataBinding)
  } else {
    addUniqueBinding(bindings, imageBase64Binding)
    addUniqueBinding(bindings, metadataBinding)
    addUniqueBinding(bindings, imageRefBinding)
  }
  if (bindings.length === 0 && selectedProtocolTemplate.value.templateId !== 'zeromq-image-trigger') {
    addUniqueBinding(bindings, appInputBindings.value.find(isImageInputBinding) ?? null)
  }
  return bindings
}

function findRequestInputBinding(): FlowApplicationBinding | null {
  const metadataBinding = findBindingFromMetadata('deployment_instance_id_binding')
  if (metadataBinding) return metadataBinding
  return appInputBindings.value.find((binding) => binding.binding_id === 'deployment_request' || binding.binding_id.includes('deployment_request')) ?? null
}

function findDefaultResultBinding(): string {
  const coreHttpResponse = appOutputBindings.value.find((binding) => binding.binding_id === 'core_output_http_response')
  if (coreHttpResponse) return coreHttpResponse.binding_id
  const httpResponse = appOutputBindings.value.find((binding) => binding.binding_id === 'http_response')
  if (httpResponse) return httpResponse.binding_id
  return appOutputBindings.value[0]?.binding_id ?? 'workflow_result'
}

function defaultSourcePath(binding: FlowApplicationBinding): string {
  if (isImageBase64Binding(binding)) return selectedProtocolTemplate.value.imageBase64SourcePath
  if (isImageRefBinding(binding)) return selectedProtocolTemplate.value.imageRefSourcePath
  if (inferredImageBindings.value.some((item) => item.binding_id === binding.binding_id)) return selectedProtocolTemplate.value.fallbackImageSourcePath
  if (inferredRequestBinding.value?.binding_id === binding.binding_id) return selectedProtocolTemplate.value.requestSourcePath
  if (binding.binding_id === 'deployment_request') return 'payload.deployment_request'
  return `payload.${binding.binding_id}`
}

function buildDefaultEndpoint(template: ProtocolTemplateOption): string {
  const baseEndpoint = template.defaultEndpoint.replace('{trigger_source_id}', triggerSourceId.value)
  if (template.templateId !== 'zeromq-image-trigger') return baseEndpoint
  return allocateZeroMqTcpEndpoint(baseEndpoint, collectUsedZeroMqBindEndpoints())
}

function collectUsedZeroMqBindEndpoints(): string[] {
  return triggerSources.value
    .filter((source) => source.trigger_kind === 'zeromq-topic')
    .map((source) => source.transport_config?.bind_endpoint)
    .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
}

function allocateZeroMqTcpEndpoint(baseEndpoint: string, usedEndpoints: string[]): string {
  const parsedBase = parseZeroMqTcpEndpoint(baseEndpoint)
  if (!parsedBase) return baseEndpoint
  const usedPorts = new Set<number>()
  for (const usedEndpoint of usedEndpoints) {
    const parsedUsed = parseZeroMqTcpEndpoint(usedEndpoint)
    if (!parsedUsed) continue
    if (!zeroMqTcpHostsCanConflict(parsedBase.host, parsedUsed.host)) continue
    usedPorts.add(parsedUsed.port)
  }
  let candidatePort = parsedBase.port
  while (usedPorts.has(candidatePort) && candidatePort < 65535) {
    candidatePort += 1
  }
  return `${parsedBase.prefix}${candidatePort}`
}

function parseZeroMqTcpEndpoint(endpoint: string): { prefix: string; host: string; port: number } | null {
  const trimmedEndpoint = endpoint.trim()
  const match = /^tcp:\/\/(.+):(\d+)$/i.exec(trimmedEndpoint)
  if (!match) return null
  const port = Number.parseInt(match[2], 10)
  if (!Number.isInteger(port) || port <= 0 || port > 65535) return null
  const host = match[1].trim().toLowerCase()
  if (!host) return null
  return {
    prefix: trimmedEndpoint.slice(0, trimmedEndpoint.length - match[2].length),
    host,
    port,
  }
}

function zeroMqTcpHostsCanConflict(leftHost: string, rightHost: string): boolean {
  return leftHost === rightHost || isZeroMqTcpWildcardHost(leftHost) || isZeroMqTcpWildcardHost(rightHost)
}

function isZeroMqTcpWildcardHost(host: string): boolean {
  return host === '*' || host === '0.0.0.0' || host === '::' || host === '[::]'
}

function buildMappingRows(): void {
  mappingRows.value = appInputBindings.value.map((binding) => {
    const inferred = inferredImageBindings.value.some((item) => item.binding_id === binding.binding_id) || binding.binding_id === inferredRequestBinding.value?.binding_id
    const zeromqBase64Image = selectedProtocolTemplate.value.templateId === 'zeromq-image-trigger' && isImageBase64Binding(binding)
    return {
      bindingId: binding.binding_id,
      payloadTypeId: getBindingPayloadTypeId(binding),
      required: binding.required,
      mode: inferred || (binding.required && !zeromqBase64Image) ? 'source' : 'skip',
      sourcePath: defaultSourcePath(binding),
      staticValue: '',
      inferred,
    }
  })
}

function applyProtocolTemplateDefaults(): void {
  const runtime = selectedRuntime.value
  const template = selectedProtocolTemplate.value
  submitMode.value = template.submitMode
  resultMode.value = template.resultMode
  ackPolicy.value = template.ackPolicy
  const runtimeSuffix = sanitizeIdentifier(runtime?.workflow_runtime_id || runtime?.application_id || 'runtime')
  const templatePrefix = template.templateId === 'webhook-json' ? 'webhook' : 'zeromq'
  triggerSourceId.value = `${templatePrefix}-${runtimeSuffix}`
  displayName.value = `${template.displayName} ${runtime?.display_name || runtime?.application_id || ''}`.trim()
  endpoint.value = buildDefaultEndpoint(template)
  syncLocalBufferPoolSelection()
  resultBinding.value = findDefaultResultBinding()
  replyTimeoutSeconds.value = String(template.defaultReplyTimeoutSeconds)
  idempotencyKeyPath.value = template.defaultIdempotencyKeyPath
  workflowRunRecordMode.value = template.templateId === 'zeromq-image-trigger' ? 'minimal' : 'full'
  returnDiagnostics.value = 'false'
  buildMappingRows()
}

async function loadSelectedRuntimeApp(): Promise<void> {
  const runtime = selectedRuntime.value
  workflowApp.value = null
  mappingRows.value = []
  if (!runtime) return
  try {
    workflowApp.value = await getWorkflowApp(selectedProjectId.value, runtime.application_id)
    applyProtocolTemplateDefaults()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取 Workflow App 失败'
  }
}

async function loadPage(options: { triggerSourceOffset?: number; resetTriggerSourcePage?: boolean; preserveStatusMessage?: boolean } = {}): Promise<void> {
  if (!selectedProjectId.value) {
    runtimes.value = []
    triggerSources.value = []
    workflowApp.value = null
    triggerSourcePagination.value = createPaginationState()
    return
  }
  loading.value = true
  errorMessage.value = null
  if (!options.preserveStatusMessage) {
    statusMessage.value = null
  }
  try {
    const triggerSourceOffset = options.resetTriggerSourcePage ? 0 : options.triggerSourceOffset ?? triggerSourcePagination.value.offset
    const [configResult, runtimeResult, triggerSourceResult] = await Promise.all([
      getSystemConfig(),
      listWorkflowAppRuntimes({ projectId: selectedProjectId.value, limit: 100 }),
      listWorkflowTriggerSources({
        projectId: selectedProjectId.value,
        offset: triggerSourceOffset,
        limit: triggerSourcePagination.value.limit,
      }),
    ])
    backendServiceConfig.value = configResult.config
    syncLocalBufferPoolSelection()
    runtimes.value = runtimeResult.items
    triggerSources.value = triggerSourceResult.items
    triggerSourcePagination.value = triggerSourceResult.pagination
    const queryRuntimeId = readQueryString('runtime_id')
    const queryApplicationId = readQueryString('application_id')
    const contextRuntime = runtimes.value.find((runtime) => runtime.workflow_runtime_id === queryRuntimeId)
      ?? runtimes.value.find((runtime) => runtime.application_id === queryApplicationId)
      ?? runtimes.value.find((runtime) => runtime.workflow_runtime_id === selectedRuntimeId.value)
      ?? runtimes.value[0]
    selectedRuntimeId.value = contextRuntime?.workflow_runtime_id ?? ''
    await loadSelectedRuntimeApp()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取 TriggerSource 页面失败'
  } finally {
    loading.value = false
  }
}

function buildTransportConfig(): WorkflowJsonObject {
  const normalizedEndpoint = endpoint.value.trim().replace('{trigger_source_id}', triggerSourceId.value.trim())
  if (selectedProtocolTemplate.value.templateId === 'zeromq-image-trigger') {
    const selectedPoolName = resolveLocalBufferPoolName()
    if (!selectedPoolName) throw new Error('LocalBufferBroker pools 未配置，不能创建 ZeroMQ 图片 TriggerSource')
    return {
      bind_endpoint: normalizedEndpoint,
      default_input_binding: selectedProtocolTemplate.value.defaultInputBinding,
      buffer_ttl_seconds: selectedProtocolTemplate.value.defaultReplyTimeoutSeconds,
      content_transport: 'local-buffer',
      pool_name: selectedPoolName,
    }
  }
  return { path: normalizedEndpoint, method: 'POST' }
}

function buildDefaultExecutionMetadata(): WorkflowJsonObject {
  const metadata: WorkflowJsonObject = {
    workflow_run_record_mode: workflowRunRecordMode.value,
    return_timing_metadata_enabled: returnDiagnostics.value === 'true',
    return_node_timings_enabled: returnDiagnostics.value === 'true',
  }
  if (selectedProtocolTemplate.value.templateId !== 'zeromq-image-trigger') return metadata
  return {
    ...metadata,
    trace_level: 'none',
    retain_trace_enabled: false,
    retain_node_records_enabled: false,
    retain_input_payload_enabled: false,
    retain_outputs_enabled: false,
  }
}

function buildMatchRule(): WorkflowJsonObject {
  if (selectedProtocolTemplate.value.templateId === 'webhook-json') return { method: 'POST' }
  return {}
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
        metadata: { inferred: row.inferred },
      }
    } else if (row.sourcePath.trim()) {
      mapping[row.bindingId] = {
        source: row.sourcePath.trim(),
        required: row.required,
        payload_type_id: row.payloadTypeId || null,
        metadata: { inferred: row.inferred },
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
  if ((trimmedValue.startsWith('{') && trimmedValue.endsWith('}')) || (trimmedValue.startsWith('[') && trimmedValue.endsWith(']'))) {
    try {
      const parsedValue = JSON.parse(trimmedValue) as unknown
      if (isRecord(parsedValue) || Array.isArray(parsedValue)) return parsedValue
    } catch {
      return value
    }
  }
  return value
}

function replaceTriggerSource(updatedSource: WorkflowTriggerSource): void {
  const sourceIndex = triggerSources.value.findIndex((source) => source.trigger_source_id === updatedSource.trigger_source_id)
  if (sourceIndex >= 0) triggerSources.value.splice(sourceIndex, 1, updatedSource)
  else triggerSources.value.unshift(updatedSource)
}

function sourceHealth(source: WorkflowTriggerSource): WorkflowTriggerSourceHealth | null {
  return healthByTriggerSourceId.value[source.trigger_source_id] ?? null
}

function sourceStateTone(source: WorkflowTriggerSource): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (source.last_error) return 'danger'
  if (source.observed_state === 'running') return 'success'
  if (source.observed_state === 'failed') return 'danger'
  if (source.desired_state === 'running' || source.enabled) return 'warning'
  return 'neutral'
}

function formatHealthSummary(value: unknown): string {
  if (!isRecord(value)) return ''
  const adapterRunning = value.adapter_running
  const requestCount = value.request_count
  const successCount = value.success_count
  const errorCount = value.error_count
  if (adapterRunning !== undefined || requestCount !== undefined || successCount !== undefined || errorCount !== undefined) {
    return `running=${String(adapterRunning ?? '-')} request=${String(requestCount ?? 0)} success=${String(successCount ?? 0)} error=${String(errorCount ?? 0)}`
  }
  return Object.keys(value).length > 0 ? JSON.stringify(value) : ''
}

function formatError(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function formatLastTriggered(value: string | null | undefined): string {
  return value ? formatSystemDateTime(value) : '未触发'
}

async function submitTriggerSource(): Promise<void> {
  const runtime = selectedRuntime.value
  if (!runtime) return
  saving.value = true
  errorMessage.value = null
  statusMessage.value = null
  try {
    const normalizedTriggerSourceId = triggerSourceId.value.trim()
    if (!normalizedTriggerSourceId) throw new Error('trigger_source_id 不能为空')
    if (submitMode.value === 'async' && workflowRunRecordMode.value === 'none') {
      throw new Error('async TriggerSource 不能使用 none 记录模式')
    }
    const triggerSource = await createWorkflowTriggerSource({
      projectId: selectedProjectId.value,
      triggerSourceId: normalizedTriggerSourceId,
      displayName: displayName.value.trim() || normalizedTriggerSourceId,
      triggerKind: selectedProtocolTemplate.value.triggerKind,
      workflowRuntimeId: runtime.workflow_runtime_id,
      submitMode: submitMode.value,
      enabled: enableAfterCreate.value === 'true',
      transportConfig: buildTransportConfig(),
      matchRule: buildMatchRule(),
      inputBindingMapping: buildInputBindingMapping(),
      resultMapping: {
        result_binding: resultBinding.value,
        result_mode: resultMode.value,
      },
      defaultExecutionMetadata: buildDefaultExecutionMetadata(),
      ackPolicy: ackPolicy.value,
      resultMode: resultMode.value,
      replyTimeoutSeconds: parseOptionalNumber(replyTimeoutSeconds.value),
      debounceWindowMs: parseOptionalNumber(debounceWindowMs.value),
      idempotencyKeyPath: idempotencyKeyPath.value.trim() || null,
      metadata: {
        source: 'web-ui-trigger-source-wizard',
        protocol_template: protocolTemplateId.value,
        application_id: runtime.application_id,
        default_input_binding: selectedProtocolTemplate.value.defaultInputBinding,
        local_buffer_pool_name: selectedProtocolTemplate.value.templateId === 'zeromq-image-trigger' ? resolveLocalBufferPoolName() : null,
        inferred_image_binding: inferredImageBinding.value?.binding_id ?? null,
        inferred_image_bindings: inferredImageBindings.value.map((binding) => binding.binding_id),
        inferred_request_binding: inferredRequestBinding.value?.binding_id ?? null,
        manual_mapping_available: true,
      },
    })
    await loadPage({ triggerSourceOffset: 0, preserveStatusMessage: true })
    statusMessage.value = `已创建 TriggerSource：${triggerSource.trigger_source_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建 TriggerSource 失败'
  } finally {
    saving.value = false
  }
}

async function setTriggerSourceEnabled(source: WorkflowTriggerSource, enabled: boolean): Promise<void> {
  busyTriggerSourceId.value = source.trigger_source_id
  errorMessage.value = null
  try {
    const updatedSource = enabled
      ? await enableWorkflowTriggerSource(source.trigger_source_id)
      : await disableWorkflowTriggerSource(source.trigger_source_id)
    replaceTriggerSource(updatedSource)
    statusMessage.value = `${enabled ? '已启用' : '已停用'} TriggerSource：${source.trigger_source_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '更新 TriggerSource 状态失败'
  } finally {
    busyTriggerSourceId.value = null
  }
}

async function refreshTriggerSourceHealth(source: WorkflowTriggerSource): Promise<void> {
  busyTriggerSourceId.value = source.trigger_source_id
  errorMessage.value = null
  try {
    const health = await getWorkflowTriggerSourceHealth(source.trigger_source_id)
    healthByTriggerSourceId.value = { ...healthByTriggerSourceId.value, [source.trigger_source_id]: health }
    source.health_summary = { ...health.health_summary } as WorkflowJsonObject
    source.last_error = health.last_error ?? null
    source.last_triggered_at = health.last_triggered_at ?? null
    statusMessage.value = `已更新 TriggerSource health：${source.trigger_source_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取 TriggerSource health 失败'
  } finally {
    busyTriggerSourceId.value = null
  }
}

async function deleteTriggerSource(source: WorkflowTriggerSource): Promise<void> {
  const confirmed = window.confirm(`删除 TriggerSource ${source.trigger_source_id}？`)
  if (!confirmed) return
  busyTriggerSourceId.value = source.trigger_source_id
  errorMessage.value = null
  try {
    await deleteWorkflowTriggerSource(source.trigger_source_id)
    const nextOffset = triggerSources.value.length === 1
      ? Math.max(0, triggerSourcePagination.value.offset - triggerSourcePagination.value.limit)
      : triggerSourcePagination.value.offset
    await loadPage({ triggerSourceOffset: nextOffset, preserveStatusMessage: true })
    const nextHealth = { ...healthByTriggerSourceId.value }
    delete nextHealth[source.trigger_source_id]
    healthByTriggerSourceId.value = nextHealth
    statusMessage.value = `已删除 TriggerSource：${source.trigger_source_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除 TriggerSource 失败'
  } finally {
    busyTriggerSourceId.value = null
  }
}

function loadPreviousTriggerSourcePage(): void {
  void loadPage({ triggerSourceOffset: Math.max(0, triggerSourcePagination.value.offset - triggerSourcePagination.value.limit) })
}

function loadNextTriggerSourcePage(): void {
  if (!triggerSourcePagination.value.hasMore) return
  void loadPage({
    triggerSourceOffset: triggerSourcePagination.value.nextOffset ?? triggerSourcePagination.value.offset + triggerSourcePagination.value.limit,
  })
}

function createPaginationState(): PaginationMeta {
  return {
    offset: 0,
    limit: 50,
    totalCount: 0,
    hasMore: false,
    nextOffset: null,
  }
}

watch(
  () => [selectedProjectId.value, route.query.runtime_id, route.query.application_id] as const,
  (currentValue, previousValue) => {
    const [projectId] = currentValue
    const previousProjectId = previousValue?.[0]
    void loadPage({ resetTriggerSourcePage: projectId !== previousProjectId })
  },
  { immediate: true },
)
</script>

<style scoped>
.trigger-source-page__pagination {
  margin-top: 16px;
}
</style>
