<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <h1>{{ t('deploymentOps.title') }}</h1>
        <p class="page-description">{{ t('deploymentOps.description') }}</p>
      </div>
      <div class="page-actions">
        <label class="segmented-field">
          <span>{{ t('deploymentOps.fields.runtimeMode') }}</span>
          <SelectField :model-value="runtimeMode" :options="runtimeModeOptions" @update:model-value="setRuntimeMode" />
        </label>
        <Button variant="secondary" :disabled="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <div class="operation-grid deployment-workspace-grid">
      <form class="form-panel deployment-create-panel" @submit.prevent="submitDeployment">
        <div>
          <h2>{{ t('deploymentOps.createTitle') }}</h2>
        </div>
        <section class="deployment-source-summary">
          <div class="section-heading">
            <div>
              <h3>{{ t('deploymentOps.source.title') }}</h3>
            </div>
            <Button type="button" variant="secondary" :disabled="sourceModelsLoading" @click="openDeploymentSourcePicker">
              {{ selectedDeploymentSource ? t('deploymentOps.source.change') : t('deploymentOps.source.choose') }}
            </Button>
          </div>
          <div v-if="selectedDeploymentSource" class="summary-grid deployment-source-summary__grid">
            <div>
              <span>{{ t('deploymentOps.columns.model') }}</span>
              <strong>{{ selectedDeploymentSource.modelName }}</strong>
            </div>
            <div>
              <span>model_type</span>
              <strong>{{ selectedDeploymentSource.modelType }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentOps.source.kind') }}</span>
              <strong>{{ selectedDeploymentSource.sourceKind === 'model-build' ? 'ModelBuild' : 'ModelVersion' }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentOps.source.id') }}</span>
              <strong>
                {{ selectedDeploymentSource.modelBuildId || selectedDeploymentSource.modelVersionId }}
              </strong>
            </div>
            <div>
              <span>Build format</span>
              <strong>{{ selectedDeploymentSource.buildFormat || '-' }}</strong>
            </div>
            <div>
              <span>Runtime backend</span>
              <strong>{{ selectedDeploymentSource.runtimeBackend || '-' }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentOps.fields.runtimePrecision') }}</span>
              <strong>{{ selectedDeploymentSource.runtimePrecision || '-' }}</strong>
            </div>
            <div>
              <span>RuntimeProfile id</span>
              <strong>{{ selectedDeploymentSource.runtimeProfileId || '-' }}</strong>
            </div>
          </div>
          <div v-else class="source-empty-card">
            <strong>{{ t('deploymentOps.source.emptyTitle') }}</strong>
            <span>{{ t('deploymentOps.source.emptyDescription') }}</span>
          </div>
        </section>
        <div class="form-grid deployment-create-grid">
          <label class="field">
            <span>{{ t('deploymentOps.fields.deviceName') }}</span>
            <SelectField :model-value="deviceName" :options="deploymentDeviceOptions" @update:model-value="setDeviceName" />
          </label>
          <label class="field">
            <span>{{ t('deploymentOps.fields.instanceCount') }}</span>
            <input
              v-model.number="instanceCount"
              type="number"
              min="1"
              max="64"
              step="1"
              @blur="normalizeInstanceCount"
            />
          </label>
          <div v-if="isOpenVinoBackend" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.openvinoPerformanceHint') }}</span>
            <SelectField
              :model-value="openvinoPerformanceHint"
              :options="openvinoPerformanceHintOptions"
              @update:model-value="setOpenvinoPerformanceHint"
            />
          </div>
          <div v-if="openvinoDeviceKind === 'cpu' && supportedRuntimeField('inference_num_threads')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.openvinoInferenceThreads') }}</span>
            <SelectField
              :model-value="openvinoInferenceNumThreads"
              :options="openvinoInferenceThreadOptions"
              @update:model-value="setOpenvinoInferenceNumThreads"
            />
          </div>
          <label v-if="(openvinoDeviceKind === 'cpu' || openvinoDeviceKind === 'gpu') && supportedRuntimeField('num_streams')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.openvinoStreams') }}</span>
            <input
              v-model.number="openvinoNumStreams"
              type="number"
              min="1"
              step="1"
              @blur="normalizeOpenvinoNumStreams"
            />
          </label>
          <div v-if="openvinoDeviceKind === 'cpu' && supportedRuntimeField('scheduling_core_type')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.cpuCoreType') }}</span>
            <SelectField
              :model-value="openvinoSchedulingCoreType"
              :options="openvinoSchedulingCoreTypeOptions"
              @update:model-value="setOpenvinoSchedulingCoreType"
            />
          </div>
          <div v-if="openvinoDeviceKind === 'cpu' && supportedRuntimeField('enable_hyper_threading')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.hyperThreading') }}</span>
            <SelectField
              :model-value="openvinoHyperThreading"
              :options="autoBooleanOptions"
              @update:model-value="setOpenvinoHyperThreading"
            />
          </div>
          <div v-if="openvinoDeviceKind === 'cpu' && supportedRuntimeField('enable_cpu_pinning')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.cpuPinning') }}</span>
            <SelectField
              :model-value="openvinoCpuPinning"
              :options="autoBooleanOptions"
              @update:model-value="setOpenvinoCpuPinning"
            />
          </div>
          <div v-if="isOpenVinoBackend && openvinoDeviceKind !== 'cpu' && supportedRuntimeField('num_requests')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.openvinoInferRequests') }}</span>
            <div class="field-control-row">
              <SelectField
                :model-value="openvinoNumRequestsMode"
                :options="openvinoNumRequestsModeOptions"
                @update:model-value="setOpenvinoNumRequestsMode"
              />
              <input
                v-if="openvinoNumRequestsMode === 'manual'"
                v-model.number="openvinoNumRequests"
                type="number"
                min="1"
                step="1"
                :aria-label="t('deploymentOps.runtimeConfig.openvinoInferRequests')"
                @blur="normalizeOpenvinoNumRequests"
              />
            </div>
          </div>
          <div v-if="(openvinoDeviceKind === 'gpu' || openvinoDeviceKind === 'npu') && supportedRuntimeField('inference_precision')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.inferencePrecision') }}</span>
            <SelectField
              :model-value="openvinoInferencePrecision"
              :options="openvinoInferencePrecisionOptions"
              @update:model-value="setOpenvinoInferencePrecision"
            />
          </div>
          <div v-if="openvinoDeviceKind === 'npu' && supportedRuntimeField('turbo')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.npuTurbo') }}</span>
            <SelectField
              :model-value="openvinoNpuTurbo"
              :options="autoBooleanOptions"
              @update:model-value="setOpenvinoNpuTurbo"
            />
          </div>
          <div v-if="openvinoDeviceKind === 'npu' && supportedRuntimeField('tiles')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.npuTiles') }}</span>
            <div class="field-control-row">
              <SelectField
                :model-value="openvinoNpuTilesMode"
                :options="autoManualOptions"
                @update:model-value="setOpenvinoNpuTilesMode"
              />
              <input
                v-if="openvinoNpuTilesMode === 'manual'"
                v-model.number="openvinoNpuTiles"
                type="number"
                min="1"
                :max="openvinoNpuMaxTiles ?? undefined"
                step="1"
                :aria-label="t('deploymentOps.runtimeConfig.npuTiles')"
                @blur="normalizeOpenvinoNpuTiles"
              />
            </div>
          </div>
          <label v-if="openvinoDeviceKind === 'npu' && supportedRuntimeField('compilation_mode_params')" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.npuCompilationModeParams') }}</span>
            <input v-model="openvinoNpuCompilationModeParams" />
          </label>
          <div
            v-if="showTensorRtSingleProfileRange"
            class="field"
          >
            <span>{{ t('deploymentOps.runtimeConfig.tensorrtProfileRange') }}</span>
            <div class="deployment-profile-summary">
              <span
                v-for="line in tensorRtSingleProfileRangeLines"
                :key="line"
              >
                {{ line }}
              </span>
            </div>
          </div>
          <div v-if="showTensorRtProfileSelector" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.tensorrtOptimizationProfile') }}</span>
            <SelectField
              :model-value="tensorrtOptimizationProfileIndex"
              :options="tensorRtOptimizationProfileOptions"
              @update:model-value="setTensorrtOptimizationProfileIndex"
            />
          </div>
          <div v-if="isTensorRtBackend" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.tensorrtPinnedOutput') }}</span>
            <SelectField
              :model-value="tensorrtPinnedOutput"
              :options="serviceDefaultBooleanOptions"
              @update:model-value="setTensorrtPinnedOutput"
            />
          </div>
          <div class="field">
            <span>{{ t('deploymentOps.runtimeConfig.keepWarm') }}</span>
            <SelectField
              :model-value="keepWarmEnabled"
              :options="enabledDisabledOptions"
              @update:model-value="setKeepWarmEnabled"
            />
          </div>
          <label v-if="keepWarmEnabled === 'true'" class="field">
            <span>{{ t('deploymentOps.runtimeConfig.keepWarmInterval') }}</span>
            <input
              v-model.number="keepWarmIntervalSeconds"
              type="number"
              min="0.01"
              step="0.01"
              @blur="normalizeKeepWarmIntervalSeconds"
            />
          </label>
          <label class="field field--wide">
            <span>{{ t('deploymentOps.fields.displayName') }}</span>
            <input v-model="displayName" />
          </label>
        </div>
        <div class="form-actions">
          <Button variant="primary" type="submit" :disabled="!canWriteModels || creating">
            <Zap :size="16" />
            {{ creating ? t('deploymentOps.actions.creating') : t('deploymentOps.actions.create') }}
          </Button>
        </div>
        <p v-if="lastCreatedDeployment" class="result-note">
          {{ t('deploymentOps.messages.created') }} {{ lastCreatedDeployment.deployment_instance_id }}
        </p>
      </form>

      <section class="resource-section deployment-instances-panel">
        <div class="section-heading">
          <div>
            <h2>{{ t('deploymentOps.listTitle') }}</h2>
          </div>
          <StatusBadge tone="info">{{ deployments.length }}</StatusBadge>
        </div>
        <EmptyState v-if="!loading && deployments.length === 0" :title="t('deploymentOps.emptyTitle')" :description="t('deploymentOps.emptyDescription')" />
        <div v-else class="deployment-instance-list">
          <article
            v-for="item in deployments"
            :key="item.deployment_instance_id"
            class="deployment-instance-card"
            :class="{ 'deployment-instance-card--selected': item.deployment_instance_id === selectedDeploymentId }"
            :data-deployment-id="item.deployment_instance_id"
            @click="selectDeployment(item.deployment_instance_id)"
          >
            <header class="deployment-instance-card__header">
              <div class="deployment-instance-card__title">
                <strong>{{ item.display_name || item.deployment_instance_id }}</strong>
                <span>{{ item.deployment_instance_id }}</span>
              </div>
              <div class="deployment-instance-card__states">
                <StatusBadge :tone="statusTone(item.status)">{{ item.status }}</StatusBadge>
                <StatusBadge :tone="runtimeProcessTone(item)">{{ runtimeProcessLabel(item) }}</StatusBadge>
              </div>
            </header>
            <div class="deployment-instance-card__details">
              <div>
                <span>{{ t('deploymentOps.columns.model') }}</span>
                <strong>{{ item.model_name }}</strong>
                <small>{{ item.model_version_id }} / {{ item.model_build_id || '-' }}</small>
              </div>
              <div>
                <span>Runtime</span>
                <strong>{{ formatRuntimeLabel(item) }}</strong>
                <small>{{ item.runtime_execution_mode }} · {{ item.source_kind }}</small>
              </div>
              <div>
                <span>{{ t('deploymentOps.columns.instances') }}</span>
                <strong>{{ getDeploymentInstanceCount(item) }}</strong>
                <small>{{ formatInputSize(item.input_size) }}</small>
              </div>
            </div>
            <div class="deployment-instance-card__actions" @click.stop>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                :disabled="!canStartDeployment(item)"
                data-deployment-action="start"
                @click="runStatusAction(item.deployment_instance_id, runtimeMode, 'start')"
              >
                <Play :size="14" />
                {{ t('deploymentOps.actions.start') }}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                :disabled="!canWarmupDeployment(item)"
                :title="warmupButtonTitle(item)"
                data-deployment-action="warmup"
                @click="runHealthAction(item.deployment_instance_id, runtimeMode, 'warmup')"
              >
                <Zap :size="14" />
                {{ t('deploymentOps.actions.warmup') }}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                :disabled="!canResetDeployment(item)"
                data-deployment-action="reset"
                @click="runHealthAction(item.deployment_instance_id, runtimeMode, 'reset')"
              >
                <RotateCcw :size="14" />
                {{ t('deploymentOps.actions.reset') }}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="danger"
                :disabled="!canStopDeployment(item)"
                data-deployment-action="stop"
                @click="runStatusAction(item.deployment_instance_id, runtimeMode, 'stop')"
              >
                <Square :size="14" />
                {{ t('deploymentOps.actions.stop') }}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="danger"
                :disabled="!canDeleteDeployment(item)"
                :title="deleteButtonTitle(item)"
                data-deployment-action="delete"
                @click="openDeleteDeploymentDialog(item.deployment_instance_id)"
              >
                <Trash2 :size="14" />
                {{ t('deploymentOps.actions.delete') }}
              </Button>
            </div>
          </article>
        </div>
        <p v-if="runtimeCapabilitiesLoading" class="result-note">{{ t('deploymentOps.messages.capabilitiesLoading') }}</p>
        <p v-else-if="runtimeCapabilityWarnings.length" class="result-note">
          {{ runtimeCapabilityWarnings.join('；') }}
        </p>
      </section>
    </div>

    <DeploymentSourcePickerDialog
      :open="deploymentSourcePickerOpen"
      :loading="sourceModelsLoading"
      :task-type="selectedTaskType"
      :task-type-options="taskTypeOptions"
      :models="sourceModels"
      :selected-model-id="selectedSourceModelId"
      :selected-model-detail="selectedSourceModelDetail"
      :selected-version-id="modelVersionId"
      :selected-build-id="modelBuildId"
      :devices="sessionStore.bootstrap?.devices ?? null"
      @close="deploymentSourcePickerOpen = false"
      @change-task-type="setTaskType"
      @select-model="selectDeploymentSourceModel"
      @apply-source="applyDeploymentSource"
    />

    <ConfirmDialog
      v-if="pendingDeleteDeployment"
      :title="t('deploymentOps.actions.delete')"
      :message="t('common.confirmDelete')"
      :details="deleteDeploymentDialogDetails"
      :confirm-label="t('deploymentOps.actions.delete')"
      :cancel-label="t('common.cancel')"
      :busy="isDeleteActionBusy(pendingDeleteDeployment.deployment_instance_id)"
      confirm-variant="danger"
      @cancel="closeDeleteDeploymentDialog"
      @confirm="confirmDeleteDeployment"
    />

    <div v-if="selectedDeployment" class="operation-grid deployment-runtime-grid">
      <section class="resource-section deployment-runtime-panel">
        <div class="section-heading">
          <div>
            <h2>{{ t('deploymentOps.runtimeTitle') }}</h2>
            <p class="page-description">{{ selectedDeployment.deployment_instance_id }}</p>
          </div>
        </div>
        <div class="summary-grid deployment-runtime-summary">
          <div>
            <span>{{ t('deploymentOps.fields.deploymentId') }}</span>
            <strong>{{ selectedDeployment.deployment_instance_id }}</strong>
          </div>
          <div>
            <span>{{ t('deploymentOps.fields.runtimeMode') }}</span>
            <strong>{{ selectedRuntimeStatus?.runtime_mode || selectedDeployment.runtime_execution_mode }}</strong>
          </div>
          <div>
            <span>{{ t('deploymentOps.fields.processState') }}</span>
            <strong>{{ selectedRuntimeStatus?.process_state || t('deploymentOps.states.notInspected') }}</strong>
          </div>
          <div>
            <span>{{ t('deploymentOps.fields.processId') }}</span>
            <strong>{{ selectedRuntimeStatus?.process_id ?? '-' }}</strong>
          </div>
          <div>
            <span>{{ t('deploymentOps.fields.healthyInstances') }}</span>
            <strong>{{ selectedRuntimeHealth?.healthy_instance_count ?? '-' }}</strong>
          </div>
          <div>
            <span>{{ t('deploymentOps.fields.warmedInstances') }}</span>
            <strong>{{ selectedRuntimeHealth?.warmed_instance_count ?? '-' }}</strong>
          </div>
          <div>
            <span>{{ t('deploymentOps.fields.pinnedBytes') }}</span>
            <strong>{{ selectedRuntimeHealth?.pinned_output_total_bytes ?? '-' }}</strong>
          </div>
          <div>
            <span>{{ t('deploymentOps.fields.lastError') }}</span>
            <strong>{{ selectedRuntimeHealth?.last_error || selectedRuntimeStatus?.last_error || '-' }}</strong>
          </div>
        </div>
        <div
          v-if="selectedRuntimeHealth?.configuration_warnings.length"
          class="runtime-configuration-warnings"
        >
          <strong>{{ t('deploymentOps.runtimeDiagnostics.warnings') }}</strong>
          <ul>
            <li
              v-for="warning in selectedRuntimeHealth.configuration_warnings"
              :key="warning"
            >
              {{ warning }}
            </li>
          </ul>
        </div>
        <div v-if="selectedRuntimeHealth" class="runtime-configuration-diagnostics">
          <details>
            <summary>{{ t('deploymentOps.runtimeDiagnostics.requested') }}</summary>
            <pre>{{ formatRuntimeConfiguration(selectedRuntimeHealth.requested_runtime_configuration) }}</pre>
          </details>
          <details>
            <summary>{{ t('deploymentOps.runtimeDiagnostics.effective') }}</summary>
            <pre>{{ formatRuntimeConfiguration(selectedRuntimeHealth.effective_runtime_configuration) }}</pre>
          </details>
        </div>
      </section>

      <section class="resource-section deployment-events-panel">
        <div class="section-heading">
          <div>
            <h2>{{ t('deploymentOps.eventsTitle') }}</h2>
            <p class="page-description">{{ selectedDeployment.deployment_instance_id }}</p>
          </div>
        </div>
        <EmptyState v-if="!eventsLoading && deploymentEvents.length === 0" :title="t('deploymentOps.emptyEventsTitle')" :description="t('deploymentOps.emptyEventsDescription')" />
        <ol v-else class="event-timeline event-timeline--compact">
          <li v-for="event in sortedDeploymentEvents" :key="`${event.runtime_mode}-${event.sequence}`">
            <time>{{ formatSystemDateTime(event.created_at) }}</time>
            <strong>{{ event.event_type }}</strong>
            <span>{{ event.message }}</span>
          </li>
        </ol>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Play, RefreshCw, RotateCcw, Square, Trash2, Zap } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import {
  createTaskDeployment,
  deleteTaskDeployment,
  getDeploymentInstanceCount,
  getDeploymentRuntimeCapabilities,
  listTaskDeploymentEvents,
  listTaskDeployments,
  runTaskDeploymentHealthAction,
  runTaskDeploymentStatusAction,
  type DeploymentHealthAction,
  type DeploymentBackendOptions,
  type DeploymentRuntimeCapabilities,
  type DeploymentRuntimeConfiguration,
  type DeploymentRuntimeMode,
  type DeploymentStatusAction,
  type ModelTaskType,
  type TaskDeploymentInstance,
  type TaskDeploymentProcessEvent,
  type TaskDeploymentProcessStatus,
  type TaskDeploymentRuntimeHealth,
} from '../services/deployment.service'
import DeploymentSourcePickerDialog from '../components/DeploymentSourcePickerDialog.vue'
import type { DeploymentSourceSelection } from '../components/deployment-source.types'
import { buildDeploymentDeviceOptions, hasCudaDevice } from '../deployment-device-support'
import {
  formatTensorRtShape,
  parseTensorRtEngineCapabilities,
  type TensorRtOptimizationProfile,
} from '../tensorrt-engine-capabilities'
import {
  getDeploymentSourceModelDetail,
  listDeploymentSourceModels,
  type DeploymentSourceModelDetail,
  type DeploymentSourceModelSummary,
} from '@/modules/models/services/model.service'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

type SelectValue = string | number | boolean | null
const TASK_TYPES: readonly ModelTaskType[] = ['detection', 'classification', 'segmentation', 'pose', 'obb']

interface DeploymentListCandidate {
  item: TaskDeploymentInstance
  routeTaskType: ModelTaskType
}

interface DeploymentRuntimeSnapshot {
  status: TaskDeploymentProcessStatus | null
  health: TaskDeploymentRuntimeHealth | null
}

const runtimeModeOptions = [
  { label: 'sync', value: 'sync' },
  { label: 'async', value: 'async' },
]
const RUNTIME_REFRESH_CONCURRENCY = 8

const taskTypeOptions = TASK_TYPES.map((taskType) => ({ label: taskType, value: taskType }))

const deployments = ref<TaskDeploymentInstance[]>([])
const deploymentEvents = ref<TaskDeploymentProcessEvent[]>([])
const sortedDeploymentEvents = computed(() => [...deploymentEvents.value].sort(compareDeploymentEventsNewestFirst))
const loading = ref(false)
const creating = ref(false)
const eventsLoading = ref(false)
const errorMessage = ref<string | null>(null)
const lastCreatedDeployment = ref<TaskDeploymentInstance | null>(null)
const runtimeSnapshotsByDeployment = ref<Record<string, DeploymentRuntimeSnapshot>>({})
const runningActionByDeployment = ref<Record<string, string>>({})
const selectedDeploymentId = ref('')
const selectedTaskType = ref<ModelTaskType>('detection')
const deploymentSourcePickerOpen = ref(false)
const sourceModelsLoading = ref(false)
const sourceModels = ref<DeploymentSourceModelSummary[]>([])
const selectedSourceModelId = ref('')
const selectedSourceModelDetail = ref<DeploymentSourceModelDetail | null>(null)
const selectedDeploymentSource = ref<DeploymentSourceSelection | null>(null)
const pendingDeleteDeploymentId = ref<string | null>(null)

function compareDeploymentEventsNewestFirst(
  left: TaskDeploymentProcessEvent,
  right: TaskDeploymentProcessEvent,
): number {
  const leftTimestamp = Date.parse(left.created_at)
  const rightTimestamp = Date.parse(right.created_at)
  if (Number.isFinite(leftTimestamp) && Number.isFinite(rightTimestamp) && leftTimestamp !== rightTimestamp) {
    return rightTimestamp - leftTimestamp
  }
  return right.sequence - left.sequence
}

const modelType = ref('')
const modelVersionId = ref('')
const modelBuildId = ref('')
const runtimeProfileId = ref('')
const deviceName = ref('')
const instanceCount = ref(1)
const openvinoPerformanceHint = ref<'latency' | 'throughput' | 'cumulative_throughput' | 'none'>('latency')
const openvinoInferenceNumThreads = ref(1)
const openvinoNumStreams = ref(1)
const openvinoNumRequestsMode = ref<'auto' | 'manual'>('auto')
const openvinoNumRequests = ref(1)
const openvinoSchedulingCoreType = ref<'auto' | 'any_core' | 'pcore_only' | 'ecore_only'>('auto')
const openvinoHyperThreading = ref<'auto' | 'true' | 'false'>('auto')
const openvinoCpuPinning = ref<'auto' | 'true' | 'false'>('auto')
const openvinoInferencePrecision = ref<'auto' | 'f32' | 'f16'>('auto')
const openvinoNpuTurbo = ref<'auto' | 'true' | 'false'>('auto')
const openvinoNpuTilesMode = ref<'auto' | 'manual'>('auto')
const openvinoNpuTiles = ref(1)
const openvinoNpuCompilationModeParams = ref('')
const tensorrtOptimizationProfileIndex = ref(0)
const tensorrtPinnedOutput = ref<'auto' | 'true' | 'false'>('auto')
const keepWarmEnabled = ref<'true' | 'false'>('false')
const keepWarmIntervalSeconds = ref(0.1)
const runtimeCapabilities = ref<DeploymentRuntimeCapabilities | null>(null)
const runtimeCapabilitiesLoading = ref(false)
const displayName = ref('')
const runtimeMode = ref<DeploymentRuntimeMode>('sync')

const canWriteModels = computed(() => sessionStore.hasScopes(['models:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)
const selectedDeployment = computed(() => deployments.value.find((item) => item.deployment_instance_id === selectedDeploymentId.value) ?? null)
const selectedRuntimeStatus = computed(() => deploymentRuntimeStatus(selectedDeploymentId.value))
const selectedRuntimeHealth = computed(() => deploymentRuntimeHealth(selectedDeploymentId.value))

function formatRuntimeConfiguration(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2)
}
const pendingDeleteDeployment = computed(() => {
  const deploymentId = pendingDeleteDeploymentId.value
  return deploymentId ? deployments.value.find((item) => item.deployment_instance_id === deploymentId) ?? null : null
})
const deleteDeploymentDialogDetails = computed(() => {
  return pendingDeleteDeployment.value ? t('deploymentOps.messages.deleteConfirm') : ''
})
const deploymentDeviceLabels = computed(() => ({
  automaticDefault: t('deploymentOps.options.automaticDefault'),
  openvinoAutoDefault: t('deploymentOps.options.openvinoAutoDefault'),
  openvinoGpu: t('deploymentOps.options.openvinoGpu'),
}))
const deploymentDeviceOptions = computed(() => buildDeploymentDeviceOptions(
  sessionStore.bootstrap?.devices ?? null,
  selectedDeploymentSource.value?.runtimeBackend ?? '',
  deploymentDeviceLabels.value,
))
const selectedRuntimeBackend = computed(() => selectedDeploymentSource.value?.runtimeBackend.trim().toLowerCase() ?? '')
const isOpenVinoBackend = computed(() => selectedRuntimeBackend.value === 'openvino')
const isTensorRtBackend = computed(() => selectedRuntimeBackend.value === 'tensorrt')
const tensorRtEngineCapabilities = computed(() => parseTensorRtEngineCapabilities(
  selectedDeploymentSource.value?.buildMetadata ?? {},
))
const showTensorRtSingleProfileRange = computed(() => (
  isTensorRtBackend.value
  && tensorRtEngineCapabilities.value?.inputShapeMode === 'dynamic'
  && tensorRtEngineCapabilities.value.optimizationProfiles.length === 1
))
const showTensorRtProfileSelector = computed(() => (
  isTensorRtBackend.value
  && tensorRtEngineCapabilities.value?.inputShapeMode === 'dynamic'
  && tensorRtEngineCapabilities.value.optimizationProfiles.length > 1
))
const tensorRtSingleProfileRangeLines = computed(() => {
  const profile = tensorRtEngineCapabilities.value?.optimizationProfiles[0]
  return profile ? formatTensorRtProfileRangeLines(profile) : []
})
const tensorRtOptimizationProfileOptions = computed(() => (
  tensorRtEngineCapabilities.value?.optimizationProfiles.map((profile) => ({
    label: t('deploymentOps.runtimeConfig.tensorrtProfileIndex', {
      index: profile.index,
    }),
    value: profile.index,
    description: formatTensorRtProfileRangeLines(profile).join(' · '),
  })) ?? []
))
const openvinoDeviceKind = computed<'cpu' | 'gpu' | 'npu' | 'auto'>(() => {
  const device = deviceName.value.trim().toLowerCase()
  if (device.startsWith('cpu')) return 'cpu'
  if (device.startsWith('gpu')) return 'gpu'
  if (device.startsWith('npu')) return 'npu'
  return 'auto'
})
const openvinoPerformanceHintOptions = computed(() => {
  const options = [
    { label: t('deploymentOps.options.lowestLatency'), value: 'latency' },
    { label: t('deploymentOps.options.maximumThroughput'), value: 'throughput' },
  ]
  if (openvinoDeviceKind.value === 'auto') {
    options.push({
      label: t('deploymentOps.options.cumulativeThroughput'),
      value: 'cumulative_throughput',
    })
  }
  options.push({
    label: t('deploymentOps.options.openvinoRuntimeDefault'),
    value: 'none',
  })
  return options
})
const openvinoSchedulingCoreTypeOptions = computed(() => [
  { label: t('deploymentOps.options.automatic'), value: 'auto' },
  { label: t('deploymentOps.options.anyCore'), value: 'any_core' },
  { label: t('deploymentOps.options.pCoreOnly'), value: 'pcore_only' },
  { label: t('deploymentOps.options.eCoreOnly'), value: 'ecore_only' },
])
const autoBooleanOptions = computed(() => [
  { label: t('deploymentOps.options.automatic'), value: 'auto' },
  { label: t('deploymentOps.options.enabled'), value: 'true' },
  { label: t('deploymentOps.options.disabled'), value: 'false' },
])
const serviceDefaultBooleanOptions = computed(() => [
  { label: t('deploymentOps.options.serviceDefault'), value: 'auto' },
  { label: t('deploymentOps.options.enabled'), value: 'true' },
  { label: t('deploymentOps.options.disabled'), value: 'false' },
])
const enabledDisabledOptions = computed(() => [
  { label: t('deploymentOps.options.disabled'), value: 'false' },
  { label: t('deploymentOps.options.enabled'), value: 'true' },
])
const openvinoInferencePrecisionOptions = computed(() => [
  { label: t('deploymentOps.options.automaticRecommended'), value: 'auto' },
  { label: 'FP16', value: 'f16' },
  ...(openvinoDeviceKind.value === 'gpu' ? [{ label: 'FP32', value: 'f32' }] : []),
])
const openvinoNumRequestsModeOptions = computed(() => [
  { label: t('deploymentOps.options.automaticRecommended'), value: 'auto' },
  { label: t('deploymentOps.options.manual'), value: 'manual' },
])
const autoManualOptions = computed(() => [
  { label: t('deploymentOps.options.automatic'), value: 'auto' },
  { label: t('deploymentOps.options.manual'), value: 'manual' },
])
const openvinoMaxInferenceThreads = computed(() => normalizePositiveInteger(
  runtimeCapabilities.value?.hardware.cpu_physical_core_count,
  1,
))
const openvinoInferenceThreadOptions = computed(() => Array.from(
  { length: openvinoMaxInferenceThreads.value },
  (_, index) => ({ label: String(index + 1), value: index + 1 }),
))
const openvinoNpuMaxTiles = computed(() => {
  const value = runtimeCapabilities.value?.read_only_properties.npu_max_tiles
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})
const runtimeCapabilityWarnings = computed(() => runtimeCapabilities.value?.warnings ?? [])

let skipNextRuntimeModeRefresh = false
let runtimeRefreshSequence = 0
let sourceModelLoadSequence = 0
let sourceModelDetailSequence = 0
let runtimeCapabilityLoadSequence = 0
const runtimeRefreshTokenByDeployment = new Map<string, number>()

onMounted(async () => {
  void sessionStore.ensureDeviceBootstrap()
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  await refreshPage()
})

watch(runtimeMode, () => {
  if (skipNextRuntimeModeRefresh) {
    skipNextRuntimeModeRefresh = false
    return
  }
  clearRuntimeSnapshots()
  void refreshRuntimeSnapshotsAndEvents()
})

watch(selectedTaskType, () => {
  sourceModelDetailSequence += 1
  if (deploymentSourcePickerOpen.value) {
    void loadDeploymentSourceModels()
  }
})

watch(deploymentDeviceOptions, (options) => {
  if (!options.some((option) => option.value === deviceName.value)) {
    deviceName.value = options[0]?.value ?? ''
  }
})

watch([selectedRuntimeBackend, deviceName], () => {
  void loadRuntimeCapabilities()
})

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function setRuntimeMode(value: SelectValue): void {
  runtimeMode.value = selectValueToString(value) === 'async' ? 'async' : 'sync'
}

function setTaskType(value: SelectValue): void {
  const normalized = selectValueToString(value)
  if (['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(normalized)) {
    selectedTaskType.value = normalized as ModelTaskType
  }
}

function setDeviceName(value: SelectValue): void {
  deviceName.value = selectValueToString(value)
}

function setOpenvinoPerformanceHint(value: SelectValue): void {
  const normalized = selectValueToString(value)
  if (['latency', 'throughput', 'cumulative_throughput', 'none'].includes(normalized)) {
    openvinoPerformanceHint.value = normalized as typeof openvinoPerformanceHint.value
  }
}

function setOpenvinoInferenceNumThreads(value: SelectValue): void {
  openvinoInferenceNumThreads.value = normalizePositiveInteger(
    value,
    openvinoInferenceNumThreads.value,
    openvinoMaxInferenceThreads.value,
  )
}

function setOpenvinoSchedulingCoreType(value: SelectValue): void {
  const normalized = selectValueToString(value)
  if (['auto', 'any_core', 'pcore_only', 'ecore_only'].includes(normalized)) {
    openvinoSchedulingCoreType.value = normalized as typeof openvinoSchedulingCoreType.value
  }
}

function setAutoBoolean(
  value: SelectValue,
  assign: (normalized: 'auto' | 'true' | 'false') => void,
): void {
  const normalized = selectValueToString(value)
  if (normalized === 'auto' || normalized === 'true' || normalized === 'false') {
    assign(normalized)
  }
}

function setOpenvinoHyperThreading(value: SelectValue): void {
  setAutoBoolean(value, (normalized) => {
    openvinoHyperThreading.value = normalized
  })
}

function setOpenvinoCpuPinning(value: SelectValue): void {
  setAutoBoolean(value, (normalized) => {
    openvinoCpuPinning.value = normalized
  })
}

function setOpenvinoNumRequestsMode(value: SelectValue): void {
  openvinoNumRequestsMode.value = selectValueToString(value) === 'manual' ? 'manual' : 'auto'
}

function setOpenvinoInferencePrecision(value: SelectValue): void {
  const normalized = selectValueToString(value)
  if (normalized === 'auto' || normalized === 'f16' || normalized === 'f32') {
    openvinoInferencePrecision.value = normalized
  }
}

function setOpenvinoNpuTurbo(value: SelectValue): void {
  setAutoBoolean(value, (normalized) => {
    openvinoNpuTurbo.value = normalized
  })
}

function setOpenvinoNpuTilesMode(value: SelectValue): void {
  openvinoNpuTilesMode.value = selectValueToString(value) === 'manual' ? 'manual' : 'auto'
}

function setTensorrtPinnedOutput(value: SelectValue): void {
  setAutoBoolean(value, (normalized) => {
    tensorrtPinnedOutput.value = normalized
  })
}

function setTensorrtOptimizationProfileIndex(value: SelectValue): void {
  const parsed = Number(value)
  const validIndices = tensorRtEngineCapabilities.value?.optimizationProfiles.map(
    (profile) => profile.index,
  ) ?? []
  tensorrtOptimizationProfileIndex.value = validIndices.includes(parsed) ? parsed : 0
}

function setKeepWarmEnabled(value: SelectValue): void {
  keepWarmEnabled.value = selectValueToString(value) === 'true' ? 'true' : 'false'
}

function supportedRuntimeField(fieldName: string): boolean {
  const capabilities = runtimeCapabilities.value
  return capabilities?.supported_backend_fields.includes(fieldName) ?? false
}

async function loadRuntimeCapabilities(): Promise<void> {
  const loadSequence = ++runtimeCapabilityLoadSequence
  const backend = selectedRuntimeBackend.value
  const device = deviceName.value.trim()
  runtimeCapabilities.value = null
  if (!backend || !device) return
  runtimeCapabilitiesLoading.value = true
  try {
    const capabilities = await getDeploymentRuntimeCapabilities(backend, device)
    if (loadSequence !== runtimeCapabilityLoadSequence) return
    runtimeCapabilities.value = capabilities
    applyRuntimeCapabilityDefaults(capabilities)
  } catch (error) {
    if (loadSequence !== runtimeCapabilityLoadSequence) return
    runtimeCapabilities.value = null
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.capabilitiesFailed')
  } finally {
    if (loadSequence === runtimeCapabilityLoadSequence) {
      runtimeCapabilitiesLoading.value = false
    }
  }
}

function applyRuntimeCapabilityDefaults(capabilities: DeploymentRuntimeCapabilities): void {
  const configuration = capabilities.default_runtime_configuration
  instanceCount.value = configuration.execution.instance_count
  keepWarmEnabled.value = configuration.lifecycle.keep_warm_enabled === true ? 'true' : 'false'
  keepWarmIntervalSeconds.value = configuration.lifecycle.keep_warm_interval_seconds ?? 0.1
  normalizeKeepWarmIntervalSeconds()
  const options = configuration.backend_options
  if (options.kind === 'openvino-cpu') {
    openvinoPerformanceHint.value = options.performance_hint
    openvinoInferenceNumThreads.value = normalizePositiveInteger(
      options.inference_num_threads,
      openvinoMaxInferenceThreads.value,
      openvinoMaxInferenceThreads.value,
    )
    openvinoNumStreams.value = normalizePositiveInteger(options.num_streams, 1)
    openvinoSchedulingCoreType.value = options.scheduling_core_type
    openvinoHyperThreading.value = formatAutoBoolean(options.enable_hyper_threading)
    openvinoCpuPinning.value = formatAutoBoolean(options.enable_cpu_pinning)
  } else if (options.kind === 'openvino-gpu') {
    openvinoPerformanceHint.value = options.performance_hint
    openvinoNumStreams.value = normalizePositiveInteger(options.num_streams, 1)
    applyOpenvinoNumRequestsDefault(options.num_requests)
    openvinoInferencePrecision.value = options.inference_precision
  } else if (options.kind === 'openvino-npu') {
    openvinoPerformanceHint.value = options.performance_hint
    applyOpenvinoNumRequestsDefault(options.num_requests)
    openvinoInferencePrecision.value = options.inference_precision
    openvinoNpuTurbo.value = formatAutoBoolean(options.turbo)
    applyOpenvinoNpuTilesDefault(options.tiles)
    openvinoNpuCompilationModeParams.value = options.compilation_mode_params ?? ''
  } else if (options.kind === 'openvino-auto') {
    openvinoPerformanceHint.value = options.performance_hint
    applyOpenvinoNumRequestsDefault(options.num_requests)
  } else if (options.kind === 'tensorrt') {
    setTensorrtOptimizationProfileIndex(options.optimization_profile_index)
    tensorrtPinnedOutput.value = options.pinned_output_buffer_enabled === null
      ? 'auto'
      : options.pinned_output_buffer_enabled
        ? 'true'
        : 'false'
  }
}

function formatAutoBoolean(value: boolean | 'auto'): 'auto' | 'true' | 'false' {
  return value === 'auto' ? 'auto' : value ? 'true' : 'false'
}

function normalizePositiveInteger(value: unknown, fallback: number, maximum?: number): number {
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < 1) return fallback
  return maximum === undefined ? parsed : Math.min(parsed, maximum)
}

function normalizeInstanceCount(): void {
  instanceCount.value = normalizePositiveInteger(instanceCount.value, 1, 64)
}

function normalizeOpenvinoNumStreams(): void {
  openvinoNumStreams.value = normalizePositiveInteger(openvinoNumStreams.value, 1)
}

function normalizeOpenvinoNumRequests(): void {
  openvinoNumRequests.value = normalizePositiveInteger(openvinoNumRequests.value, 1)
}

function normalizeOpenvinoNpuTiles(): void {
  openvinoNpuTiles.value = normalizePositiveInteger(
    openvinoNpuTiles.value,
    1,
    openvinoNpuMaxTiles.value ?? undefined,
  )
}

function normalizeKeepWarmIntervalSeconds(): void {
  const parsed = Number(keepWarmIntervalSeconds.value)
  keepWarmIntervalSeconds.value = Number.isFinite(parsed) && parsed >= 0.01
    ? parsed
    : 0.1
}

function applyOpenvinoNumRequestsDefault(value: number | 'auto'): void {
  openvinoNumRequestsMode.value = value === 'auto' ? 'auto' : 'manual'
  openvinoNumRequests.value = value === 'auto' ? 1 : normalizePositiveInteger(value, 1)
}

function applyOpenvinoNpuTilesDefault(value: number | 'auto'): void {
  openvinoNpuTilesMode.value = value === 'auto' ? 'auto' : 'manual'
  openvinoNpuTiles.value = value === 'auto'
    ? 1
    : normalizePositiveInteger(value, 1, openvinoNpuMaxTiles.value ?? undefined)
}

function parseAutoBoolean(value: 'auto' | 'true' | 'false'): boolean | 'auto' {
  if (value === 'auto') return 'auto'
  return value === 'true'
}

function buildBackendOptions(): DeploymentBackendOptions {
  if (isTensorRtBackend.value) {
    return {
      kind: 'tensorrt',
      optimization_profile_index: resolveTensorRtOptimizationProfileIndex(),
      pinned_output_buffer_enabled: tensorrtPinnedOutput.value === 'auto'
        ? null
        : tensorrtPinnedOutput.value === 'true',
      pinned_output_buffer_max_bytes: null,
    }
  }
  if (!isOpenVinoBackend.value) return { kind: 'default' }
  if (openvinoDeviceKind.value === 'cpu') {
    return {
      kind: 'openvino-cpu',
      performance_hint: openvinoPerformanceHint.value,
      inference_num_threads: normalizePositiveInteger(
        openvinoInferenceNumThreads.value,
        1,
        openvinoMaxInferenceThreads.value,
      ),
      num_streams: normalizePositiveInteger(openvinoNumStreams.value, 1),
      scheduling_core_type: openvinoSchedulingCoreType.value,
      enable_hyper_threading: parseAutoBoolean(openvinoHyperThreading.value),
      enable_cpu_pinning: parseAutoBoolean(openvinoCpuPinning.value),
    }
  }
  if (openvinoDeviceKind.value === 'gpu') {
    return {
      kind: 'openvino-gpu',
      performance_hint: openvinoPerformanceHint.value,
      num_streams: normalizePositiveInteger(openvinoNumStreams.value, 1),
      num_requests: openvinoNumRequestsMode.value === 'auto'
        ? 'auto'
        : normalizePositiveInteger(openvinoNumRequests.value, 1),
      inference_precision: openvinoInferencePrecision.value,
      queue_priority: 'auto',
      queue_throttle: 'auto',
    }
  }
  if (openvinoDeviceKind.value === 'npu') {
    return {
      kind: 'openvino-npu',
      performance_hint: openvinoPerformanceHint.value,
      num_requests: openvinoNumRequestsMode.value === 'auto'
        ? 'auto'
        : normalizePositiveInteger(openvinoNumRequests.value, 1),
      inference_precision: openvinoInferencePrecision.value === 'f32' ? 'auto' : openvinoInferencePrecision.value,
      turbo: parseAutoBoolean(openvinoNpuTurbo.value),
      tiles: openvinoNpuTilesMode.value === 'auto'
        ? 'auto'
        : normalizePositiveInteger(
            openvinoNpuTiles.value,
            1,
            openvinoNpuMaxTiles.value ?? undefined,
          ),
      compilation_mode_params: openvinoNpuCompilationModeParams.value.trim() || null,
    }
  }
  return {
    kind: 'openvino-auto',
    performance_hint: openvinoPerformanceHint.value,
    num_requests: openvinoNumRequestsMode.value === 'auto'
      ? 'auto'
      : normalizePositiveInteger(openvinoNumRequests.value, 1),
  }
}

function buildRuntimeConfiguration(): DeploymentRuntimeConfiguration {
  normalizeKeepWarmIntervalSeconds()
  return {
    execution: {
      instance_count: normalizePositiveInteger(instanceCount.value, 1, 64),
      isolation_level: 'session',
      overflow_policy: 'reject',
      performance_goal: runtimeCapabilities.value?.default_runtime_configuration.execution.performance_goal ?? 'latency',
    },
    lifecycle: {
      warmup_dummy_inference_count: null,
      warmup_dummy_image_size: null,
      keep_warm_enabled: keepWarmEnabled.value === 'true',
      keep_warm_interval_seconds: keepWarmIntervalSeconds.value,
    },
    backend_options: buildBackendOptions(),
  }
}

function clearRuntimeSnapshots(): void {
  if (Object.keys(runtimeSnapshotsByDeployment.value).length === 0) {
    runtimeRefreshTokenByDeployment.clear()
    return
  }
  runtimeSnapshotsByDeployment.value = {}
  runtimeRefreshTokenByDeployment.clear()
}

function setRuntimeModeWithoutRefresh(mode: DeploymentRuntimeMode): void {
  if (runtimeMode.value === mode) return
  skipNextRuntimeModeRefresh = true
  clearRuntimeSnapshots()
  runtimeMode.value = mode
}

async function openDeploymentSourcePicker(): Promise<void> {
  deploymentSourcePickerOpen.value = true
  await loadDeploymentSourceModels()
}

async function loadDeploymentSourceModels(): Promise<void> {
  const loadSequence = ++sourceModelLoadSequence
  sourceModelDetailSequence += 1
  const taskType = selectedTaskType.value
  sourceModelsLoading.value = true
  errorMessage.value = null
  try {
    const models = await listDeploymentSourceModels(selectedProjectId.value, taskType)
    if (loadSequence !== sourceModelLoadSequence) return
    const candidateModelIds = [
      selectedSourceModelId.value,
      selectedDeploymentSource.value?.taskType === taskType ? selectedDeploymentSource.value.modelId : '',
      models[0]?.model_id ?? '',
    ]
    const preferredModelId = candidateModelIds.find((modelId) => models.some((model) => model.model_id === modelId)) ?? ''
    const modelDetail = preferredModelId
      ? await getDeploymentSourceModelDetail(selectedProjectId.value, preferredModelId)
      : null
    if (loadSequence !== sourceModelLoadSequence) return
    sourceModels.value = models
    selectedSourceModelId.value = preferredModelId
    selectedSourceModelDetail.value = modelDetail
  } catch (error) {
    if (loadSequence !== sourceModelLoadSequence) return
    sourceModels.value = []
    selectedSourceModelId.value = ''
    selectedSourceModelDetail.value = null
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.sourceModelsFailed')
  } finally {
    if (loadSequence === sourceModelLoadSequence) {
      sourceModelsLoading.value = false
    }
  }
}

async function selectDeploymentSourceModel(modelId: string): Promise<void> {
  const detailSequence = ++sourceModelDetailSequence
  selectedSourceModelId.value = modelId
  errorMessage.value = null
  try {
    const modelDetail = await getDeploymentSourceModelDetail(selectedProjectId.value, modelId)
    if (detailSequence !== sourceModelDetailSequence || selectedSourceModelId.value !== modelId) return
    selectedSourceModelDetail.value = modelDetail
  } catch (error) {
    if (detailSequence !== sourceModelDetailSequence || selectedSourceModelId.value !== modelId) return
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.sourceModelDetailFailed')
  }
}

function applyDeploymentSource(selection: DeploymentSourceSelection): void {
  selectedDeploymentSource.value = selection
  tensorrtOptimizationProfileIndex.value = 0
  selectedSourceModelId.value = selection.modelId
  modelType.value = selection.modelType
  modelVersionId.value = selection.modelVersionId
  modelBuildId.value = selection.modelBuildId
  runtimeProfileId.value = selection.runtimeProfileId
  selectedTaskType.value = selection.taskType
  const deviceOptions = buildDeploymentDeviceOptions(
    sessionStore.bootstrap?.devices ?? null,
    selection.runtimeBackend,
    deploymentDeviceLabels.value,
  )
  if (!deviceOptions.some((option) => option.value === deviceName.value)) {
    deviceName.value = deviceOptions[0]?.value ?? ''
  }
  if (!displayName.value.trim()) {
    const sourceLabel = selection.modelBuildId || selection.modelVersionId
    displayName.value = `${selection.modelName} ${sourceLabel}`
  }
  deploymentSourcePickerOpen.value = false
}

function resolveTensorRtOptimizationProfileIndex(): number {
  if (!showTensorRtProfileSelector.value) return 0
  const validIndices = tensorRtEngineCapabilities.value?.optimizationProfiles.map(
    (profile) => profile.index,
  ) ?? []
  return validIndices.includes(tensorrtOptimizationProfileIndex.value)
    ? tensorrtOptimizationProfileIndex.value
    : 0
}

function formatTensorRtProfileRangeLines(profile: TensorRtOptimizationProfile): string[] {
  return profile.inputs.map((input) => t(
    'deploymentOps.runtimeConfig.tensorrtProfileInputRange',
    {
      input: input.inputName,
      min: formatTensorRtShape(input.minShape),
      opt: formatTensorRtShape(input.optShape),
      max: formatTensorRtShape(input.maxShape),
    },
  ))
}

function deploymentSourceUnavailableReason(selection: DeploymentSourceSelection): string {
  const runtimeBackend = selection.runtimeBackend.trim().toLowerCase()
  if (runtimeBackend !== 'tensorrt') {
    return ''
  }
  const devices = sessionStore.bootstrap?.devices ?? null
  if (!hasCudaDevice(devices)) {
    return t('deploymentOps.messages.tensorrtCudaUnavailable')
  }
  const tensorrt = readDeviceRecord(devices, 'tensorrt')
  if (tensorrt?.installed !== true) {
    return t('deploymentOps.messages.tensorrtRuntimeUnavailable')
  }
  return ''
}

function readDeviceRecord(
  record: Record<string, unknown> | null | undefined,
  key: string,
): Record<string, unknown> | null {
  const value = record?.[key]
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('running') || normalized.includes('active') || normalized.includes('ready')) return 'success'
  if (normalized.includes('crash') || normalized.includes('error') || normalized.includes('fail')) return 'danger'
  if (normalized.includes('start') || normalized.includes('created') || normalized.includes('stopped')) return 'warning'
  return 'neutral'
}

function createEmptyRuntimeSnapshot(): DeploymentRuntimeSnapshot {
  return {
    status: null,
    health: null,
  }
}

function deploymentRuntimeSnapshot(deploymentId: string): DeploymentRuntimeSnapshot | null {
  if (!deploymentId) return null
  return runtimeSnapshotsByDeployment.value[deploymentId] ?? null
}

function deploymentRuntimeStatus(deploymentId: string): TaskDeploymentProcessStatus | null {
  return deploymentRuntimeSnapshot(deploymentId)?.status ?? null
}

function deploymentRuntimeHealth(deploymentId: string): TaskDeploymentRuntimeHealth | null {
  return deploymentRuntimeSnapshot(deploymentId)?.health ?? null
}

function runtimeSnapshotValueEquals(left: unknown, right: unknown): boolean {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null)
}

function setDeploymentRuntimeSnapshot(
  deploymentId: string,
  patch: Partial<DeploymentRuntimeSnapshot>,
): void {
  if (!deploymentId) return
  const current = runtimeSnapshotsByDeployment.value[deploymentId] ?? createEmptyRuntimeSnapshot()
  const next: DeploymentRuntimeSnapshot = {
    status: patch.status === undefined ? current.status : patch.status,
    health: patch.health === undefined ? current.health : patch.health,
  }
  if (
    runtimeSnapshotValueEquals(current.status, next.status)
    && runtimeSnapshotValueEquals(current.health, next.health)
  ) {
    return
  }
  runtimeSnapshotsByDeployment.value = {
    ...runtimeSnapshotsByDeployment.value,
    [deploymentId]: next,
  }
}

function commitDeploymentRuntimeStatus(
  deploymentId: string,
  status: TaskDeploymentProcessStatus | null,
): void {
  setDeploymentRuntimeSnapshot(deploymentId, { status })
}

function commitDeploymentRuntimeHealth(
  deploymentId: string,
  health: TaskDeploymentRuntimeHealth | null,
): void {
  setDeploymentRuntimeSnapshot(deploymentId, {
    status: health,
    health,
  })
}

function commitDeploymentRuntimeResult(
  deploymentId: string,
  status: TaskDeploymentProcessStatus | null,
  health: TaskDeploymentRuntimeHealth | null,
): void {
  setDeploymentRuntimeSnapshot(deploymentId, {
    status: health ?? status,
    health,
  })
}

function deleteDeploymentRuntimeSnapshot(deploymentId: string): void {
  if (!runtimeSnapshotsByDeployment.value[deploymentId]) return
  const nextSnapshots = { ...runtimeSnapshotsByDeployment.value }
  delete nextSnapshots[deploymentId]
  runtimeSnapshotsByDeployment.value = nextSnapshots
  runtimeRefreshTokenByDeployment.delete(deploymentId)
}

function beginDeploymentRuntimeRefresh(deploymentId: string): number {
  const token = ++runtimeRefreshSequence
  runtimeRefreshTokenByDeployment.set(deploymentId, token)
  return token
}

function isCurrentDeploymentRuntimeRefresh(deploymentId: string, token: number): boolean {
  return runtimeRefreshTokenByDeployment.get(deploymentId) === token
}

function finishDeploymentRuntimeRefresh(deploymentId: string, token: number): void {
  if (!isCurrentDeploymentRuntimeRefresh(deploymentId, token)) return
  runtimeRefreshTokenByDeployment.delete(deploymentId)
}

function normalizeDeploymentRuntimeMode(value: string | null | undefined): DeploymentRuntimeMode {
  return String(value ?? '').trim().toLowerCase() === 'async' ? 'async' : 'sync'
}

function normalizeModelTaskType(value: string | null | undefined): ModelTaskType {
  const normalized = String(value ?? '').trim().toLowerCase()
  return TASK_TYPES.includes(normalized as ModelTaskType) ? normalized as ModelTaskType : 'detection'
}

function taskTypeForDeployment(item: TaskDeploymentInstance): ModelTaskType {
  return normalizeModelTaskType(item.task_type)
}

function runtimeProcessTone(item: TaskDeploymentInstance): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const processState = deploymentRuntimeStatus(item.deployment_instance_id)?.process_state
  if (!processState) return 'neutral'
  return statusTone(processState)
}

function runtimeProcessLabel(item: TaskDeploymentInstance): string {
  return deploymentRuntimeStatus(item.deployment_instance_id)?.process_state || t('deploymentOps.states.notInspected')
}

function setDeploymentRunningAction(deploymentId: string, action: string | null): void {
  const nextActions = { ...runningActionByDeployment.value }
  if (action) {
    nextActions[deploymentId] = action
  } else {
    delete nextActions[deploymentId]
  }
  runningActionByDeployment.value = nextActions
}

function deploymentRunningAction(deploymentId: string): string | null {
  return runningActionByDeployment.value[deploymentId] ?? null
}

function isDeleteActionBusy(deploymentId: string): boolean {
  return deploymentRunningAction(deploymentId) === 'delete'
}

function isRuntimeActionBusy(item: TaskDeploymentInstance): boolean {
  return deploymentRunningAction(item.deployment_instance_id) !== null
}

function canStartDeployment(item: TaskDeploymentInstance): boolean {
  if (!canWriteModels.value || isRuntimeActionBusy(item)) return false
  const processState = String(deploymentRuntimeStatus(item.deployment_instance_id)?.process_state ?? '').toLowerCase()
  return processState !== 'running'
}

function canStopDeployment(item: TaskDeploymentInstance): boolean {
  if (!canWriteModels.value || isRuntimeActionBusy(item)) return false
  const processState = String(deploymentRuntimeStatus(item.deployment_instance_id)?.process_state ?? item.status ?? '').toLowerCase()
  return processState.includes('running') || processState.includes('starting') || processState.includes('ready')
}

function canDeleteDeployment(item: TaskDeploymentInstance): boolean {
  if (!canWriteModels.value || isRuntimeActionBusy(item)) return false
  const status = deploymentRuntimeStatus(item.deployment_instance_id)
  if (!status) return true
  return status.desired_state === 'stopped' && status.process_state === 'stopped'
}

function deleteButtonTitle(item: TaskDeploymentInstance): string {
  if (!canWriteModels.value) return t('deploymentOps.messages.writePermissionRequired')
  if (deploymentRunningAction(item.deployment_instance_id) !== null) return t('deploymentOps.messages.actionInProgress')
  const status = deploymentRuntimeStatus(item.deployment_instance_id)
  if (status && (status.desired_state !== 'stopped' || status.process_state !== 'stopped')) {
    return t('deploymentOps.messages.deleteRequiresStopped')
  }
  return t('deploymentOps.actions.delete')
}

function canWarmupDeployment(item: TaskDeploymentInstance): boolean {
  return canWriteModels.value && !isRuntimeActionBusy(item) && !isDeploymentWarmupComplete(item)
}

function isDeploymentWarmupComplete(item: TaskDeploymentInstance): boolean {
  const health = deploymentRuntimeHealth(item.deployment_instance_id)
  return health ? isRuntimeHealthWarmupComplete(health, getDeploymentInstanceCount(item)) : false
}

function isRuntimeHealthWarmupComplete(health: TaskDeploymentRuntimeHealth, fallbackInstanceCount: number): boolean {
  const expectedInstanceCount = Math.max(0, Number(health.instance_count || fallbackInstanceCount || 0))
  const warmedInstanceCount = Math.max(0, Number(health.warmed_instance_count || 0))
  const instancesReady = expectedInstanceCount > 0 && warmedInstanceCount >= expectedInstanceCount
  if (!instancesReady) return false
  if (health.keep_warm?.enabled === false) return true
  return health.keep_warm?.activated === true
}

function warmupButtonTitle(item: TaskDeploymentInstance): string {
  if (isDeploymentWarmupComplete(item)) return t('deploymentOps.messages.warmupComplete')
  if (!canWriteModels.value) return t('deploymentOps.messages.writePermissionRequired')
  if (deploymentRunningAction(item.deployment_instance_id) !== null) return t('deploymentOps.messages.actionInProgress')
  return t('deploymentOps.messages.warmupDeployment')
}

function canResetDeployment(item: TaskDeploymentInstance): boolean {
  return canWriteModels.value && !isRuntimeActionBusy(item)
}

function formatRuntimeLabel(item: TaskDeploymentInstance): string {
  const backend = item.runtime_backend || 'pytorch'
  const precision = item.runtime_precision || 'fp32'
  const device = item.device_name ? ` / ${item.device_name}` : ''
  return `${backend} ${precision}${device}`
}

function formatInputSize(inputSize: [number, number] | null | undefined): string {
  if (!Array.isArray(inputSize) || inputSize.length < 2) return '-'
  return `${inputSize[0]} x ${inputSize[1]}`
}

async function refreshPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    deployments.value = await listAllTaskDeployments()
    if (!deployments.value.some((item) => item.deployment_instance_id === selectedDeploymentId.value)) {
      selectedDeploymentId.value = deployments.value[0]?.deployment_instance_id ?? ''
    }
    await refreshRuntimeSnapshotsAndEvents()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function listAllTaskDeployments(): Promise<TaskDeploymentInstance[]> {
  const groups = await Promise.all(
    TASK_TYPES.map(async (taskType) => {
      const items = await listTaskDeployments(taskType, selectedProjectId.value)
      return items.map((item) => ({
        item: {
          ...item,
          task_type: item.task_type || taskType,
        },
        routeTaskType: taskType,
      }))
    }),
  )

  const byDeploymentId = new Map<string, DeploymentListCandidate>()
  for (const candidate of groups.flat()) {
    const existing = byDeploymentId.get(candidate.item.deployment_instance_id)
    if (!existing || shouldPreferDeploymentCandidate(candidate, existing)) {
      byDeploymentId.set(candidate.item.deployment_instance_id, candidate)
    }
  }

  return Array.from(byDeploymentId.values())
    .map((candidate) => candidate.item)
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
}

function shouldPreferDeploymentCandidate(next: DeploymentListCandidate, current: DeploymentListCandidate): boolean {
  const nextMatchesRoute = normalizeModelTaskType(next.item.task_type) === next.routeTaskType
  const currentMatchesRoute = normalizeModelTaskType(current.item.task_type) === current.routeTaskType
  if (nextMatchesRoute !== currentMatchesRoute) return nextMatchesRoute

  const nextHasBuild = Boolean(next.item.model_build_id)
  const currentHasBuild = Boolean(current.item.model_build_id)
  if (nextHasBuild !== currentHasBuild) return nextHasBuild

  return Date.parse(next.item.updated_at) > Date.parse(current.item.updated_at)
}

async function selectDeployment(deploymentId: string): Promise<void> {
  selectedDeploymentId.value = deploymentId
  const deployment = selectedDeployment.value
  await Promise.all([
    deployment ? refreshDeploymentRuntimeSnapshot(deployment, { showError: true }) : Promise.resolve(null),
    loadDeploymentEvents(),
  ])
}

async function loadDeploymentEvents(): Promise<void> {
  const deployment = selectedDeployment.value
  if (!deployment) {
    deploymentEvents.value = []
    return
  }
  eventsLoading.value = true
  errorMessage.value = null
  try {
    deploymentEvents.value = await listTaskDeploymentEvents(
      taskTypeForDeployment(deployment),
      deployment.deployment_instance_id,
      runtimeMode.value,
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.eventsFailed')
  } finally {
    eventsLoading.value = false
  }
}

async function refreshRuntimeSnapshotsAndEvents(): Promise<void> {
  await Promise.all([
    refreshRuntimeSnapshotsForDeployments(deployments.value),
    loadDeploymentEvents(),
  ])
}

async function refreshRuntimeSnapshotsForDeployments(items: TaskDeploymentInstance[]): Promise<void> {
  const failures: string[] = []
  let cursor = 0
  const workerCount = Math.min(RUNTIME_REFRESH_CONCURRENCY, items.length)
  await Promise.all(Array.from({ length: workerCount }, async () => {
    while (cursor < items.length) {
      const item = items[cursor]
      cursor += 1
      const message = await refreshDeploymentRuntimeSnapshot(item)
      if (message) failures.push(message)
    }
  }))
  const failed = failures[0]
  if (failed) {
    errorMessage.value = failed
  }
}

async function refreshDeploymentRuntimeSnapshot(
  deployment: TaskDeploymentInstance,
  options: { showError?: boolean } = {},
): Promise<string | null> {
  const deploymentId = deployment.deployment_instance_id
  const refreshToken = beginDeploymentRuntimeRefresh(deploymentId)
  if (options.showError) {
    errorMessage.value = null
  }
  try {
    const status = await runTaskDeploymentStatusAction(taskTypeForDeployment(deployment), deploymentId, runtimeMode.value, 'status')
    let health: TaskDeploymentRuntimeHealth | null = null
    try {
      health = await runTaskDeploymentHealthAction(taskTypeForDeployment(deployment), deploymentId, runtimeMode.value, 'health')
    } catch {
      health = null
    }
    if (!isCurrentDeploymentRuntimeRefresh(deploymentId, refreshToken)) return null
    commitDeploymentRuntimeResult(deploymentId, status, health)
    return null
  } catch (error) {
    if (!isCurrentDeploymentRuntimeRefresh(deploymentId, refreshToken)) return null
    const message = error instanceof Error ? error.message : t('deploymentOps.messages.actionFailed')
    if (options.showError) {
      errorMessage.value = message
    }
    return message
  } finally {
    finishDeploymentRuntimeRefresh(deploymentId, refreshToken)
  }
}

async function submitDeployment(): Promise<void> {
  if (!selectedDeploymentSource.value || !modelType.value.trim()) {
    errorMessage.value = t('deploymentOps.messages.sourceRequired')
    return
  }
  const unavailableReason = deploymentSourceUnavailableReason(selectedDeploymentSource.value)
  if (unavailableReason) {
    errorMessage.value = unavailableReason
    return
  }
  normalizeInstanceCount()
  if (isOpenVinoBackend.value && openvinoDeviceKind.value !== 'npu') {
    normalizeOpenvinoNumStreams()
  }
  if (isOpenVinoBackend.value && openvinoNumRequestsMode.value === 'manual') {
    normalizeOpenvinoNumRequests()
  }
  if (openvinoDeviceKind.value === 'npu' && openvinoNpuTilesMode.value === 'manual') {
    normalizeOpenvinoNpuTiles()
  }
  creating.value = true
  errorMessage.value = null
  try {
    lastCreatedDeployment.value = await createTaskDeployment({
      taskType: selectedDeploymentSource.value.taskType,
      projectId: selectedProjectId.value,
      modelType: modelType.value.trim(),
      modelVersionId: modelVersionId.value.trim(),
      modelBuildId: modelBuildId.value.trim(),
      runtimeProfileId: runtimeProfileId.value.trim(),
      runtimeBackend: selectedDeploymentSource.value.runtimeBackend.trim(),
      runtimePrecision: selectedDeploymentSource.value.runtimePrecision === 'fp16' ? 'fp16' : 'fp32',
      deviceName: deviceName.value.trim(),
      runtimeConfiguration: buildRuntimeConfiguration(),
      displayName: displayName.value,
    })
    selectedDeploymentId.value = lastCreatedDeployment.value.deployment_instance_id
    await refreshPage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.createFailed')
  } finally {
    creating.value = false
  }
}

async function runStatusAction(deploymentId: string, modeValue: string, action: DeploymentStatusAction): Promise<void> {
  const mode = normalizeDeploymentRuntimeMode(modeValue)
  const deployment = deployments.value.find((item) => item.deployment_instance_id === deploymentId)
  const taskType = deployment ? taskTypeForDeployment(deployment) : selectedTaskType.value
  selectedDeploymentId.value = deploymentId
  setRuntimeModeWithoutRefresh(mode)
  setDeploymentRunningAction(deploymentId, `${mode}:${action}`)
  errorMessage.value = null
  try {
    const status = await runTaskDeploymentStatusAction(taskType, deploymentId, mode, action)
    if (action === 'status') {
      commitDeploymentRuntimeStatus(deploymentId, status)
    } else {
      let health: TaskDeploymentRuntimeHealth | null = null
      try {
        health = await runTaskDeploymentHealthAction(taskType, deploymentId, mode, 'health')
      } catch {
        health = null
      }
      commitDeploymentRuntimeResult(deploymentId, status, health)
    }
    await loadDeploymentEvents()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.actionFailed')
  } finally {
    setDeploymentRunningAction(deploymentId, null)
  }
}

async function runHealthAction(deploymentId: string, modeValue: string, action: DeploymentHealthAction): Promise<void> {
  const mode = normalizeDeploymentRuntimeMode(modeValue)
  const deployment = deployments.value.find((item) => item.deployment_instance_id === deploymentId)
  const taskType = deployment ? taskTypeForDeployment(deployment) : selectedTaskType.value
  selectedDeploymentId.value = deploymentId
  setRuntimeModeWithoutRefresh(mode)
  setDeploymentRunningAction(deploymentId, `${mode}:${action}`)
  errorMessage.value = null
  try {
    if (action === 'warmup') {
      const currentHealth = await loadDeploymentRuntimeHealthBeforeWarmup(taskType, deploymentId, mode)
      if (
        currentHealth
        && isRuntimeHealthWarmupComplete(
          currentHealth,
          deployment ? getDeploymentInstanceCount(deployment) : 0,
        )
      ) {
        await loadDeploymentEvents()
        return
      }
    }
    const health = await runTaskDeploymentHealthAction(taskType, deploymentId, mode, action)
    commitDeploymentRuntimeHealth(deploymentId, health)
    await loadDeploymentEvents()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.actionFailed')
  } finally {
    setDeploymentRunningAction(deploymentId, null)
  }
}

function openDeleteDeploymentDialog(deploymentId: string): void {
  const deployment = deployments.value.find((item) => item.deployment_instance_id === deploymentId)
  if (!deployment || !canDeleteDeployment(deployment)) return
  pendingDeleteDeploymentId.value = deploymentId
}

function closeDeleteDeploymentDialog(): void {
  const deploymentId = pendingDeleteDeployment.value?.deployment_instance_id
  if (deploymentId && isDeleteActionBusy(deploymentId)) return
  pendingDeleteDeploymentId.value = null
}

async function confirmDeleteDeployment(): Promise<void> {
  const deployment = pendingDeleteDeployment.value
  if (!deployment || !canDeleteDeployment(deployment)) return
  const deploymentId = deployment.deployment_instance_id
  const taskType = taskTypeForDeployment(deployment)
  selectedDeploymentId.value = deploymentId
  setDeploymentRunningAction(deploymentId, 'delete')
  errorMessage.value = null
  try {
    await deleteTaskDeployment(taskType, deploymentId)
    deleteDeploymentRuntimeSnapshot(deploymentId)
    deploymentEvents.value = []
    lastCreatedDeployment.value = lastCreatedDeployment.value?.deployment_instance_id === deploymentId
      ? null
      : lastCreatedDeployment.value
    await refreshPage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.deleteFailed')
  } finally {
    setDeploymentRunningAction(deploymentId, null)
    pendingDeleteDeploymentId.value = null
  }
}

async function loadDeploymentRuntimeHealthBeforeWarmup(
  taskType: ModelTaskType,
  deploymentId: string,
  mode: DeploymentRuntimeMode,
): Promise<TaskDeploymentRuntimeHealth | null> {
  try {
    const health = await runTaskDeploymentHealthAction(taskType, deploymentId, mode, 'health')
    commitDeploymentRuntimeHealth(deploymentId, health)
    return health
  } catch {
    return null
  }
}
</script>

<style scoped>
.deployment-source-summary {
  display: grid;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--summary-bg);
}

.deployment-source-summary h3 {
  margin: 0;
}

.deployment-source-summary__grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.deployment-source-summary__grid div {
  padding: 10px;
}

.source-empty-card {
  display: grid;
  gap: 4px;
  min-height: 74px;
  align-content: center;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.source-empty-card span {
  color: var(--muted);
}

.deployment-workspace-grid {
  grid-template-columns: 1fr;
  align-items: start;
}

.deployment-create-panel {
  min-width: 0;
}

.deployment-create-grid {
  gap: 10px;
}

.field-control-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 112px;
  gap: 8px;
  align-items: stretch;
}

.field-control-row > :only-child {
  grid-column: 1 / -1;
}

.deployment-profile-summary {
  display: grid;
  gap: 4px;
  min-height: 34px;
  align-content: center;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-muted);
}

.deployment-profile-summary span {
  color: var(--text);
  font-weight: 500;
}

.deployment-instances-panel,
.deployment-runtime-panel,
.deployment-events-panel {
  min-width: 0;
}

.deployment-instance-list {
  display: grid;
  gap: 10px;
}

.deployment-instance-card {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  cursor: pointer;
}

.deployment-instance-card--selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent);
}

.deployment-instance-card__header {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: flex-start;
}

.deployment-instance-card__title {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.deployment-instance-card__title strong,
.deployment-instance-card__title span,
.deployment-instance-card__details strong,
.deployment-instance-card__details small {
  overflow-wrap: anywhere;
}

.deployment-instance-card__title span,
.deployment-instance-card__details span,
.deployment-instance-card__details small {
  color: var(--muted);
}

.deployment-instance-card__states {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.deployment-instance-card__details {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.deployment-instance-card__details div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.deployment-instance-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.deployment-runtime-grid {
  grid-template-columns: 1fr;
  align-items: start;
}

.deployment-runtime-summary {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.deployment-runtime-summary div {
  padding: 10px;
}

.runtime-configuration-warnings {
  display: grid;
  gap: 8px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--warning-border, #d8a52d);
  border-radius: 8px;
  background: var(--warning-surface, #fff8df);
}

.runtime-configuration-warnings ul {
  margin: 0;
  padding-left: 20px;
}

.runtime-configuration-diagnostics {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.runtime-configuration-diagnostics details {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.runtime-configuration-diagnostics summary {
  padding: 10px 12px;
  cursor: pointer;
  font-weight: 600;
}

.runtime-configuration-diagnostics pre {
  max-height: 320px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border-top: 1px solid var(--line);
  font-size: 12px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.deployment-events-panel .event-timeline li {
  grid-template-columns: 148px minmax(180px, max-content) minmax(0, 1fr);
  gap: 14px;
  padding: 8px 0;
}

.deployment-events-panel .event-timeline time,
.deployment-events-panel .event-timeline strong,
.deployment-events-panel .event-timeline span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  overflow-wrap: normal;
}

.deployment-events-panel .event-timeline strong {
  max-width: 260px;
}

@media (max-width: 900px) {
  .deployment-workspace-grid,
  .deployment-runtime-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .deployment-instance-card__header {
    display: grid;
  }

  .deployment-instance-card__states {
    justify-content: flex-start;
  }

  .deployment-instance-card__details {
    grid-template-columns: 1fr;
  }

  .deployment-source-summary__grid,
  .deployment-runtime-summary,
  .deployment-events-panel .event-timeline li {
    grid-template-columns: 1fr;
  }

  .deployment-events-panel .event-timeline time,
  .deployment-events-panel .event-timeline strong,
  .deployment-events-panel .event-timeline span {
    white-space: normal;
  }
}
</style>
