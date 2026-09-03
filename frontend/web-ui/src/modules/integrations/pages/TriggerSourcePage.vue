<template>
  <section class="page-stack">
    <PageHeader :title="t('triggerSources.title')">
      <template #actions>
        <ButtonLink v-if="selectedRuntime" :to="appDetailPath">
          <Workflow :size="16" />
          {{ t('triggerSources.actions.backToApp') }}
        </ButtonLink>
        <Button variant="secondary" :disabled="loading" :loading="loading" @click="loadPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <InlineError :message="errorMessage" />
    <InlineMessage v-if="statusMessage" tone="success" :message="statusMessage" />

    <form class="form-panel" @submit.prevent="submitTriggerSource">
      <div class="section-heading">
        <div>
          <h2>{{ t('triggerSources.createTitle') }}</h2>
        </div>
        <Button variant="primary" type="submit" :disabled="saving || !selectedRuntime" :loading="saving">
          <Save :size="16" />
          {{ t('triggerSources.actions.create') }}
        </Button>
      </div>

      <EmptyState
        v-if="runtimes.length === 0"
        class="trigger-source-runtime-empty"
        :title="t('triggerSources.emptyRuntimeTitle')"
        :description="t('triggerSources.emptyRuntimeDescription')"
      />

      <template v-else>
        <div class="form-grid">
          <label class="field field--wide">
            <span>{{ t('triggerSources.fields.runtimeInstance') }}</span>
            <SelectField :model-value="selectedRuntimeId" :options="runtimeOptions" :placeholder="t('triggerSources.placeholders.selectRuntime')" @update:model-value="selectRuntime" />
          </label>
          <label class="field">
            <span>{{ t('triggerSources.fields.protocolTemplate') }}</span>
            <SelectField :model-value="protocolTemplateId" :options="protocolTemplateOptions" @update:model-value="selectProtocolTemplate" />
          </label>
          <label class="field">
            <span>{{ t('triggerSources.fields.enableAfterCreate') }}</span>
            <SelectField :model-value="enableAfterCreate" :options="enableAfterCreateOptions" @update:model-value="setEnableAfterCreate" />
          </label>
        </div>

        <div v-if="selectedRuntime" class="summary-grid">
          <div>
            <span>{{ t('triggerSources.fields.runtime') }}</span>
            <strong>{{ selectedRuntime.workflow_runtime_id }}</strong>
          </div>
          <div>
            <span>{{ t('triggerSources.fields.application') }}</span>
            <strong>{{ selectedRuntime.application_id }}</strong>
          </div>
          <div>
            <span>{{ t('triggerSources.fields.state') }}</span>
            <strong>{{ selectedRuntime.desired_state }} / {{ selectedRuntime.observed_state }}</strong>
          </div>
          <div>
            <span>{{ t('triggerSources.fields.bindings') }}</span>
            <strong>{{ appInputBindings.length }} {{ t('triggerSources.values.input') }} / {{ appOutputBindings.length }} {{ t('triggerSources.values.output') }}</strong>
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
          <label v-if="selectedProtocolTemplate.requiresEndpoint" class="field">
            <span>{{ selectedProtocolTemplate.endpointLabel }}</span>
            <input v-model="endpoint" />
          </label>
          <label v-if="isDirectoryWatch" class="field field--wide">
            <span>directory_path</span>
            <input v-model="directoryPath" placeholder="W:\\results" />
          </label>
          <label v-if="isDirectoryWatch" class="field">
            <span>recursive</span>
            <SelectField :model-value="directoryRecursive" :options="booleanOptions" @update:model-value="directoryRecursive = selectValueToBooleanString($event)" />
          </label>
          <label v-if="isDirectoryWatch" class="field">
            <span>include_hidden</span>
            <SelectField :model-value="directoryIncludeHidden" :options="booleanOptions" @update:model-value="directoryIncludeHidden = selectValueToBooleanString($event)" />
          </label>
          <label v-if="isDirectoryWatch" class="field">
            <span>glob_pattern</span>
            <input v-model="directoryGlobPattern" placeholder="*" />
          </label>
          <label v-if="isDirectoryWatch" class="field">
            <span>extensions</span>
            <input v-model="directoryExtensions" placeholder=".jpg, .png, .json" />
          </label>
          <label v-if="isDirectoryWatch" class="field field--wide">
            <span>event_types</span>
            <MultiSelect :model-value="directoryEventTypes" :options="directoryEventTypeOptions" @update:model-value="directoryEventTypes = $event" />
          </label>
          <label class="field">
            <span>result_bindings</span>
            <MultiSelect
              :model-value="resultBindings"
              :options="resultBindingOptions"
              @update:model-value="setResultBindings"
            />
          </label>
        </div>

        <div v-if="!isDirectoryWatch" class="trigger-source-inference">
          <div class="section-heading">
            <div>
              <h2>{{ t('triggerSources.inferenceTitle') }}</h2>
            </div>
            <StatusBadge tone="info">{{ protocolTemplateDisplayName(selectedProtocolTemplate) }}</StatusBadge>
          </div>
          <div class="summary-grid">
            <div>
              <span>{{ t('triggerSources.fields.imageInput') }}</span>
              <strong>{{ inferredImageBindingText }}</strong>
            </div>
            <div>
              <span>{{ t('triggerSources.fields.requestParameters') }}</span>
              <strong>{{ inferredRequestBinding?.binding_id ?? t('triggerSources.values.notFound') }}</strong>
            </div>
            <div>
              <span>{{ t('triggerSources.fields.httpReceipt') }}</span>
              <strong>{{ resultBindingDeliverySummary || t('triggerSources.values.notFound') }}</strong>
            </div>
            <div>
              <span>submit / ack</span>
              <strong>{{ submitMode }} / {{ ackPolicy }}</strong>
            </div>
          </div>
        </div>

        <div v-else class="trigger-source-inference">
          <div class="section-heading">
            <div><h2>{{ t('triggerSources.directorySummaryTitle') }}</h2></div>
            <StatusBadge tone="info">{{ protocolTemplateDisplayName(selectedProtocolTemplate) }}</StatusBadge>
          </div>
          <div class="summary-grid">
            <div><span>directory</span><strong>{{ directoryPath || '-' }}</strong></div>
            <div><span>filter</span><strong>{{ directoryGlobPattern }} / {{ directoryExtensions || '*' }}</strong></div>
            <div><span>event_types</span><strong>{{ directoryEventTypes.join(' / ') }}</strong></div>
            <div><span>interval / samples</span><strong>{{ directoryMinTriggerIntervalSeconds }}s / {{ directoryEventSampleLimit }}</strong></div>
          </div>
        </div>

        <details class="trigger-source-advanced">
          <summary class="section-heading trigger-source-advanced__summary">
            <strong>{{ t('triggerSources.advancedTitle') }}</strong>
            <Settings2 :size="16" />
          </summary>

          <div class="trigger-source-advanced__content">
            <div class="form-grid">
              <label class="field">
                <span>submit_mode</span>
                <SelectField :model-value="submitMode" :options="submitModeOptions" :disabled="selectedProtocolTemplate.triggerKind === 'local-shared-memory' || isDirectoryWatch" @update:model-value="setSubmitMode" />
              </label>
              <label class="field">
                <span>result_mode</span>
                <SelectField :model-value="resultMode" :options="resultModeOptions" :disabled="selectedProtocolTemplate.triggerKind === 'local-shared-memory' || isDirectoryWatch" @update:model-value="setResultMode" />
              </label>
              <label class="field">
                <span>ack_policy</span>
                <SelectField :model-value="ackPolicy" :options="ackPolicyOptions" :disabled="selectedProtocolTemplate.triggerKind === 'local-shared-memory' || isDirectoryWatch" @update:model-value="setAckPolicy" />
              </label>
              <label v-if="!isDirectoryWatch" class="field">
                <span>reply_timeout_seconds</span>
                <input v-model="replyTimeoutSeconds" inputmode="numeric" :placeholder="t('triggerSources.placeholders.emptyDefault')" />
              </label>
              <label v-if="!isDirectoryWatch" class="field">
                <span>debounce_window_ms</span>
                <input v-model="debounceWindowMs" inputmode="numeric" :placeholder="t('triggerSources.placeholders.emptyDisabled')" />
              </label>
              <label v-if="isDirectoryWatch" class="field">
                <span>min_trigger_interval_seconds</span>
                <input v-model="directoryMinTriggerIntervalSeconds" inputmode="decimal" />
              </label>
              <label v-if="isDirectoryWatch" class="field">
                <span>event_sample_limit</span>
                <input v-model="directoryEventSampleLimit" inputmode="numeric" />
              </label>
              <label v-if="isDirectoryWatch" class="field">
                <span>force_polling</span>
                <SelectField :model-value="directoryForcePolling" :options="forcePollingOptions" @update:model-value="directoryForcePolling = selectValueToString($event)" />
              </label>
              <label v-if="isDirectoryWatch" class="field">
                <span>poll_delay_ms</span>
                <input v-model="directoryPollDelayMs" inputmode="numeric" :disabled="directoryForcePolling !== 'true'" />
              </label>
              <label v-if="isDirectoryWatch" class="field">
                <span>ignore_permission_denied</span>
                <SelectField :model-value="directoryIgnorePermissionDenied" :options="booleanOptions" @update:model-value="directoryIgnorePermissionDenied = selectValueToBooleanString($event)" />
              </label>
              <label class="field">
                <span>idempotency_key_path</span>
                <input v-model="idempotencyKeyPath" placeholder="payload.request_id" />
              </label>
              <label class="field">
                <span>{{ t('triggerSources.fields.workflowRunRecord') }}</span>
                <SelectField :model-value="workflowRunRecordMode" :options="workflowRunRecordModeOptions" @update:model-value="setWorkflowRunRecordMode" />
              </label>
              <label class="field">
                <span>{{ t('triggerSources.fields.returnDiagnostics') }}</span>
                <SelectField :model-value="returnDiagnostics" :options="returnDiagnosticsOptions" @update:model-value="setReturnDiagnostics" />
              </label>
            </div>

            <div class="trigger-mapping-list">
              <article v-for="row in mappingRows" :key="row.bindingId" class="trigger-mapping-row">
                <div class="trigger-mapping-row__target">
                  <strong>{{ row.bindingId }}</strong>
                  <span>
                    {{ row.payloadTypeId || 'unknown' }} /
                    {{ row.required ? t('triggerSources.values.required') : t('triggerSources.values.optional') }} /
                    {{ !row.supported ? t('triggerSources.values.httpRuntimeOnly') : row.inferred ? t('triggerSources.values.inferred') : t('triggerSources.values.manual') }}
                  </span>
                </div>
                <label v-if="row.supported" class="field">
                  <span>{{ t('triggerSources.fields.mappingMode') }}</span>
                  <SelectField :model-value="row.mode" :options="mappingModeOptions" @update:model-value="setMappingMode(row, $event)" />
                </label>
                <label v-if="row.supported && row.mode === 'source'" class="field trigger-mapping-row__source">
                  <span>source path</span>
                  <input v-model="row.sourcePath" placeholder="payload.request_image_ref" />
                </label>
                <label v-else-if="row.supported && row.mode === 'static'" class="field trigger-mapping-row__source">
                  <span>{{ t('triggerSources.fields.staticValue') }}</span>
                  <input v-model="row.staticValue" :placeholder="t('triggerSources.placeholders.staticValue')" />
                </label>
                <p v-else-if="row.supported" class="trigger-mapping-row__hint">{{ t('triggerSources.mappingSkipped') }}</p>
                <p v-else class="trigger-mapping-row__hint">{{ t('triggerSources.highPerformanceInputUnsupported') }}</p>
              </article>
            </div>
          </div>
        </details>
      </template>
    </form>

    <section class="resource-section">
      <div class="section-heading">
        <div>
          <h2>{{ t('triggerSources.listTitle') }}</h2>
        </div>

        <StatusBadge tone="neutral">{{ totalTriggerSourceCount }}</StatusBadge>
      </div>
      <EmptyState
        v-if="triggerSources.length === 0"
        :title="t('triggerSources.emptyTitle')"
        :description="t('triggerSources.emptyDescription')"
      />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('triggerSources.fields.triggerSource') }}</th>
              <th>{{ t('triggerSources.fields.runtime') }}</th>
              <th>{{ t('triggerSources.fields.kind') }}</th>
              <th>{{ t('triggerSources.fields.state') }}</th>
              <th>{{ t('triggerSources.fields.health') }}</th>
              <th>{{ t('triggerSources.fields.lastError') }}</th>
              <th>{{ t('triggerSources.fields.actions') }}</th>
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
                <StatusBadge :tone="sourceStateTone(source)">{{ source.enabled ? t('triggerSources.values.enabled') : t('triggerSources.values.disabled') }} / {{ source.observed_state }}</StatusBadge>
              </td>
              <td>
                <strong>{{ formatHealthSummary(sourceHealth(source)?.health_summary ?? source.health_summary) || '-' }}</strong>
                <span>{{ formatLastTriggered(sourceHealth(source)?.last_triggered_at ?? source.last_triggered_at) }}</span>
              </td>
              <td>{{ formatError(sourceHealth(source)?.last_error ?? source.last_error) || '-' }}</td>
              <td>
                <div class="table-actions table-actions--wrap">
                  <Button v-if="!source.enabled" size="sm" variant="secondary" :disabled="busyTriggerSourceId === source.trigger_source_id" :loading="isTriggerSourceAction(source, 'state')" @click="setTriggerSourceEnabled(source, true)">
                    <Power :size="14" />
                    {{ t('triggerSources.actions.enable') }}
                  </Button>
                  <Button v-else size="sm" variant="secondary" :disabled="busyTriggerSourceId === source.trigger_source_id" :loading="isTriggerSourceAction(source, 'state')" @click="setTriggerSourceEnabled(source, false)">
                    <PowerOff :size="14" />
                    {{ t('triggerSources.actions.disable') }}
                  </Button>
                  <Button size="sm" variant="secondary" :disabled="busyTriggerSourceId === source.trigger_source_id" :loading="isTriggerSourceAction(source, 'health')" @click="refreshTriggerSourceHealth(source)">
                    <Activity :size="14" />
                    {{ t('triggerSources.actions.refreshHealth') }}
                  </Button>
                  <Button size="sm" variant="danger" :disabled="busyTriggerSourceId === source.trigger_source_id" :loading="isTriggerSourceAction(source, 'delete')" @click="requestDeleteTriggerSource(source)">
                    <Trash2 :size="14" />
                    {{ t('triggerSources.actions.delete') }}
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

    <ConfirmDialog
      v-if="pendingDeleteTriggerSource"
      :title="t('common.confirmDelete')"
      :message="t('triggerSources.messages.confirmDelete', { triggerSourceId: pendingDeleteTriggerSource.trigger_source_id })"
      :confirm-label="t('triggerSources.actions.delete')"
      :cancel-label="t('common.cancel')"
      :busy="isTriggerSourceAction(pendingDeleteTriggerSource, 'delete')"
      @cancel="pendingDeleteTriggerSource = null"
      @confirm="deleteTriggerSource"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Activity, Power, PowerOff, RefreshCw, Save, Settings2, Trash2, Workflow } from '@lucide/vue'

import { useProjectStore } from '@/app/stores/project.store'
import type { PaginationMeta } from '@/shared/api/pagination'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import MultiSelect from '@/shared/ui/components/MultiSelect.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import { getWorkflowApp, type WorkflowAppDocument } from '@/workflows/workflow-editor/services/workflow-app.service'
import {
  listWorkflowAppRuntimes,
  refreshWorkflowAppRuntimeStatuses,
} from '@/workflows/workflow-editor/services/workflow-runtime.service'
import type { FlowApplicationBinding, WorkflowAppRuntime, WorkflowJsonObject } from '@/workflows/workflow-editor/types'
import { supportsTriggerInputPayloadType } from '../trigger-input-capabilities'
import {
  createWorkflowTriggerSource,
  deleteWorkflowTriggerSource,
  disableWorkflowTriggerSource,
  enableWorkflowTriggerSource,
  getWorkflowTriggerSourceHealth,
  listWorkflowTriggerSources,
  refreshWorkflowTriggerSourceStatuses,
  type InputBindingMappingItem,
  type WorkflowTriggerSource,
  type WorkflowTriggerSourceHealth,
} from '../services/trigger-source.service'

type MappingMode = 'source' | 'static' | 'skip'
type ProtocolTemplateId = 'local-shared-memory' | 'zeromq-image-trigger' | 'webhook-json' | 'directory-watch'
type WorkflowRunRecordMode = 'full' | 'minimal' | 'none'
type TriggerSourceAction = 'state' | 'health' | 'delete'
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
  supported: boolean
}

interface ProtocolTemplateOption {
  templateId: ProtocolTemplateId
  displayNameKey: string
  triggerKind: string
  defaultEndpoint: string
  endpointLabel: string
  requiresEndpoint: boolean
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

const { t } = useI18n()

const protocolTemplates: ProtocolTemplateOption[] = [
  {
    templateId: 'local-shared-memory',
    displayNameKey: 'triggerSources.protocols.localSharedMemory',
    triggerKind: 'local-shared-memory',
    defaultEndpoint: '',
    endpointLabel: '',
    requiresEndpoint: false,
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
    templateId: 'zeromq-image-trigger',
    displayNameKey: 'triggerSources.protocols.zeromqImage',
    triggerKind: 'zeromq-topic',
    defaultEndpoint: 'tcp://127.0.0.1:5555',
    endpointLabel: 'bind_endpoint',
    requiresEndpoint: true,
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
    displayNameKey: 'triggerSources.protocols.webhookJson',
    triggerKind: 'webhook',
    defaultEndpoint: '/workflow-triggers/{trigger_source_id}',
    endpointLabel: 'webhook path',
    requiresEndpoint: true,
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
  {
    templateId: 'directory-watch',
    displayNameKey: 'triggerSources.protocols.directoryWatch',
    triggerKind: 'directory-watch',
    defaultEndpoint: '',
    endpointLabel: '',
    requiresEndpoint: false,
    submitMode: 'async',
    resultMode: 'event-only',
    ackPolicy: 'ack-after-run-created',
    imageBase64SourcePath: '',
    imageRefSourcePath: '',
    fallbackImageSourcePath: '',
    requestSourcePath: 'payload.directory_event_value',
    defaultInputBinding: 'request_json',
    defaultReplyTimeoutSeconds: 0,
    defaultIdempotencyKeyPath: 'payload.directory_event_value.value.event_id',
  },
]

const enableAfterCreateOptions = computed<SelectOption[]>(() => [
  { label: t('triggerSources.options.saveDisabled'), value: 'false' },
  { label: t('triggerSources.options.createEnabled'), value: 'true' },
])

const submitModeOptions = computed<SelectOption[]>(() => [
  { label: 'sync', value: 'sync', description: t('triggerSources.options.submitSync') },
  { label: 'async', value: 'async', description: t('triggerSources.options.submitAsync') },
])

const ackPolicyOptions = computed<SelectOption[]>(() => [
  { label: 'ack-after-run-finished', value: 'ack-after-run-finished', description: t('triggerSources.options.ackFinished') },
  { label: 'ack-after-run-created', value: 'ack-after-run-created', description: t('triggerSources.options.ackCreated') },
])

const workflowRunRecordModeOptions = computed<SelectOption[]>(() => [
  { label: 'minimal', value: 'minimal', description: t('triggerSources.options.recordMinimal') },
  { label: 'full', value: 'full', description: t('triggerSources.options.recordFull') },
  { label: 'none', value: 'none', description: t('triggerSources.options.recordNone') },
])

const returnDiagnosticsOptions = computed<SelectOption[]>(() => [
  { label: t('triggerSources.options.no'), value: 'false', description: t('triggerSources.options.diagnosticsOff') },
  { label: t('triggerSources.options.yes'), value: 'true', description: t('triggerSources.options.diagnosticsOn') },
])

const booleanOptions = computed<SelectOption[]>(() => [
  { label: t('triggerSources.options.no'), value: 'false' },
  { label: t('triggerSources.options.yes'), value: 'true' },
])

const forcePollingOptions = computed<SelectOption[]>(() => [
  { label: t('triggerSources.options.automatic'), value: 'auto' },
  { label: t('triggerSources.options.yes'), value: 'true' },
  { label: t('triggerSources.options.no'), value: 'false' },
])

const directoryEventTypeOptions = computed(() => [
  { label: t('triggerSources.options.directoryCreated'), value: 'created' },
  { label: t('triggerSources.options.directoryModified'), value: 'modified' },
  { label: t('triggerSources.options.directoryDeleted'), value: 'deleted' },
])

const mappingModeOptions = computed<SelectOption[]>(() => [
  { label: t('triggerSources.options.eventField'), value: 'source', description: t('triggerSources.options.eventFieldDescription') },
  { label: t('triggerSources.options.staticValue'), value: 'static', description: t('triggerSources.options.staticValueDescription') },
  { label: t('triggerSources.options.skip'), value: 'skip', description: t('triggerSources.options.skipDescription') },
])

const route = useRoute()
const projectStore = useProjectStore()

const loading = ref(false)
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const statusMessage = ref<string | null>(null)
const runtimes = ref<WorkflowAppRuntime[]>([])
const triggerSources = ref<WorkflowTriggerSource[]>([])
const triggerSourcePagination = ref<PaginationMeta>(createPaginationState())
const workflowApp = ref<WorkflowAppDocument | null>(null)
const selectedRuntimeId = ref('')
const protocolTemplateId = ref<ProtocolTemplateId>('local-shared-memory')
const triggerSourceId = ref('')
const displayName = ref('')
const endpoint = ref('')
const submitMode = ref<'async' | 'sync'>('sync')
const resultBindings = ref<string[]>([])
const resultMode = ref('sync-reply')
const ackPolicy = ref('ack-after-run-finished')
const replyTimeoutSeconds = ref('30')
const debounceWindowMs = ref('')
const idempotencyKeyPath = ref('')
const workflowRunRecordMode = ref<WorkflowRunRecordMode>('minimal')
const returnDiagnostics = ref('false')
const directoryPath = ref('')
const directoryRecursive = ref('false')
const directoryIncludeHidden = ref('false')
const directoryGlobPattern = ref('*')
const directoryExtensions = ref('')
const directoryEventTypes = ref<string[]>(['created', 'modified', 'deleted'])
const directoryMinTriggerIntervalSeconds = ref('3')
const directoryEventSampleLimit = ref('10')
const directoryForcePolling = ref('auto')
const directoryPollDelayMs = ref('300')
const directoryIgnorePermissionDenied = ref('false')
const enableAfterCreate = ref('false')
const mappingRows = ref<MappingRow[]>([])
const busyTriggerSourceId = ref<string | null>(null)
const busyTriggerSourceAction = ref<TriggerSourceAction | null>(null)
const pendingDeleteTriggerSource = ref<WorkflowTriggerSource | null>(null)
const healthByTriggerSourceId = ref<Record<string, WorkflowTriggerSourceHealth>>({})

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const selectedProtocolTemplate = computed(() => protocolTemplates.find((template) => template.templateId === protocolTemplateId.value) ?? protocolTemplates[0])
const isDirectoryWatch = computed(() => selectedProtocolTemplate.value.templateId === 'directory-watch')
const resultModeOptions = computed<SelectOption[]>(() => isDirectoryWatch.value
  ? [
      { label: 'event-only', value: 'event-only', description: t('triggerSources.options.resultEventOnly') },
    ]
  : [
      { label: 'sync-reply', value: 'sync-reply', description: t('triggerSources.options.resultSyncReply') },
      { label: 'accepted-then-query', value: 'accepted-then-query', description: t('triggerSources.options.resultAccepted') },
      { label: 'event-only', value: 'event-only', description: t('triggerSources.options.resultEventOnly') },
    ])
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
  if (appInputBindings.value.length === 0) return t('triggerSources.values.noExternalInput')
  const bindingIds = inferredImageBindings.value.map((binding) => binding.binding_id)
  return bindingIds.length > 0 ? bindingIds.join(' / ') : t('triggerSources.values.notFound')
})
const inferredRequestBinding = computed(() => findRequestInputBinding())
const runtimeOptions = computed<SelectOption[]>(() => [
  { label: t('triggerSources.placeholders.selectRuntime'), value: '' },
  ...runtimes.value.map((runtime) => ({
    label: `${runtime.display_name || runtime.workflow_runtime_id} / ${runtime.application_id} / ${runtime.observed_state}`,
    value: runtime.workflow_runtime_id,
  })),
])
const protocolTemplateOptions = computed<SelectOption[]>(() => protocolTemplates.map((template) => ({
  label: protocolTemplateDisplayName(template),
  value: template.templateId,
  description: protocolTemplateDescription(template),
})))
const resultBindingOptions = computed(() => [
  ...appOutputBindings.value.map((binding) => ({
    label: `${binding.binding_id} / ${getBindingPayloadTypeId(binding) || 'unknown'}`,
    value: binding.binding_id,
    description: describeResultBindingDelivery(getBindingPayloadTypeId(binding)),
  })),
])
const resultBindingDeliverySummary = computed(() => resultBindings.value.map((bindingId) => {
  const binding = appOutputBindings.value.find((item) => item.binding_id === bindingId)
  const delivery = describeResultBindingDelivery(binding ? getBindingPayloadTypeId(binding) : '')
  return `${bindingId} → ${delivery}`
}).join(' · '))
const totalTriggerSourceCount = computed(() => triggerSourcePagination.value.totalCount ?? triggerSources.value.length)
function protocolTemplateDisplayName(template: ProtocolTemplateOption): string {
  return t(template.displayNameKey)
}

function protocolTemplateDescription(template: ProtocolTemplateOption): string {
  if (template.triggerKind === 'local-shared-memory') return t('triggerSources.protocols.localSharedMemoryDescription')
  if (template.triggerKind === 'zeromq-topic') return t('triggerSources.protocols.zeromqImageDescription')
  if (template.triggerKind === 'directory-watch') return t('triggerSources.protocols.directoryWatchDescription')
  return t('triggerSources.protocols.webhookJsonDescription')
}

function usesImageRefTransport(template: ProtocolTemplateOption): boolean {
  return template.triggerKind === 'local-shared-memory' || template.triggerKind === 'zeromq-topic'
}

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
  protocolTemplateId.value = nextValue === 'webhook-json' || nextValue === 'zeromq-image-trigger' || nextValue === 'directory-watch'
    ? nextValue
    : 'local-shared-memory'
  applyProtocolTemplateDefaults()
}

function setEnableAfterCreate(value: SelectValue): void {
  enableAfterCreate.value = selectValueToString(value) === 'true' ? 'true' : 'false'
}

function setResultBindings(value: string[]): void {
  resultBindings.value = [...value]
}

function setSubmitMode(value: SelectValue): void {
  if (selectedProtocolTemplate.value.triggerKind === 'local-shared-memory' || isDirectoryWatch.value) return
  submitMode.value = selectValueToString(value) === 'async' ? 'async' : 'sync'
  resultMode.value = submitMode.value === 'sync' ? 'sync-reply' : 'accepted-then-query'
  ackPolicy.value = submitMode.value === 'sync' ? 'ack-after-run-finished' : 'ack-after-run-created'
  if (submitMode.value === 'async' && workflowRunRecordMode.value === 'none') {
    workflowRunRecordMode.value = 'minimal'
  }
}

function setResultMode(value: SelectValue): void {
  const nextValue = selectValueToString(value)
  if (isDirectoryWatch.value) {
    resultMode.value = 'event-only'
    resultBindings.value = []
    return
  }
  resultMode.value = nextValue || 'sync-reply'
}

function setAckPolicy(value: SelectValue): void {
  if (isDirectoryWatch.value) return
  ackPolicy.value = selectValueToString(value) || 'ack-after-run-finished'
}

function selectValueToBooleanString(value: SelectValue): string {
  return selectValueToString(value) === 'true' ? 'true' : 'false'
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

function describeResultBindingDelivery(payloadTypeId: string): string {
  if (resultMode.value === 'event-only') return 'ignored'
  const isImageAttachment = payloadTypeId === 'image-ref.v1' || payloadTypeId === 'image-refs.v1'
  if (!isImageAttachment) return 'JSON'
  if (resultMode.value === 'accepted-then-query') return 'ObjectStore'
  if (selectedProtocolTemplate.value.triggerKind === 'zeromq-topic') return 'ZeroMQ binary attachment'
  if (selectedProtocolTemplate.value.triggerKind === 'local-shared-memory') return 'LocalBuffer'
  return 'unsupported image attachment'
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
  if (usesImageRefTransport(selectedProtocolTemplate.value)) {
    addUniqueBinding(bindings, imageRefBinding)
    if (metadataBinding && isImageRefBinding(metadataBinding)) addUniqueBinding(bindings, metadataBinding)
  } else {
    addUniqueBinding(bindings, imageBase64Binding)
    addUniqueBinding(bindings, metadataBinding)
    addUniqueBinding(bindings, imageRefBinding)
  }
  if (bindings.length === 0 && !usesImageRefTransport(selectedProtocolTemplate.value)) {
    addUniqueBinding(bindings, appInputBindings.value.find(isImageInputBinding) ?? null)
  }
  return bindings
}

function findRequestInputBinding(): FlowApplicationBinding | null {
  const metadataBinding = findBindingFromMetadata('deployment_instance_id_binding')
  if (metadataBinding) return metadataBinding
  return appInputBindings.value.find((binding) => binding.binding_id === 'deployment_request' || binding.binding_id.includes('deployment_request')) ?? null
}

function findDefaultResultBindings(): string[] {
  const coreHttpResponse = appOutputBindings.value.find((binding) => binding.binding_id === 'core_output_http_response')
  if (coreHttpResponse) return [coreHttpResponse.binding_id]
  const httpResponse = appOutputBindings.value.find((binding) => binding.binding_id === 'http_response')
  if (httpResponse) return [httpResponse.binding_id]
  const firstOutput = appOutputBindings.value[0]
  return firstOutput ? [firstOutput.binding_id] : []
}

function defaultSourcePath(binding: FlowApplicationBinding): string {
  if (isDirectoryWatch.value && binding.binding_id === 'request_json' && getBindingPayloadTypeId(binding) === 'value.v1') {
    return 'payload.directory_event_value'
  }
  if (isImageBase64Binding(binding)) return selectedProtocolTemplate.value.imageBase64SourcePath
  if (isImageRefBinding(binding)) return selectedProtocolTemplate.value.imageRefSourcePath
  if (inferredImageBindings.value.some((item) => item.binding_id === binding.binding_id)) return selectedProtocolTemplate.value.fallbackImageSourcePath
  if (inferredRequestBinding.value?.binding_id === binding.binding_id) return selectedProtocolTemplate.value.requestSourcePath
  if (binding.binding_id === 'deployment_request') return 'payload.deployment_request'
  return `payload.${binding.binding_id}`
}

function buildDefaultEndpoint(template: ProtocolTemplateOption): string {
  if (!template.requiresEndpoint) return ''
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
    const payloadTypeId = getBindingPayloadTypeId(binding)
    const supported = supportsTriggerInputPayloadType(
      selectedProtocolTemplate.value.triggerKind,
      payloadTypeId,
    )
    const standardHighPerformanceInput = usesImageRefTransport(selectedProtocolTemplate.value)
      && ['request_image_ref', 'request_json', 'request_text'].includes(binding.binding_id)
    const standardDirectoryInput = isDirectoryWatch.value
      && binding.binding_id === 'request_json'
      && payloadTypeId === 'value.v1'
    return {
      bindingId: binding.binding_id,
      payloadTypeId,
      required: binding.required,
      mode: supported && (standardDirectoryInput || (!isDirectoryWatch.value && (inferred || standardHighPerformanceInput || binding.required))) ? 'source' : 'skip',
      sourcePath: defaultSourcePath(binding),
      staticValue: '',
      inferred,
      supported,
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
  const templatePrefix = template.templateId === 'webhook-json'
    ? 'webhook'
    : template.templateId === 'zeromq-image-trigger'
      ? 'zeromq'
      : template.templateId === 'directory-watch' ? 'directory-watch' : 'local-shared-memory'
  triggerSourceId.value = template.templateId === 'directory-watch'
    ? `${templatePrefix}-${runtimeSuffix}-${createShortUuid()}`
    : `${templatePrefix}-${runtimeSuffix}`
  displayName.value = `${protocolTemplateDisplayName(template)} ${runtime?.display_name || runtime?.application_id || ''}`.trim()
  endpoint.value = buildDefaultEndpoint(template)
  resultBindings.value = findDefaultResultBindings()
  replyTimeoutSeconds.value = template.defaultReplyTimeoutSeconds > 0 ? String(template.defaultReplyTimeoutSeconds) : ''
  debounceWindowMs.value = ''
  idempotencyKeyPath.value = template.defaultIdempotencyKeyPath
  workflowRunRecordMode.value = 'minimal'
  returnDiagnostics.value = 'false'
  directoryPath.value = ''
  directoryRecursive.value = 'false'
  directoryIncludeHidden.value = 'false'
  directoryGlobPattern.value = '*'
  directoryExtensions.value = ''
  directoryEventTypes.value = ['created', 'modified', 'deleted']
  directoryMinTriggerIntervalSeconds.value = '3'
  directoryEventSampleLimit.value = '10'
  directoryForcePolling.value = 'auto'
  directoryPollDelayMs.value = '300'
  directoryIgnorePermissionDenied.value = 'false'
  buildMappingRows()
}

function createShortUuid(): string {
  return crypto.randomUUID().replaceAll('-', '').slice(0, 8)
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
    errorMessage.value = error instanceof Error ? error.message : t('triggerSources.messages.loadAppFailed')
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
    const [runtimeResult, triggerSourceResult] = await Promise.all([
      listWorkflowAppRuntimes({ projectId: selectedProjectId.value, limit: 100 }),
      listWorkflowTriggerSources({
        projectId: selectedProjectId.value,
        offset: triggerSourceOffset,
        limit: triggerSourcePagination.value.limit,
      }),
    ])
    const [runtimeStatusResult, triggerStatusResult] = await Promise.all([
      refreshWorkflowAppRuntimeStatuses(runtimeResult.items),
      refreshWorkflowTriggerSourceStatuses(triggerSourceResult.items),
    ])
    runtimes.value = runtimeStatusResult.items
    triggerSources.value = triggerStatusResult.items
    healthByTriggerSourceId.value = triggerStatusResult.healthByTriggerSourceId
    triggerSourcePagination.value = triggerSourceResult.pagination
    const queryRuntimeId = readQueryString('runtime_id')
    const queryApplicationId = readQueryString('application_id')
    const contextRuntime = runtimes.value.find((runtime) => runtime.workflow_runtime_id === queryRuntimeId)
      ?? runtimes.value.find((runtime) => runtime.application_id === queryApplicationId)
      ?? runtimes.value.find((runtime) => runtime.workflow_runtime_id === selectedRuntimeId.value)
      ?? runtimes.value[0]
    selectedRuntimeId.value = contextRuntime?.workflow_runtime_id ?? ''
    await loadSelectedRuntimeApp()
    const failedIds = [...runtimeStatusResult.failedRuntimeIds, ...triggerStatusResult.failedTriggerSourceIds]
    if (failedIds.length > 0) {
      errorMessage.value = t('triggerSources.messages.partialRuntimeRefreshFailed', { runtimeIds: failedIds.join(', ') })
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('triggerSources.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

function buildTransportConfig(): WorkflowJsonObject {
  const normalizedEndpoint = endpoint.value.trim().replace('{trigger_source_id}', triggerSourceId.value.trim())
  if (isDirectoryWatch.value) {
    const forcePolling = directoryForcePolling.value === 'auto'
      ? null
      : directoryForcePolling.value === 'true'
    return {
      directory_path: directoryPath.value.trim(),
      recursive: directoryRecursive.value === 'true',
      include_hidden: directoryIncludeHidden.value === 'true',
      glob_pattern: directoryGlobPattern.value.trim(),
      extensions: parseDirectoryExtensions(directoryExtensions.value),
      event_types: [...directoryEventTypes.value],
      min_trigger_interval_seconds: Number(directoryMinTriggerIntervalSeconds.value),
      event_sample_limit: Number(directoryEventSampleLimit.value),
      force_polling: forcePolling,
      poll_delay_ms: Number(directoryPollDelayMs.value),
      ignore_permission_denied: directoryIgnorePermissionDenied.value === 'true',
    }
  }
  if (selectedProtocolTemplate.value.triggerKind === 'local-shared-memory') {
    return {
      default_input_binding: selectedProtocolTemplate.value.defaultInputBinding,
    }
  }
  if (selectedProtocolTemplate.value.templateId === 'zeromq-image-trigger') {
    return {
      bind_endpoint: normalizedEndpoint,
      default_input_binding: selectedProtocolTemplate.value.defaultInputBinding,
      content_transport: 'local-buffer',
    }
  }
  return { path: normalizedEndpoint, method: 'POST' }
}

function buildDefaultExecutionMetadata(): WorkflowJsonObject {
  const metadata: WorkflowJsonObject = {
    workflow_run_record_mode: workflowRunRecordMode.value,
    return_timing_metadata_enabled: returnDiagnostics.value === 'true',
    return_node_timings_enabled: returnDiagnostics.value === 'true',
    trace_level: 'none',
    retain_trace_enabled: false,
    retain_node_records_enabled: false,
  }
  if (selectedProtocolTemplate.value.triggerKind === 'local-shared-memory' || selectedProtocolTemplate.value.triggerKind === 'zeromq-topic') {
    return {
      ...metadata,
      retain_input_payload_enabled: false,
      retain_outputs_enabled: false,
    }
  }
  return metadata
}

function buildMatchRule(): WorkflowJsonObject {
  if (selectedProtocolTemplate.value.templateId === 'webhook-json') return { method: 'POST' }
  return {}
}

function buildInputBindingMapping(): Record<string, InputBindingMappingItem> {
  const mapping: Record<string, InputBindingMappingItem> = {}
  for (const row of mappingRows.value) {
    if (!row.supported || row.mode === 'skip') continue
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
  const timeoutCount = value.timeout_count
  const busyCount = value.busy_count
  const capacityRejectCount = value.capacity_reject_count
  const requestTimeoutCount = value.request_timeout_count
  const responseAckTimeoutCount = value.response_ack_timeout_count
  const cancelCount = value.cancel_count
  if (adapterRunning !== undefined || requestCount !== undefined || successCount !== undefined || errorCount !== undefined) {
    return [
      `running=${String(adapterRunning ?? '-')}`,
      `request=${String(requestCount ?? 0)}`,
      `success=${String(successCount ?? 0)}`,
      `error=${String(errorCount ?? 0)}`,
      `timeout=${String(timeoutCount ?? 0)}`,
      `busy=${String(busyCount ?? 0)}`,
      `capacity=${String(capacityRejectCount ?? 0)}`,
      `request-timeout=${String(requestTimeoutCount ?? 0)}`,
      `ack-timeout=${String(responseAckTimeoutCount ?? 0)}`,
      `cancel=${String(cancelCount ?? 0)}`,
    ].join(' ')
  }
  return Object.keys(value).length > 0 ? JSON.stringify(value) : ''
}

function formatError(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function formatLastTriggered(value: string | null | undefined): string {
  return value ? formatSystemDateTime(value) : t('triggerSources.values.neverTriggered')
}

async function submitTriggerSource(): Promise<void> {
  const runtime = selectedRuntime.value
  if (!runtime) return
  saving.value = true
  errorMessage.value = null
  statusMessage.value = null
  try {
    const normalizedTriggerSourceId = triggerSourceId.value.trim()
    if (!normalizedTriggerSourceId) throw new Error(t('triggerSources.messages.idRequired'))
    if (isDirectoryWatch.value) validateDirectoryWatchForm()
    if (submitMode.value === 'async' && workflowRunRecordMode.value === 'none') {
      throw new Error(t('triggerSources.messages.asyncRecordNone'))
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
        result_bindings: [...resultBindings.value],
      },
      defaultExecutionMetadata: buildDefaultExecutionMetadata(),
      ackPolicy: ackPolicy.value,
      resultMode: resultMode.value,
      replyTimeoutSeconds: parseOptionalNumber(replyTimeoutSeconds.value),
      debounceWindowMs: isDirectoryWatch.value ? null : parseOptionalNumber(debounceWindowMs.value),
      idempotencyKeyPath: idempotencyKeyPath.value.trim() || null,
      metadata: {
        source: 'web-ui-trigger-source-wizard',
        protocol_template: protocolTemplateId.value,
        application_id: runtime.application_id,
        default_input_binding: selectedProtocolTemplate.value.defaultInputBinding,
        image_transport: selectedProtocolTemplate.value.triggerKind === 'local-shared-memory'
          ? 'local-buffer-arena'
          : selectedProtocolTemplate.value.triggerKind === 'zeromq-topic'
            ? 'zeromq-multipart'
            : isDirectoryWatch.value ? 'none' : 'json',
        inferred_image_binding: inferredImageBinding.value?.binding_id ?? null,
        inferred_image_bindings: inferredImageBindings.value.map((binding) => binding.binding_id),
        inferred_request_binding: inferredRequestBinding.value?.binding_id ?? null,
        manual_mapping_available: true,
      },
    })
    await loadPage({ triggerSourceOffset: 0, preserveStatusMessage: true })
    statusMessage.value = t('triggerSources.messages.created', { triggerSourceId: triggerSource.trigger_source_id })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('triggerSources.messages.createFailed')
  } finally {
    saving.value = false
  }
}

async function setTriggerSourceEnabled(source: WorkflowTriggerSource, enabled: boolean): Promise<void> {
  busyTriggerSourceId.value = source.trigger_source_id
  busyTriggerSourceAction.value = 'state'
  errorMessage.value = null
  try {
    const updatedSource = enabled
      ? await enableWorkflowTriggerSource(source.trigger_source_id)
      : await disableWorkflowTriggerSource(source.trigger_source_id)
    replaceTriggerSource(updatedSource)
    statusMessage.value = t(
      enabled ? 'triggerSources.messages.enabled' : 'triggerSources.messages.disabled',
      { triggerSourceId: source.trigger_source_id },
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('triggerSources.messages.updateStateFailed')
  } finally {
    busyTriggerSourceId.value = null
    busyTriggerSourceAction.value = null
  }
}

function validateDirectoryWatchForm(): void {
  const interval = Number(directoryMinTriggerIntervalSeconds.value)
  const sampleLimit = Number(directoryEventSampleLimit.value)
  const pollDelay = Number(directoryPollDelayMs.value)
  if (!directoryPath.value.trim()) throw new Error(t('triggerSources.messages.directoryPathRequired'))
  if (!directoryGlobPattern.value.trim()) throw new Error(t('triggerSources.messages.directoryGlobRequired'))
  if (directoryEventTypes.value.length === 0) throw new Error(t('triggerSources.messages.directoryEventTypeRequired'))
  if (!Number.isFinite(interval) || interval < 1 || interval > 3600) {
    throw new Error(t('triggerSources.messages.directoryIntervalInvalid'))
  }
  if (!Number.isInteger(sampleLimit) || sampleLimit < 0 || sampleLimit > 100) {
    throw new Error(t('triggerSources.messages.directorySampleLimitInvalid'))
  }
  if (!Number.isInteger(pollDelay) || pollDelay < 50 || pollDelay > 60000) {
    throw new Error(t('triggerSources.messages.directoryPollDelayInvalid'))
  }
}

function parseDirectoryExtensions(value: string): string[] {
  return [...new Set(value.split(',').map((item) => item.trim()).filter(Boolean))]
}

async function refreshTriggerSourceHealth(source: WorkflowTriggerSource): Promise<void> {
  busyTriggerSourceId.value = source.trigger_source_id
  busyTriggerSourceAction.value = 'health'
  errorMessage.value = null
  try {
    const health = await getWorkflowTriggerSourceHealth(source.trigger_source_id)
    healthByTriggerSourceId.value = { ...healthByTriggerSourceId.value, [source.trigger_source_id]: health }
    source.health_summary = { ...health.health_summary } as WorkflowJsonObject
    source.last_error = health.last_error ?? null
    source.last_triggered_at = health.last_triggered_at ?? null
    statusMessage.value = t('triggerSources.messages.healthUpdated', { triggerSourceId: source.trigger_source_id })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('triggerSources.messages.healthFailed')
  } finally {
    busyTriggerSourceId.value = null
    busyTriggerSourceAction.value = null
  }
}

function requestDeleteTriggerSource(source: WorkflowTriggerSource): void {
  if (busyTriggerSourceId.value === source.trigger_source_id) return
  pendingDeleteTriggerSource.value = source
}

async function deleteTriggerSource(): Promise<void> {
  const source = pendingDeleteTriggerSource.value
  if (!source) return
  busyTriggerSourceId.value = source.trigger_source_id
  busyTriggerSourceAction.value = 'delete'
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
    statusMessage.value = t('triggerSources.messages.deleted', { triggerSourceId: source.trigger_source_id })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('triggerSources.messages.deleteFailed')
  } finally {
    busyTriggerSourceId.value = null
    busyTriggerSourceAction.value = null
    pendingDeleteTriggerSource.value = null
  }
}

function isTriggerSourceAction(source: WorkflowTriggerSource, action: TriggerSourceAction): boolean {
  return busyTriggerSourceId.value === source.trigger_source_id && busyTriggerSourceAction.value === action
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
.trigger-source-runtime-empty {
  border: 0;
  background: transparent;
}

.trigger-source-inference {
  display: grid;
  gap: 12px;
}

.trigger-source-advanced {
  overflow: hidden;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-soft);
}

.trigger-source-advanced__summary {
  min-height: 42px;
  padding: 10px 12px;
  cursor: pointer;
  list-style: none;
}

.trigger-source-advanced__summary::-webkit-details-marker {
  display: none;
}

.trigger-source-advanced[open] .trigger-source-advanced__summary {
  border-bottom: 1px solid var(--am-border);
}

.trigger-source-advanced__content {
  display: grid;
  gap: 16px;
  padding: 14px 12px 12px;
}

.trigger-source-page__pagination {
  margin-top: 16px;
}
</style>
