<template>
  <section class="page-stack">
    <PageHeader
      :title="application?.display_name || applicationId"
      :description="application?.description || t('workflowEditor.appDetail.description')"
    >
      <template #actions>
        <Button variant="secondary" @click="openAppList">
          <ArrowLeft :size="16" />
          {{ t('workflowEditor.appDetail.actions.backToList') }}
        </Button>
        <Button variant="secondary" @click="openGraphEditor">
          <Workflow :size="16" />
          {{ t('workflowEditor.actions.openGraphEditor') }}
        </Button>
        <Button variant="secondary" :disabled="loading" :loading="loading" @click="loadPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <InlineError :message="errorMessage" />
    <p v-if="statusMessage" class="result-note">{{ statusMessage }}</p>

    <EmptyState
      v-if="!loading && !workflowApp"
      :title="t('workflowEditor.appDetail.notFoundTitle')"
      :description="t('workflowEditor.appDetail.notFoundDescription')"
    />

    <template v-else-if="workflowApp">
      <section class="resource-section">
        <div class="section-heading">
          <div>
            <h2>{{ t('workflowEditor.appDetail.summaryTitle') }}</h2>
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
            <h2>App Contract</h2>
          </div>
          <StatusBadge tone="neutral">{{ bindings.length }} bindings</StatusBadge>
        </div>
        <div class="resource-table">
          <table>
            <thead>
              <tr>
                <th>{{ t('workflowEditor.appDetail.fields.direction') }}</th>
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
                <td>{{ binding.required ? t('workflowEditor.editor.required') : t('workflowEditor.editor.optional') }}</td>
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
            <h2>{{ t('workflowEditor.appDetail.runtimeTitle') }}</h2>
          </div>
          <div class="table-actions table-actions--wrap">
            <Button v-if="canWriteWorkflows" variant="primary" :disabled="runtimeActionBusy" @click="createRuntime">
              <Plus :size="16" />
              {{ t('workflowEditor.appDetail.actions.createRuntime') }}
            </Button>
            <Button
              v-if="canWriteWorkflows"
              variant="secondary"
              :disabled="!selectedRuntime || loading"
              :title="selectedRuntime ? t('workflowEditor.appDetail.actions.addTriggerForCurrent') : t('workflowEditor.appDetail.actions.selectRuntimeFirst')"
              @click="openSelectedRuntimeTriggerSource"
            >
              <PlugZap :size="16" />
              {{ t('workflowEditor.appDetail.actions.addTriggerSource') }}
            </Button>
          </div>
        </div>
        <div v-if="canWriteWorkflows" class="form-grid workflow-runtime-defaults">
          <label class="field">
            <span>{{ t('workflowEditor.appDetail.fields.workflowRunRecord') }}</span>
            <SelectField :model-value="runtimeWorkflowRunRecordMode" :options="workflowRunRecordModeOptions" @update:model-value="setRuntimeWorkflowRunRecordMode" />
          </label>
          <label class="field">
            <span>{{ t('workflowEditor.appDetail.fields.returnDiagnostics') }}</span>
            <SelectField :model-value="runtimeReturnDiagnostics" :options="returnDiagnosticsOptions" @update:model-value="setRuntimeReturnDiagnostics" />
          </label>
        </div>
        <EmptyState
          v-if="runtimes.length === 0"
          :title="t('workflowEditor.appDetail.emptyRuntimeTitle')"
          :description="t('workflowEditor.appDetail.emptyRuntimeDescription')"
        />
        <div v-else class="resource-table">
          <table>
            <thead>
              <tr>
                <th>runtime</th>
                <th>state</th>
                <th>health / error</th>
                <th>updated</th>
                <th>{{ t('workflowEditor.columns.actions') }}</th>
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
                    <Button
                      size="sm"
                      variant="secondary"
                      :disabled="!canSelectRuntime(runtime)"
                      :title="canSelectRuntime(runtime) ? t('workflowEditor.appDetail.actions.setCurrentHint') : t('workflowEditor.appDetail.actions.currentHint')"
                      @click="selectRuntime(runtime.workflow_runtime_id)"
                    >
                      <CheckCircle2 v-if="runtime.workflow_runtime_id === selectedRuntimeId" :size="14" />
                      <MousePointer2 v-else :size="14" />
                      {{ runtime.workflow_runtime_id === selectedRuntimeId ? t('workflowEditor.appDetail.actions.current') : t('workflowEditor.appDetail.actions.setCurrent') }}
                    </Button>
                    <Button
                      v-if="canWriteWorkflows"
                      size="sm"
                      variant="secondary"
                      :disabled="!canStartRuntime(runtime)"
                      :title="startRuntimeTitle(runtime)"
                      @click="controlRuntime(runtime, 'start')"
                    >
                      <Play :size="14" />
                      {{ t('workflowEditor.appDetail.actions.start') }}
                    </Button>
                    <Button
                      v-if="canWriteWorkflows"
                      size="sm"
                      variant="secondary"
                      :disabled="!canStopRuntime(runtime)"
                      :title="stopRuntimeTitle(runtime)"
                      @click="controlRuntime(runtime, 'stop')"
                    >
                      <Square :size="14" />
                      {{ t('workflowEditor.appDetail.actions.stop') }}
                    </Button>
                    <Button
                      v-if="canWriteWorkflows"
                      size="sm"
                      variant="secondary"
                      :disabled="!canRestartRuntime(runtime)"
                      :title="restartRuntimeTitle(runtime)"
                      @click="controlRuntime(runtime, 'restart')"
                    >
                      <RotateCw :size="14" />
                      {{ t('workflowEditor.appDetail.actions.restart') }}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      :disabled="!canRefreshRuntimeHealth(runtime)"
                      :title="t('workflowEditor.appDetail.actions.refreshHealthHint')"
                      @click="refreshRuntimeHealth(runtime)"
                    >
                      <Activity :size="14" />
                      {{ t('workflowEditor.appDetail.actions.healthCheck') }}
                    </Button>
                    <Button
                      v-if="canWriteWorkflows"
                      size="sm"
                      variant="secondary"
                      :disabled="!canAddTriggerSource(runtime)"
                      :title="addTriggerTitle(runtime)"
                      @click="openTriggerSourceCreate(runtime.workflow_runtime_id)"
                    >
                      <PlugZap :size="14" />
                      {{ t('workflowEditor.appDetail.actions.addTrigger') }}
                    </Button>
                    <Button
                      v-if="canWriteWorkflows"
                      size="sm"
                      variant="danger"
                      :disabled="!canDeleteRuntime(runtime)"
                      :loading="busyRuntimeId === runtime.workflow_runtime_id && pendingDeleteRuntime?.workflow_runtime_id === runtime.workflow_runtime_id"
                      :title="deleteRuntimeTitle(runtime)"
                      @click="requestDeleteRuntime(runtime)"
                    >
                      <Trash2 :size="14" />
                      {{ t('workflowEditor.appDetail.actions.delete') }}
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
            <h2>{{ t('workflowEditor.appDetail.httpTitle') }}</h2>
          </div>
          <StatusBadge :tone="selectedRuntime ? 'info' : 'neutral'">{{ selectedRuntime?.workflow_runtime_id ?? 'select-runtime' }}</StatusBadge>
        </div>
        <div v-if="selectedRuntime" class="form-grid">
          <div class="field field--wide">
            <span>{{ t('workflowEditor.appDetail.fields.endpoint') }}</span>
            <pre class="json-view">POST /api/v1/workflows/app-runtimes/{{ selectedRuntime.workflow_runtime_id }}/runs
POST /api/v1/workflows/app-runtimes/{{ selectedRuntime.workflow_runtime_id }}/invoke
GET /api/v1/workflows/runs/{workflow_run_id}
GET /api/v1/workflows/runs/{workflow_run_id}?response_mode=run</pre>
          </div>
          <label class="field field--wide">
            <span>input_bindings JSON</span>
            <textarea v-model="runtimePayloadText" rows="8" spellcheck="false" />
          </label>
          <div class="table-actions table-actions--wrap field--wide">
            <Button variant="secondary" @click="resetSamplePayload">
              <Copy :size="16" />
              {{ t('workflowEditor.appDetail.actions.generateSample') }}
            </Button>
            <Button v-if="canWriteWorkflows" variant="primary" :disabled="runtimeActionBusy" @click="submitRun('async')">
              <Send :size="16" />
              {{ t('workflowEditor.appDetail.actions.createAsyncRun') }}
            </Button>
            <Button v-if="canWriteWorkflows" variant="secondary" :disabled="runtimeActionBusy" @click="submitRun('sync')">
              <Zap :size="16" />
              {{ t('workflowEditor.appDetail.actions.syncInvoke') }}
            </Button>
          </div>
        </div>
        <EmptyState
          v-else
          :title="t('workflowEditor.appDetail.noRuntimeSelectedTitle')"
          :description="t('workflowEditor.appDetail.noRuntimeSelectedDescription')"
        />
      </section>

      <section class="resource-section">
        <div class="section-heading">
          <div>
            <h2>{{ t('workflowEditor.appDetail.lastReceiptTitle') }}</h2>
          </div>
          <div class="table-actions table-actions--wrap">
            <Button variant="secondary" :disabled="fetchingLastRun || !lastRun" @click="refreshLastRun">
              <RefreshCw :size="16" />
              {{ t('workflowEditor.appDetail.actions.fetchAsyncResult') }}
            </Button>
            <StatusBadge :tone="lastRun ? runTone(lastRun.state) : 'neutral'">{{ lastRun?.state ?? 'none' }}</StatusBadge>
          </div>
        </div>
        <EmptyState
          v-if="!lastRun"
          :title="t('workflowEditor.appDetail.emptyRunTitle')"
          :description="t('workflowEditor.appDetail.emptyRunDescription')"
        />
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
        <WorkflowRuntimeBodyViewer
          v-if="lastRunResponseBody"
          :project-id="selectedProjectId"
          :status-code="lastRunResponseStatusCode"
          :body="lastRunResponseBody"
        />
        <p v-else-if="lastRun" class="result-note">{{ t('workflowEditor.appDetail.noRenderableBody') }}</p>
        <details v-if="lastRun" class="result-details">
          <summary>{{ t('workflowEditor.appDetail.viewReceiptJson') }}</summary>
          <pre class="json-view">{{ lastRunReceiptText }}</pre>
        </details>
      </section>

      <section class="resource-section">
        <div class="section-heading">
          <div>
            <h2>{{ t('workflowEditor.appDetail.triggerSourceTitle') }}</h2>
          </div>
          <Button
            v-if="canWriteWorkflows"
            variant="primary"
            :disabled="!selectedRuntime || loading"
            :title="selectedRuntime ? t('workflowEditor.appDetail.actions.addTriggerForCurrent') : t('workflowEditor.appDetail.actions.selectRuntimeFirst')"
            @click="openSelectedRuntimeTriggerSource"
          >
            <PlugZap :size="16" />
            {{ t('workflowEditor.appDetail.actions.addTriggerSource') }}
          </Button>
        </div>
        <EmptyState
          v-if="relatedTriggerSources.length === 0"
          :title="t('workflowEditor.appDetail.emptyTriggerTitle')"
          :description="t('workflowEditor.appDetail.emptyTriggerDescription')"
        />
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

    <ConfirmDialog
      v-if="pendingDeleteRuntime"
      :title="t('common.confirmDelete')"
      :message="t('workflowEditor.appDetail.messages.confirmDeleteRuntime', { runtimeId: pendingDeleteRuntime.workflow_runtime_id })"
      :confirm-label="t('workflowEditor.appDetail.actions.delete')"
      :cancel-label="t('common.cancel')"
      :busy="busyRuntimeId === pendingDeleteRuntime.workflow_runtime_id"
      @cancel="pendingDeleteRuntime = null"
      @confirm="deleteRuntime"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
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
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import {
  listWorkflowTriggerSources,
  refreshWorkflowTriggerSourceStatuses,
  type WorkflowTriggerSource,
} from '@/modules/integrations/services/trigger-source.service'
import WorkflowRuntimeBodyViewer from '../components/WorkflowRuntimeBodyViewer.vue'
import { getWorkflowApp, type WorkflowAppDocument } from '../services/workflow-app.service'
import {
  createWorkflowAppRuntime,
  createWorkflowRun,
  deleteWorkflowAppRuntime,
  getWorkflowAppRuntimeHealth,
  getWorkflowRun,
  invokeWorkflowAppRuntime,
  restartWorkflowAppRuntime,
  refreshWorkflowAppRuntimeStatuses,
  startWorkflowAppRuntime,
  stopWorkflowAppRuntime,
} from '../services/workflow-runtime.service'
import type { FlowApplicationBinding, WorkflowAppRuntime, WorkflowJsonObject, WorkflowRun } from '../types'

type RuntimeControlAction = 'start' | 'stop' | 'restart'
type RunSubmitMode = 'async' | 'sync'
type WorkflowRunRecordMode = 'full' | 'minimal' | 'none'
type SelectValue = string | number | boolean | null

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()

const workflowRunRecordModeOptions = computed<SelectOption[]>(() => [
  { label: 'full', value: 'full', description: t('workflowEditor.appDetail.options.recordFull') },
  { label: 'minimal', value: 'minimal', description: t('workflowEditor.appDetail.options.recordMinimal') },
  { label: 'none', value: 'none', description: t('workflowEditor.appDetail.options.recordNone') },
])

const returnDiagnosticsOptions = computed<SelectOption[]>(() => [
  { label: t('workflowEditor.appDetail.options.no'), value: 'false', description: t('workflowEditor.appDetail.options.diagnosticsOff') },
  { label: t('workflowEditor.appDetail.options.yes'), value: 'true', description: t('workflowEditor.appDetail.options.diagnosticsOn') },
])

const loading = ref(false)
const errorMessage = ref<string | null>(null)
const statusMessage = ref<string | null>(null)
const workflowApp = ref<WorkflowAppDocument | null>(null)
const triggerSources = ref<WorkflowTriggerSource[]>([])
const selectedRuntimeId = ref('')
const busyRuntimeId = ref<string | null>(null)
const pendingDeleteRuntime = ref<WorkflowAppRuntime | null>(null)
const runtimePayloadText = ref('{}')
const lastRun = ref<WorkflowRun | null>(null)
const fetchingLastRun = ref(false)
const runtimeWorkflowRunRecordMode = ref<WorkflowRunRecordMode>('full')
const runtimeReturnDiagnostics = ref('false')

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
const lastRunResponsePayload = computed<Record<string, unknown> | null>(() => {
  const outputs = lastRun.value?.outputs
  if (!isRecord(outputs)) return null
  const responsePayload = outputs.http_response
  return isRecord(responsePayload) ? responsePayload : null
})
const lastRunResponseBody = computed<WorkflowJsonObject | null>(() => {
  const responsePayload = lastRunResponsePayload.value
  if (!responsePayload) return null
  const body = responsePayload.body
  return isRecord(body) ? body : null
})
const lastRunResponseStatusCode = computed<number | null>(() => {
  const responsePayload = lastRunResponsePayload.value
  if (!responsePayload) return null
  const rawStatusCode = responsePayload.status_code
  if (typeof rawStatusCode === 'number' && Number.isFinite(rawStatusCode)) return rawStatusCode
  if (typeof rawStatusCode === 'string' && rawStatusCode.trim()) {
    const parsedValue = Number(rawStatusCode)
    return Number.isFinite(parsedValue) ? parsedValue : null
  }
  return null
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
  if (payloadTypeId === 'image-ref.v1') {
    return {
      transport_kind: 'storage',
      object_key: 'workflows/inputs/sample.png',
      media_type: 'image/png',
    }
  }
  if (payloadTypeId === 'image-base64.v1') {
    return {
      image_base64: '<base64>',
      media_type: 'image/png',
    }
  }
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
    const shouldInclude = binding.required
      || binding.binding_id === 'request_image_base64'
      || binding.binding_id === 'request_image_ref'
      || binding.binding_id.includes('deployment_request')
    if (shouldInclude) sampleInputBindings[binding.binding_id] = sampleValueForPayloadType(payloadTypeId, binding.binding_id)
  }
  return sampleInputBindings
}

function resetSamplePayload(): void {
  runtimePayloadText.value = JSON.stringify(buildSampleInputBindings(), null, 2)
}

function parseInputBindings(): WorkflowJsonObject {
  const parsedValue = JSON.parse(runtimePayloadText.value || '{}') as unknown
  if (!isRecord(parsedValue)) throw new Error(t('workflowEditor.appDetail.messages.inputBindingsObject'))
  const candidate = parsedValue.input_bindings
  if (candidate !== undefined) {
    if (!isRecord(candidate)) throw new Error(t('workflowEditor.appDetail.messages.inputBindingsObject'))
    validateInputBindingPayloads(candidate)
    return candidate
  }
  validateInputBindingPayloads(parsedValue)
  return parsedValue
}

function validateInputBindingPayloads(inputBindingPayloads: Record<string, unknown>): void {
  for (const binding of inputBindings.value) {
    if (!Object.prototype.hasOwnProperty.call(inputBindingPayloads, binding.binding_id)) continue
    const payload = inputBindingPayloads[binding.binding_id]
    if (payload === null || payload === undefined) {
      if (binding.required) throw new Error(t('workflowEditor.appDetail.messages.requiredInputNull', { bindingId: binding.binding_id }))
      continue
    }
    const payloadTypeId = getBindingPayloadTypeId(binding)
    if (payloadTypeId === 'image-base64.v1') validateImageBase64BindingPayload(binding.binding_id, payload)
    else if (payloadTypeId === 'image-ref.v1') validateImageRefBindingPayload(binding.binding_id, payload)
  }
}

function validateImageBase64BindingPayload(bindingId: string, payload: unknown): void {
  if (!isRecord(payload)) {
    throw new Error(t('workflowEditor.appDetail.messages.imageBase64Object', { bindingId }))
  }
  const imageBase64 = payload.image_base64
  if (typeof imageBase64 !== 'string' || !imageBase64.trim()) {
    throw new Error(t('workflowEditor.appDetail.messages.imageBase64Missing', { bindingId }))
  }
}

function validateImageRefBindingPayload(bindingId: string, payload: unknown): void {
  if (!isRecord(payload)) {
    throw new Error(t('workflowEditor.appDetail.messages.imageRefObject', { bindingId }))
  }
  const transportKind = payload.transport_kind
  if (transportKind === undefined || transportKind === null || transportKind === '') {
    const objectKey = payload.object_key
    if (typeof objectKey !== 'string' || !objectKey.trim()) {
      throw new Error(t('workflowEditor.appDetail.messages.objectKeyMissing', { bindingId }))
    }
    return
  }
  if (transportKind === 'storage') {
    const objectKey = payload.object_key
    if (typeof objectKey !== 'string' || !objectKey.trim()) {
      throw new Error(t('workflowEditor.appDetail.messages.storageObjectKeyMissing', { bindingId }))
    }
  } else if (transportKind === 'memory') {
    const imageHandle = payload.image_handle
    if (typeof imageHandle !== 'string' || !imageHandle.trim()) {
      throw new Error(t('workflowEditor.appDetail.messages.memoryHandleMissing', { bindingId }))
    }
  } else if (transportKind === 'buffer') {
    const bufferRef = payload.buffer_ref
    if (typeof bufferRef !== 'string' || !bufferRef.trim()) {
      throw new Error(t('workflowEditor.appDetail.messages.bufferRefMissing', { bindingId }))
    }
  } else if (transportKind === 'frame') {
    const frameRef = payload.frame_ref
    if (typeof frameRef !== 'string' || !frameRef.trim()) {
      throw new Error(t('workflowEditor.appDetail.messages.frameRefMissing', { bindingId }))
    }
  }
}

function selectRuntime(runtimeId: string): void {
  const runtime = runtimes.value.find((item) => item.workflow_runtime_id === runtimeId)
  if (!runtime || !canSelectRuntime(runtime)) return
  selectedRuntimeId.value = runtimeId
}

function isRuntimeStarting(runtime: WorkflowAppRuntime): boolean {
  return runtime.observed_state === 'starting'
}

function isRuntimeStopping(runtime: WorkflowAppRuntime): boolean {
  return runtime.observed_state === 'stopping'
}

function isRuntimeRunning(runtime: WorkflowAppRuntime): boolean {
  return runtime.observed_state === 'running'
}

function isRuntimeBusy(): boolean {
  return loading.value || busyRuntimeId.value !== null
}

function runtimeTriggerSourceCount(runtime: WorkflowAppRuntime): number {
  return triggerSources.value.filter((source) => source.workflow_runtime_id === runtime.workflow_runtime_id).length
}

function canSelectRuntime(runtime: WorkflowAppRuntime): boolean {
  return !loading.value && runtime.workflow_runtime_id !== selectedRuntimeId.value
}

function canStartRuntime(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy()) return false
  return !isRuntimeRunning(runtime) && !isRuntimeStarting(runtime) && !isRuntimeStopping(runtime)
}

function canStopRuntime(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy()) return false
  return isRuntimeRunning(runtime) || runtime.observed_state === 'starting'
}

function canRestartRuntime(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy()) return false
  return isRuntimeRunning(runtime)
}

function canRefreshRuntimeHealth(_runtime: WorkflowAppRuntime): boolean {
  return !isRuntimeBusy()
}

function canAddTriggerSource(runtime: WorkflowAppRuntime): boolean {
  return canWriteWorkflows.value && !loading.value && Boolean(runtime.workflow_runtime_id)
}

function canDeleteRuntime(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy()) return false
  if (isRuntimeRunning(runtime) || runtime.observed_state === 'starting' || runtime.observed_state === 'stopping') return false
  return runtimeTriggerSourceCount(runtime) === 0
}

function startRuntimeTitle(runtime: WorkflowAppRuntime): string {
  if (isRuntimeBusy()) return t('workflowEditor.appDetail.hints.runtimeBusy')
  if (isRuntimeRunning(runtime)) return t('workflowEditor.appDetail.hints.runtimeRunning')
  if (isRuntimeStarting(runtime)) return t('workflowEditor.appDetail.hints.runtimeStarting')
  if (isRuntimeStopping(runtime)) return t('workflowEditor.appDetail.hints.runtimeStoppingBeforeStart')
  return t('workflowEditor.appDetail.hints.startRuntime')
}

function stopRuntimeTitle(runtime: WorkflowAppRuntime): string {
  if (isRuntimeBusy()) return t('workflowEditor.appDetail.hints.runtimeBusy')
  if (runtime.observed_state === 'stopping') return t('workflowEditor.appDetail.hints.runtimeStopping')
  if (!canStopRuntime(runtime)) return t('workflowEditor.appDetail.hints.runtimeNotRunning')
  return t('workflowEditor.appDetail.hints.stopRuntime')
}

function restartRuntimeTitle(runtime: WorkflowAppRuntime): string {
  if (isRuntimeBusy()) return t('workflowEditor.appDetail.hints.runtimeBusy')
  if (!isRuntimeRunning(runtime)) return t('workflowEditor.appDetail.hints.restartRunningOnly')
  return t('workflowEditor.appDetail.hints.restartRuntime')
}

function addTriggerTitle(runtime: WorkflowAppRuntime): string {
  if (!canWriteWorkflows.value) return t('workflowEditor.appDetail.hints.noTriggerPermission')
  if (!runtime.workflow_runtime_id) return t('workflowEditor.appDetail.hints.runtimeIdMissing')
  return isRuntimeRunning(runtime)
    ? t('workflowEditor.appDetail.hints.addTrigger')
    : t('workflowEditor.appDetail.hints.addTriggerAfterStart')
}

function deleteRuntimeTitle(runtime: WorkflowAppRuntime): string {
  const triggerSourceCount = runtimeTriggerSourceCount(runtime)
  if (isRuntimeBusy()) return t('workflowEditor.appDetail.hints.runtimeBusy')
  if (isRuntimeRunning(runtime) || runtime.observed_state === 'starting' || runtime.observed_state === 'stopping') {
    return t('workflowEditor.appDetail.hints.stopBeforeDelete')
  }
  if (triggerSourceCount > 0) return t('workflowEditor.appDetail.hints.deleteTriggersFirst', { count: triggerSourceCount })
  return t('workflowEditor.appDetail.hints.deleteRuntime')
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

function openAppList(): void {
  void router.push('/workflows/apps')
}

function openGraphEditor(): void {
  void router.push(graphEditorPath.value)
}

function openTriggerSourceCreate(runtimeId: string): void {
  const runtime = runtimes.value.find((item) => item.workflow_runtime_id === runtimeId)
  if (!runtime || !canAddTriggerSource(runtime)) return
  void router.push(triggerSourceCreatePath(runtimeId))
}

function openSelectedRuntimeTriggerSource(): void {
  const runtime = selectedRuntime.value
  if (!runtime || !canAddTriggerSource(runtime)) return
  void router.push(triggerSourceCreatePath(runtime.workflow_runtime_id))
}

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function setRuntimeWorkflowRunRecordMode(value: SelectValue): void {
  const nextValue = selectValueToString(value)
  runtimeWorkflowRunRecordMode.value = nextValue === 'minimal' || nextValue === 'none' ? nextValue : 'full'
}

function setRuntimeReturnDiagnostics(value: SelectValue): void {
  runtimeReturnDiagnostics.value = selectValueToString(value) === 'true' ? 'true' : 'false'
}

function buildRuntimeDefaultExecutionMetadata(): WorkflowJsonObject {
  return {
    workflow_run_record_mode: runtimeWorkflowRunRecordMode.value,
    return_timing_metadata_enabled: runtimeReturnDiagnostics.value === 'true',
    return_node_timings_enabled: runtimeReturnDiagnostics.value === 'true',
    trace_level: 'none',
    retain_trace_enabled: false,
    retain_node_records_enabled: false,
  }
}

function readRuntimeWorkflowRunRecordMode(runtime: WorkflowAppRuntime): WorkflowRunRecordMode {
  const defaultExecutionMetadata = runtime.metadata.default_execution_metadata
  const recordMode = typeof defaultExecutionMetadata === 'object' && defaultExecutionMetadata !== null && !Array.isArray(defaultExecutionMetadata)
    ? (defaultExecutionMetadata as WorkflowJsonObject).workflow_run_record_mode
    : null
  return recordMode === 'minimal' || recordMode === 'none' ? recordMode : 'full'
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
    const [runtimeStatusResult, triggerStatusResult] = await Promise.all([
      refreshWorkflowAppRuntimeStatuses(appDocument.runtimes),
      refreshWorkflowTriggerSourceStatuses(triggerSourceResult.items),
    ])
    appDocument.runtimes = runtimeStatusResult.items
    appDocument.primaryRuntime = runtimeStatusResult.items.find((runtime) => runtime.observed_state === 'running')
      ?? runtimeStatusResult.items[0]
      ?? null
    workflowApp.value = appDocument
    triggerSources.value = triggerStatusResult.items
    const queryRuntimeId = typeof route.query.runtime_id === 'string' ? route.query.runtime_id : ''
    selectedRuntimeId.value = appDocument.runtimes.some((runtime) => runtime.workflow_runtime_id === queryRuntimeId)
      ? queryRuntimeId
      : appDocument.primaryRuntime?.workflow_runtime_id ?? appDocument.runtimes[0]?.workflow_runtime_id ?? ''
    resetSamplePayload()
    const failedIds = [...runtimeStatusResult.failedRuntimeIds, ...triggerStatusResult.failedTriggerSourceIds]
    if (failedIds.length > 0) {
      errorMessage.value = t('workflowEditor.appDetail.messages.partialRefreshFailed', { runtimeIds: failedIds.join(', ') })
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.appDetail.messages.loadFailed')
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
      metadata: {
        source: 'web-ui-app-detail',
        default_execution_metadata: buildRuntimeDefaultExecutionMetadata(),
      },
    })
    replaceRuntime(runtime)
    selectedRuntimeId.value = runtime.workflow_runtime_id
    statusMessage.value = t('workflowEditor.appDetail.messages.runtimeCreated', { runtimeId: runtime.workflow_runtime_id })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.appDetail.messages.createRuntimeFailed')
  } finally {
    busyRuntimeId.value = null
  }
}

async function controlRuntime(runtime: WorkflowAppRuntime, action: RuntimeControlAction): Promise<void> {
  if (!canWriteWorkflows.value) return
  if (action === 'start' && !canStartRuntime(runtime)) return
  if (action === 'stop' && !canStopRuntime(runtime)) return
  if (action === 'restart' && !canRestartRuntime(runtime)) return
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
    statusMessage.value = t('workflowEditor.appDetail.messages.runtimeActionSubmitted', {
      action,
      runtimeId: updatedRuntime.workflow_runtime_id,
    })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.appDetail.messages.runtimeActionFailed', { action })
  } finally {
    busyRuntimeId.value = null
  }
}

async function refreshRuntimeHealth(runtime: WorkflowAppRuntime): Promise<void> {
  if (!canRefreshRuntimeHealth(runtime)) return
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    const updatedRuntime = await getWorkflowAppRuntimeHealth(runtime.workflow_runtime_id)
    replaceRuntime(updatedRuntime)
    statusMessage.value = t('workflowEditor.appDetail.messages.healthUpdated', { runtimeId: updatedRuntime.workflow_runtime_id })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.appDetail.messages.healthFailed')
  } finally {
    busyRuntimeId.value = null
  }
}

function requestDeleteRuntime(runtime: WorkflowAppRuntime): void {
  if (!workflowApp.value || !canDeleteRuntime(runtime)) return
  pendingDeleteRuntime.value = runtime
}

async function deleteRuntime(): Promise<void> {
  const runtime = pendingDeleteRuntime.value
  if (!runtime) return
  if (!workflowApp.value || !canDeleteRuntime(runtime)) return
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    await deleteWorkflowAppRuntime(runtime.workflow_runtime_id)
    workflowApp.value.runtimes = workflowApp.value.runtimes.filter((item) => item.workflow_runtime_id !== runtime.workflow_runtime_id)
    workflowApp.value.primaryRuntime = workflowApp.value.runtimes.find((item) => item.observed_state === 'running') ?? workflowApp.value.runtimes[0] ?? null
    selectedRuntimeId.value = workflowApp.value.primaryRuntime?.workflow_runtime_id ?? workflowApp.value.runtimes[0]?.workflow_runtime_id ?? ''
    statusMessage.value = t('workflowEditor.appDetail.messages.runtimeDeleted', { runtimeId: runtime.workflow_runtime_id })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.appDetail.messages.deleteRuntimeFailed')
  } finally {
    busyRuntimeId.value = null
    pendingDeleteRuntime.value = null
  }
}

async function submitRun(mode: RunSubmitMode): Promise<void> {
  const runtime = selectedRuntime.value
  if (!runtime || !canWriteWorkflows.value) return
  if (mode === 'async' && readRuntimeWorkflowRunRecordMode(runtime) === 'none') {
    errorMessage.value = t('workflowEditor.appDetail.messages.asyncRunRecordNone')
    return
  }
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    const inputBindings = parseInputBindings()
    const run = mode === 'async'
      ? await createWorkflowRun(runtime.workflow_runtime_id, { inputBindings, executionMetadata: { source: 'web-ui-app-detail' } })
      : await invokeWorkflowAppRuntime(runtime.workflow_runtime_id, { inputBindings, executionMetadata: { source: 'web-ui-app-detail' } })
    lastRun.value = run
    statusMessage.value = t('workflowEditor.appDetail.messages.runCreated', { runId: run.workflow_run_id })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.appDetail.messages.invokeFailed')
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
    statusMessage.value = t('workflowEditor.appDetail.messages.runFetched', { runId: run.workflow_run_id })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.appDetail.messages.fetchRunFailed')
  } finally {
    fetchingLastRun.value = false
  }
}

onMounted(loadPage)
</script>

<style scoped>
.result-details {
  margin-top: 16px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  padding: 12px 14px;
  background: var(--am-surface-soft);
}

.result-details summary {
  cursor: pointer;
  font-weight: 600;
}

.result-details .json-view {
  margin-top: 12px;
}
</style>
