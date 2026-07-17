<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('deploymentOps.kicker') }}</p>
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
          <p class="page-kicker">{{ t('deploymentOps.createKicker') }}</p>
          <h2>{{ t('deploymentOps.createTitle') }}</h2>
        </div>
        <section class="deployment-source-summary">
          <div class="section-heading">
            <div>
              <p class="page-kicker">SOURCE</p>
              <h3>部署来源模型</h3>
            </div>
            <Button type="button" variant="secondary" :disabled="sourceModelsLoading" @click="openDeploymentSourcePicker">
              {{ selectedDeploymentSource ? '更换来源' : '选择部署来源' }}
            </Button>
          </div>
          <div v-if="selectedDeploymentSource" class="summary-grid deployment-source-summary__grid">
            <div>
              <span>模型</span>
              <strong>{{ selectedDeploymentSource.modelName }}</strong>
            </div>
            <div>
              <span>model_type</span>
              <strong>{{ selectedDeploymentSource.modelType }}</strong>
            </div>
            <div>
              <span>来源类型</span>
              <strong>{{ selectedDeploymentSource.sourceKind === 'model-build' ? 'ModelBuild' : 'ModelVersion' }}</strong>
            </div>
            <div>
              <span>来源 id</span>
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
              <span>Runtime precision</span>
              <strong>{{ selectedDeploymentSource.runtimePrecision || '-' }}</strong>
            </div>
            <div>
              <span>RuntimeProfile id</span>
              <strong>{{ selectedDeploymentSource.runtimeProfileId || '-' }}</strong>
            </div>
          </div>
          <div v-else class="source-empty-card">
            <strong>尚未选择部署来源模型</strong>
            <span>先选择训练完成的 ModelVersion 或转换完成的 ModelBuild，再创建部署实例。</span>
          </div>
        </section>
        <div class="form-grid deployment-create-grid">
          <label class="field">
            <span>{{ t('deploymentOps.fields.deviceName') }}</span>
            <SelectField :model-value="deviceName" :options="deploymentDeviceOptions" @update:model-value="setDeviceName" />
          </label>
          <label class="field">
            <span>{{ t('deploymentOps.fields.instanceCount') }}</span>
            <input v-model.number="instanceCount" type="number" min="1" />
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
            <p class="page-kicker">{{ t('deploymentOps.listKicker') }}</p>
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
                <span>模型</span>
                <strong>{{ item.model_name }}</strong>
                <small>{{ item.model_version_id }} / {{ item.model_build_id || '-' }}</small>
              </div>
              <div>
                <span>Runtime</span>
                <strong>{{ formatRuntimeLabel(item) }}</strong>
                <small>{{ item.runtime_execution_mode }} · {{ item.source_kind }}</small>
              </div>
              <div>
                <span>实例</span>
                <strong>{{ item.instance_count }}</strong>
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
      :message="deleteDeploymentDialogMessage"
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
            <p class="page-kicker">{{ t('deploymentOps.runtimeKicker') }}</p>
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
            <strong>{{ selectedRuntimeStatus?.process_state || '未探测' }}</strong>
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
      </section>

      <section class="resource-section deployment-events-panel">
        <div class="section-heading">
          <div>
            <p class="page-kicker">{{ t('deploymentOps.eventsKicker') }}</p>
            <h2>{{ t('deploymentOps.eventsTitle') }}</h2>
            <p class="page-description">{{ selectedDeployment.deployment_instance_id }}</p>
          </div>
        </div>
        <EmptyState v-if="!eventsLoading && deploymentEvents.length === 0" :title="t('deploymentOps.emptyEventsTitle')" :description="t('deploymentOps.emptyEventsDescription')" />
        <ol v-else class="event-timeline event-timeline--compact">
          <li v-for="event in deploymentEvents" :key="`${event.runtime_mode}-${event.sequence}`">
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
  listTaskDeploymentEvents,
  listTaskDeployments,
  runTaskDeploymentHealthAction,
  runTaskDeploymentStatusAction,
  type DeploymentHealthAction,
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

const modelType = ref('')
const modelVersionId = ref('')
const modelBuildId = ref('')
const runtimeProfileId = ref('')
const deviceName = ref('')
const instanceCount = ref(1)
const displayName = ref('')
const runtimeMode = ref<DeploymentRuntimeMode>('sync')

const canWriteModels = computed(() => sessionStore.hasScopes(['models:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)
const selectedDeployment = computed(() => deployments.value.find((item) => item.deployment_instance_id === selectedDeploymentId.value) ?? null)
const selectedRuntimeStatus = computed(() => deploymentRuntimeStatus(selectedDeploymentId.value))
const selectedRuntimeHealth = computed(() => deploymentRuntimeHealth(selectedDeploymentId.value))
const pendingDeleteDeployment = computed(() => {
  const deploymentId = pendingDeleteDeploymentId.value
  return deploymentId ? deployments.value.find((item) => item.deployment_instance_id === deploymentId) ?? null : null
})
const deleteDeploymentDialogMessage = computed(() => {
  const deployment = pendingDeleteDeployment.value
  if (!deployment) return ''
  return t('deploymentOps.messages.deleteConfirm', {
    deploymentId: deployment.deployment_instance_id,
    displayName: deployment.display_name || deployment.deployment_instance_id,
  })
})
const deploymentDeviceOptions = computed(() => buildDeploymentDeviceOptions(
  sessionStore.bootstrap?.devices ?? null,
  selectedDeploymentSource.value?.runtimeBackend ?? '',
))

let skipNextRuntimeModeRefresh = false
let runtimeRefreshSequence = 0
let sourceModelLoadSequence = 0
let sourceModelDetailSequence = 0
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
  if (!deviceName.value) return
  if (!options.some((option) => option.value === deviceName.value)) {
    deviceName.value = ''
  }
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
    errorMessage.value = error instanceof Error ? error.message : '部署来源模型加载失败'
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
    errorMessage.value = error instanceof Error ? error.message : '模型详情加载失败'
  }
}

function applyDeploymentSource(selection: DeploymentSourceSelection): void {
  selectedDeploymentSource.value = selection
  selectedSourceModelId.value = selection.modelId
  modelType.value = selection.modelType
  modelVersionId.value = selection.modelVersionId
  modelBuildId.value = selection.modelBuildId
  runtimeProfileId.value = selection.runtimeProfileId
  selectedTaskType.value = selection.taskType
  if (!buildDeploymentDeviceOptions(sessionStore.bootstrap?.devices ?? null, selection.runtimeBackend).some((option) => option.value === deviceName.value)) {
    deviceName.value = ''
  }
  if (!displayName.value.trim()) {
    const sourceLabel = selection.modelBuildId || selection.modelVersionId
    displayName.value = `${selection.modelName} ${sourceLabel}`
  }
  deploymentSourcePickerOpen.value = false
}

function deploymentSourceUnavailableReason(selection: DeploymentSourceSelection): string {
  const runtimeBackend = selection.runtimeBackend.trim().toLowerCase()
  if (runtimeBackend !== 'tensorrt') {
    return ''
  }
  const devices = sessionStore.bootstrap?.devices ?? null
  if (!hasCudaDevice(devices)) {
    return '当前环境未检测到 NVIDIA CUDA 设备，不能创建 TensorRT deployment'
  }
  const tensorrt = readDeviceRecord(devices, 'tensorrt')
  if (tensorrt?.installed !== true) {
    return '当前环境未安装 TensorRT 运行时，不能创建 TensorRT deployment'
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
  return deploymentRuntimeStatus(item.deployment_instance_id)?.process_state || '未探测'
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
  if (!canWriteModels.value) return '当前账号没有部署写权限'
  if (deploymentRunningAction(item.deployment_instance_id) !== null) return '当前部署实例操作正在执行'
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
  return health ? isRuntimeHealthWarmupComplete(health, item.instance_count) : false
}

function isRuntimeHealthWarmupComplete(health: TaskDeploymentRuntimeHealth, fallbackInstanceCount: number): boolean {
  const expectedInstanceCount = Math.max(0, Number(health.instance_count || fallbackInstanceCount || 0))
  const warmedInstanceCount = Math.max(0, Number(health.warmed_instance_count || 0))
  return expectedInstanceCount > 0 && warmedInstanceCount >= expectedInstanceCount
}

function warmupButtonTitle(item: TaskDeploymentInstance): string {
  if (isDeploymentWarmupComplete(item)) return '已预热完成'
  if (!canWriteModels.value) return '当前账号没有部署写权限'
  if (deploymentRunningAction(item.deployment_instance_id) !== null) return '当前部署实例操作正在执行'
  return '预热部署实例'
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
    errorMessage.value = '请选择部署来源模型'
    return
  }
  const unavailableReason = deploymentSourceUnavailableReason(selectedDeploymentSource.value)
  if (unavailableReason) {
    errorMessage.value = unavailableReason
    return
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
      instanceCount: instanceCount.value,
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
      if (currentHealth && isRuntimeHealthWarmupComplete(currentHealth, deployment?.instance_count ?? 0)) {
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
