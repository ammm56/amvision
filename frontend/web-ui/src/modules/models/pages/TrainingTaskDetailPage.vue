<template>
  <section class="page-stack">
    <PageHeader :title="task?.display_name || taskId">
      <template #actions>
        <ButtonLink to="/models">
          <ArrowLeft :size="16" />
          {{ t('trainingDetail.actions.backToModels') }}
        </ButtonLink>
        <ButtonLink
          v-if="task"
          :to="`/tasks/${task.task_id}`"
        >
          <Activity :size="16" />
          {{ t('trainingDetail.actions.taskStatus') }}
        </ButtonLink>
        <Button
          v-if="task && canDeleteTask"
          variant="danger"
          :disabled="actionRunning !== null"
          :loading="actionRunning === 'delete'"
          @click="openDeleteDialog"
        >
          <Trash2 :size="16" />
          {{ t('trainingDetail.actions.delete') }}
        </Button>
        <Button variant="secondary" :disabled="loading" :loading="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <InlineError :message="errorMessage" />

    <section v-if="task" class="resource-section">
      <div class="section-heading">
        <div>
          <h2>{{ t('trainingDetail.summaryTitle') }}</h2>
        </div>
        <TaskStateBadge :state="task.state" />
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('trainingDetail.fields.datasetExportId') }}</span>
          <strong>{{ task.dataset_export_id || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.modelVersionId') }}</span>
          <strong>{{ task.model_version_id || task.latest_checkpoint_model_version_id || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.bestMetric') }}</span>
          <strong>{{ task.best_metric_name ? `${task.best_metric_name}: ${task.best_metric_value ?? '-'}` : '-' }}</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.controlStatus') }}</span>
          <strong>{{ task.control_status.status }}</strong>
        </div>
      </div>
      <InlineError v-if="task.error_message" :message="task.error_message" />
      <div class="table-actions table-actions--wrap">
        <Button
          v-for="action in visibleControlActions"
          :key="action"
          size="sm"
          :variant="action === 'terminate' ? 'danger' : 'secondary'"
          :disabled="actionRunning !== null"
          :loading="actionRunning === action"
          @click="runAction(action)"
        >
          <component :is="actionIcon(action)" :size="14" />
          {{ t(`trainingDetail.actions.${action}`) }}
        </Button>
        <Button
          v-if="taskType === 'detection'"
          size="sm"
          variant="secondary"
          :disabled="!canRegisterCheckpoint || actionRunning !== null"
          :loading="actionRunning === 'register-model-version'"
          @click="registerCheckpoint"
        >
          <UploadCloud :size="14" />
          {{ t('trainingDetail.actions.registerModelVersion') }}
        </Button>
      </div>
    </section>

    <section v-if="task" class="resource-section training-progress-section">
      <div class="section-heading">
        <div>
          <h2>{{ t('trainingDetail.progressTitle') }}</h2>
        </div>
      </div>
      <TaskProgress
        :percent="progressPercent"
        :label="t('trainingDetail.progressTitle')"
        :aria-label="t('trainingDetail.progressTitle')"
      />
      <div class="summary-grid training-progress-grid">
        <div>
          <span>{{ t('trainingDetail.fields.stage') }}</span>
          <TaskStateBadge v-if="progressStage !== '-'" :state="progressStage" />
          <strong v-else>-</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.epoch') }}</span>
          <strong>{{ progressEpochText }}</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.learningRate') }}</span>
          <strong>{{ learningRateText }}</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.currentMetric') }}</span>
          <strong>{{ currentMetricText }}</strong>
        </div>
        <div v-if="actualOptimizerText !== '-'">
          <span>{{ t('trainingDetail.fields.optimizer') }}</span>
          <strong>{{ actualOptimizerText }}</strong>
        </div>
        <div v-if="initialLearningRateText !== '-'">
          <span>{{ t('trainingDetail.fields.initialLearningRate') }}</span>
          <strong>{{ initialLearningRateText }}</strong>
        </div>
        <div v-if="finalLearningRateText !== '-'">
          <span>{{ t('trainingDetail.fields.finalLearningRate') }}</span>
          <strong>{{ finalLearningRateText }}</strong>
        </div>
      </div>
      <div class="training-metric-panels">
        <article class="training-metric-panel">
          <div>
            <h3>{{ t('trainingDetail.completedEpochMetricsTitle') }}</h3>
            <p class="training-metric-hint">{{ t('trainingDetail.completedEpochMetricsHint') }}</p>
            <p v-if="showsYoloSpatialLossHint" class="training-metric-hint">
              {{ t('trainingDetail.yoloLossComponentsHint') }}
            </p>
          </div>
          <dl v-if="trainMetricEntries.length > 0" class="training-metric-list">
            <template v-for="metric in trainMetricEntries" :key="metric.name">
              <dt>{{ metric.name }}</dt>
              <dd>{{ metric.value }}</dd>
            </template>
          </dl>
          <span v-else class="training-muted-value">-</span>
        </article>
        <article v-if="batchMetricEntries.length > 0" class="training-metric-panel">
          <div>
            <h3>{{ t('trainingDetail.currentBatchMetricsTitle') }}</h3>
            <p class="training-metric-hint">{{ t('trainingDetail.currentBatchMetricsHint') }}</p>
          </div>
          <dl class="training-metric-list">
            <template v-for="metric in batchMetricEntries" :key="metric.name">
              <dt>{{ metric.name }}</dt>
              <dd>{{ metric.value }}</dd>
            </template>
          </dl>
        </article>
        <article class="training-metric-panel">
          <h3>{{ t('trainingDetail.validationMetricsTitle') }}</h3>
          <dl v-if="validationMetricEntries.length > 0" class="training-metric-list">
            <template v-for="metric in validationMetricEntries" :key="metric.name">
              <dt>{{ metric.name }}</dt>
              <dd>{{ metric.value }}</dd>
            </template>
          </dl>
          <span v-else class="training-muted-value">-</span>
        </article>
        <article v-if="runtimeMetricEntries.length > 0" class="training-metric-panel">
          <div>
            <h3>{{ t('trainingDetail.runtimeMetricsTitle') }}</h3>
            <p class="training-metric-hint">{{ t('trainingDetail.runtimeMetricsHint') }}</p>
          </div>
          <dl class="training-metric-list">
            <template v-for="metric in runtimeMetricEntries" :key="metric.name">
              <dt>{{ metric.name }}</dt>
              <dd>{{ metric.value }}</dd>
            </template>
          </dl>
        </article>
      </div>
      <div class="training-chart-heading">
        <div>
          <h3>{{ t('trainingDetail.charts.title') }}</h3>
          <p>{{ t('trainingDetail.charts.description') }}</p>
        </div>
        <StatusBadge :tone="trainingStreamConnected ? 'success' : 'neutral'">
          {{ trainingStreamConnected ? t('trainingDetail.charts.live') : t('trainingDetail.charts.snapshot') }}
        </StatusBadge>
      </div>
      <p
        v-if="runtimeHistory.length === 0"
        class="training-metric-hint training-runtime-history-status"
      >
        {{ runtimeHistoryEmptyText }}
      </p>
      <TrainingMetricsCharts
        v-if="taskType"
        :task-type="taskType"
        :train-history="trainMetricHistory"
        :validation-history="validationMetricHistory"
        :learning-rate-history="learningRateHistory"
        :runtime-history="runtimeHistory"
        :runtime-empty-text="runtimeHistoryEmptyText"
      />
    </section>

    <section v-if="task" class="resource-section">
      <div>
        <h2>{{ t('trainingDetail.outputsTitle') }}</h2>
      </div>
      <EmptyState v-if="outputFiles.length === 0" :title="t('trainingDetail.emptyOutputsTitle')" :description="t('trainingDetail.emptyOutputsDescription')" />
      <div v-else class="detail-layout">
        <div class="resource-table">
          <table>
            <thead>
              <tr>
                <th>{{ t('trainingDetail.columns.file') }}</th>
                <th>{{ t('trainingDetail.columns.status') }}</th>
                <th>{{ t('trainingDetail.columns.size') }}</th>
                <th>{{ t('trainingDetail.columns.updatedAt') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="file in outputFiles"
                :key="file.file_name"
                :class="{ 'is-selected': file.file_name === selectedOutputFile?.file_name }"
                @click="selectOutputFile(file.file_name)"
              >
                <td>
                  <strong>{{ file.file_name }}</strong>
                  <span>{{ file.object_key || file.file_kind }}</span>
                </td>
                <td><StatusBadge :tone="statusTone(file.file_status)">{{ file.file_status }}</StatusBadge></td>
                <td>{{ file.size_bytes ?? '-' }}</td>
                <td>{{ formatSystemDateTime(file.updated_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <aside class="detail-side">
          <h3>{{ selectedOutputFile?.file_name || t('trainingDetail.outputPreviewTitle') }}</h3>
          <pre class="json-view">{{ selectedOutputContent || t('trainingDetail.messages.noOutputContent') }}</pre>
        </aside>
      </div>
    </section>

    <ConfirmDialog
      v-if="deleteDialogOpen"
      :title="t('trainingDetail.deleteDialog.title')"
      :message="t('common.confirmDelete')"
      :details="t('trainingDetail.messages.confirmDelete')"
      :confirm-label="t('trainingDetail.actions.delete')"
      :cancel-label="t('common.cancel')"
      :busy="actionRunning === 'delete'"
      confirm-variant="danger"
      @cancel="deleteDialogOpen = false"
      @confirm="deleteCurrentTask"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue'
import { Activity, ArrowLeft, Pause, Play, RefreshCw, Save, Square, Trash2, UploadCloud } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  deleteModelTrainingTask,
  getModelTrainingOutputFileDetail,
  getModelTrainingTaskDetail,
  listModelTrainingOutputFiles,
  registerModelTrainingLatestCheckpoint,
  requestModelTrainingTaskAction,
  type ModelTrainingOutputFileDetail,
  type ModelTrainingOutputFileSummary,
  type ModelTrainingTaskActionName,
  type ModelTrainingTaskDetail,
  type ModelTaskType,
} from '../services/model.service'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import TaskProgress from '@/modules/tasks/components/TaskProgress.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { useTaskEvents } from '@/modules/tasks/composables/useTaskEvents'
import type { TaskEvent } from '@/shared/contracts'
import {
  useTrainingTelemetry,
  type TrainingTelemetryPayload,
} from '../composables/useTrainingTelemetry'
import {
  appendTrainingMetricPoint,
  appendTrainingRuntimePoint,
  appendTrainingScalarPoint,
  buildLearningRatePointFromProgress,
  buildMetricPointFromProgress,
  buildRuntimePoint,
  readPersistedLearningRateHistory,
  readPersistedMetricHistory,
  readPersistedRuntimeHistory,
  type TrainingMetricPoint,
  type TrainingRuntimePoint,
  type TrainingScalarPoint,
} from '../training-metric-history'

const TrainingMetricsCharts = defineAsyncComponent(
  () => import('../components/TrainingMetricsCharts.vue'),
)

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const task = ref<ModelTrainingTaskDetail | null>(null)
const outputFiles = ref<ModelTrainingOutputFileSummary[]>([])
const selectedOutputFile = ref<ModelTrainingOutputFileDetail | null>(null)
const loading = ref(false)
const actionRunning = ref<string | null>(null)
const deleteDialogOpen = ref(false)
const errorMessage = ref<string | null>(null)
const trainingMetricsPayload = ref<Record<string, unknown>>({})
const validationMetricsPayload = ref<Record<string, unknown>>({})
const runtimeMetricsPayload = ref<Record<string, unknown>>({})
const trainMetricHistory = ref<TrainingMetricPoint[]>([])
const validationMetricHistory = ref<TrainingMetricPoint[]>([])
const learningRateHistory = ref<TrainingScalarPoint[]>([])
const runtimeHistory = ref<TrainingRuntimePoint[]>([])
const latestTaskEventCursor = ref<string | null>(null)
let snapshotRefreshTimer: ReturnType<typeof window.setTimeout> | null = null
let outputFilesRefreshTimer: ReturnType<typeof window.setTimeout> | null = null

const taskId = computed(() => String(route.params.taskId ?? ''))
const taskType = computed<ModelTaskType | null>(() => {
  const value = String(route.params.taskType ?? '')
  return ['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(value)
    ? value as ModelTaskType
    : null
})
const visibleControlActions = computed(() => task.value?.available_actions.filter((action) => action !== 'delete') ?? [])
const showsYoloSpatialLossHint = computed(() => (
  ['yolov8', 'yolo11', 'yolo26'].includes(String(task.value?.model_type ?? '').toLowerCase())
  && ['detection', 'segmentation', 'pose', 'obb'].includes(String(taskType.value ?? ''))
))
const canDeleteTask = computed(() => task.value?.available_actions.includes('delete') ?? false)
const canRegisterCheckpoint = computed(() => Boolean(task.value?.latest_checkpoint_object_key || task.value?.control_status.resume_checkpoint_object_key))
const progressSnapshot = computed(() => task.value?.progress ?? {})
const progressPercent = computed(() => readNumber(progressSnapshot.value.percent))
const progressStage = computed(() => formatPlainValue(progressSnapshot.value.stage))
const progressEpochText = computed(() => {
  const epoch = readNumber(progressSnapshot.value.epoch)
  const maxEpochs = readNumber(progressSnapshot.value.max_epochs)
  if (epoch === null && maxEpochs === null) return '-'
  return `${epoch ?? '-'} / ${maxEpochs ?? '-'}`
})
const learningRateText = computed(() => formatMetricValue(progressSnapshot.value.learning_rate))
const optimizerPayload = computed(() => readRecord(trainingMetricsPayload.value.optimizer))
const actualOptimizerText = computed(() => formatPlainValue(
  optimizerPayload.value?.name ?? trainingMetricsPayload.value.optimizer,
))
const initialLearningRateText = computed(() => formatMetricValue(
  trainingMetricsPayload.value.initial_learning_rate
    ?? optimizerPayload.value?.initial_learning_rate,
))
const finalLearningRateText = computed(() => formatMetricValue(
  trainingMetricsPayload.value.final_learning_rate
    ?? optimizerPayload.value?.final_learning_rate,
))
const currentMetricText = computed(() => {
  const name = formatPlainValue(progressSnapshot.value.current_metric_name)
  const value = formatMetricValue(progressSnapshot.value.current_metric_value)
  if (name === '-' && value === '-') return bestMetricText.value
  return `${name}: ${value}`
})
const bestMetricText = computed(() => {
  const name = task.value?.best_metric_name || formatPlainValue(progressSnapshot.value.best_metric_name)
  const value = task.value?.best_metric_value ?? progressSnapshot.value.best_metric_value
  if (!name || name === '-') return '-'
  return `${name}: ${formatMetricValue(value)}`
})
const completedEpochMetrics = computed(() => {
  const persistedMetrics = readRecord(trainingMetricsPayload.value.final_metrics)
  if (Object.keys(persistedMetrics).length > 0) return persistedMetrics
  return readRecord(progressSnapshot.value.train_metrics)
})
const trainMetricEntries = computed(() => buildMetricEntries(completedEpochMetrics.value))
const batchMetricEntries = computed(() => {
  const explicitBatchMetrics = readRecord(progressSnapshot.value.batch_metrics)
  return buildMetricEntries(explicitBatchMetrics)
})
const validationMetricEntries = computed(() => buildMetricEntries(progressSnapshot.value.validation_metrics))
const runtimeMetricEntries = computed(() => buildRuntimeMetricEntries(progressSnapshot.value.runtime))
const selectedOutputContent = computed(() => {
  const outputFile = selectedOutputFile.value
  if (!outputFile) return ''
  if (outputFile.file_kind === 'text') return outputFile.text_content || outputFile.lines.join('\n')
  if (Object.keys(outputFile.payload).length > 0) return JSON.stringify(outputFile.payload, null, 2)
  return outputFile.object_key || ''
})
const taskEvents = useTaskEvents(
  () => taskId.value,
  handleTaskEvent,
  () => latestTaskEventCursor.value,
)
const trainingTelemetry = useTrainingTelemetry(
  () => taskId.value,
  handleTrainingTelemetry,
  scheduleSnapshotRefresh,
)
const trainingStreamConnected = computed(() => (
  trainingTelemetry.streamState.value?.connected === true
))
const runtimeHistoryEmptyText = computed(() => {
  if (runtimeHistory.value.length > 0) return t('common.noValue')
  const runtimeFile = outputFiles.value.find((file) => file.file_name === 'runtime-metrics')
  return !isActiveTrainingState(task.value?.state) && runtimeFile?.file_status !== 'ready'
    ? t('trainingDetail.charts.legacyRuntimeUnavailable')
    : t('trainingDetail.charts.runtimePending')
})

onMounted(async () => {
  await refreshPage()
})

onBeforeUnmount(() => {
  if (snapshotRefreshTimer !== null) {
    window.clearTimeout(snapshotRefreshTimer)
    snapshotRefreshTimer = null
  }
  if (outputFilesRefreshTimer !== null) {
    window.clearTimeout(outputFilesRefreshTimer)
    outputFilesRefreshTimer = null
  }
})

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('success') || normalized.includes('succeed') || normalized.includes('ready')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error') || normalized.includes('terminate')) return 'danger'
  if (normalized.includes('queue') || normalized.includes('pending') || normalized.includes('pause')) return 'warning'
  if (normalized.includes('run') || normalized.includes('process') || normalized.includes('save')) return 'info'
  return 'neutral'
}

function actionIcon(action: ModelTrainingTaskActionName) {
  if (action === 'save') return Save
  if (action === 'pause') return Pause
  if (action === 'resume') return Play
  if (action === 'terminate') return Square
  return Trash2
}

async function refreshPage(): Promise<void> {
  if (!taskType.value) {
    errorMessage.value = t('trainingDetail.messages.taskTypeRequired')
    return
  }
  const currentTaskType = taskType.value
  loading.value = true
  errorMessage.value = null
  try {
    const [taskDetail, files] = await Promise.all([
      getModelTrainingTaskDetail(currentTaskType, taskId.value),
      listModelTrainingOutputFiles(currentTaskType, taskId.value),
    ])
    task.value = taskDetail
    latestTaskEventCursor.value = buildLatestTaskEventCursor(taskDetail.events)
    outputFiles.value = files
    const metricsFile = files.find((file) => file.file_name === 'train-metrics')
    const validationMetricsFile = files.find((file) => file.file_name === 'validation-metrics')
    const runtimeMetricsFile = files.find((file) => file.file_name === 'runtime-metrics')
    const [trainMetricsDetail, validationMetricsDetail, runtimeMetricsDetail] = await Promise.all([
      metricsFile
        ? getModelTrainingOutputFileDetail(currentTaskType, taskId.value, metricsFile.file_name)
        : Promise.resolve(null),
      validationMetricsFile
        ? getModelTrainingOutputFileDetail(currentTaskType, taskId.value, validationMetricsFile.file_name)
        : Promise.resolve(null),
      runtimeMetricsFile?.file_status === 'ready'
        ? getModelTrainingOutputFileDetail(currentTaskType, taskId.value, runtimeMetricsFile.file_name)
        : Promise.resolve(null),
    ])
    trainingMetricsPayload.value = trainMetricsDetail?.payload ?? {}
    validationMetricsPayload.value = validationMetricsDetail?.payload ?? {}
    runtimeMetricsPayload.value = runtimeMetricsDetail?.payload ?? {}
    mergePersistedHistories()
    appendProgressHistory(taskDetail.progress)
    taskDetail.events.forEach((event) => {
      appendProgressHistory(readRecord(event.payload).progress)
    })
    const selectedFileName = selectedOutputFile.value?.file_name
    const nextFileName = files.some((file) => file.file_name === selectedFileName)
      ? selectedFileName
      : files[0]?.file_name
    selectedOutputFile.value = null
    if (nextFileName) {
      await selectOutputFile(nextFileName)
    }
    syncTaskEventSubscription()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function runAction(action: ModelTrainingTaskActionName): Promise<void> {
  if (!taskType.value) {
    errorMessage.value = t('trainingDetail.messages.taskTypeRequired')
    return
  }
  if (action === 'delete') {
    openDeleteDialog()
    return
  }
  const currentTaskType = taskType.value
  actionRunning.value = action
  errorMessage.value = null
  try {
    await requestModelTrainingTaskAction(currentTaskType, taskId.value, action)
    await refreshPage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.actionFailed')
  } finally {
    actionRunning.value = null
  }
}

function handleTaskEvent(event: TaskEvent): void {
  const data = readRecord(event.payload)
  const progress = readRecord(data.progress)
  const shouldApplySnapshot = shouldApplyTaskEventSnapshot(data, progress)
  const shouldApplyCompletedEpoch = shouldApplySnapshot
    || shouldApplyRecentCompletedEpochMetrics(progress)
  if (task.value && Object.keys(data).length > 0 && shouldApplySnapshot) {
    const nextState = typeof data.state === 'string' ? data.state : task.value.state
    const nextBestMetricName = typeof progress.best_metric_name === 'string'
      ? progress.best_metric_name
      : task.value.best_metric_name
    const nextBestMetricValue = readNumber(progress.best_metric_value) ?? task.value.best_metric_value
    task.value = {
      ...task.value,
      state: nextState,
      progress: { ...task.value.progress, ...progress },
      result: { ...task.value.result, ...readRecord(data.result) },
      metadata: { ...task.value.metadata, ...readRecord(data.metadata) },
      best_metric_name: nextBestMetricName,
      best_metric_value: nextBestMetricValue,
    }
  }
  if (task.value && shouldApplyCompletedEpoch) {
    const nextBestMetricName = typeof progress.best_metric_name === 'string'
      ? progress.best_metric_name
      : task.value.best_metric_name
    const nextBestMetricValue = readNumber(progress.best_metric_value)
      ?? task.value.best_metric_value
    task.value = {
      ...task.value,
      best_metric_name: nextBestMetricName,
      best_metric_value: nextBestMetricValue,
    }
    mergeCompletedEpochMetricPayloads(progress)
  }
  appendProgressHistory(progress)
  if (event.event_type === 'result' || event.event_type === 'status') {
    scheduleSnapshotRefresh()
  }
  if (shouldApplySnapshot && !isActiveTrainingState(task.value?.state)) {
    taskEvents.stop()
    trainingTelemetry.stop()
  }
}

function shouldApplyRecentCompletedEpochMetrics(
  incomingProgress: Record<string, unknown>,
): boolean {
  const trainMetrics = readRecord(incomingProgress.train_metrics)
  const validationMetrics = readRecord(incomingProgress.validation_metrics)
  if (Object.keys(trainMetrics).length === 0 && Object.keys(validationMetrics).length === 0) {
    return false
  }
  const incomingEpoch = readNumber(incomingProgress.epoch)
  if (incomingEpoch === null) return false
  const persistedEpoch = Math.max(
    readNumber(trainingMetricsPayload.value.epoch) ?? -1,
    readNumber(validationMetricsPayload.value.epoch) ?? -1,
  )
  if (incomingEpoch <= persistedEpoch) return false
  const currentEpoch = readNumber(task.value?.progress.epoch)
  return currentEpoch === null || incomingEpoch >= currentEpoch - 1
}

function mergeCompletedEpochMetricPayloads(progress: Record<string, unknown>): void {
  const trainMetrics = readRecord(progress.train_metrics)
  if (Object.keys(trainMetrics).length > 0) {
    trainingMetricsPayload.value = {
      ...trainingMetricsPayload.value,
      epoch: readNumber(progress.epoch) ?? trainingMetricsPayload.value.epoch,
      epoch_index: readNumber(progress.epoch_index) ?? trainingMetricsPayload.value.epoch_index,
      max_epochs: readNumber(progress.max_epochs) ?? trainingMetricsPayload.value.max_epochs,
      final_metrics: trainMetrics,
    }
  }
  const validationMetrics = readRecord(progress.validation_metrics)
  if (Object.keys(validationMetrics).length > 0) {
    validationMetricsPayload.value = {
      ...validationMetricsPayload.value,
      epoch: readNumber(progress.epoch) ?? validationMetricsPayload.value.epoch,
      epoch_index: readNumber(progress.epoch_index) ?? validationMetricsPayload.value.epoch_index,
      max_epochs: readNumber(progress.max_epochs) ?? validationMetricsPayload.value.max_epochs,
      final_metrics: validationMetrics,
    }
  }
}

function handleTrainingTelemetry(payload: TrainingTelemetryPayload): void {
  const currentTask = task.value
  if (currentTask === null || payload.task_id !== currentTask.task_id) return
  if (payload.attempt_no < currentTask.current_attempt_no) return
  const currentEpoch = readNumber(currentTask.progress.epoch)
  if (currentEpoch !== null && payload.epoch !== null && payload.epoch !== undefined) {
    if (payload.epoch < currentEpoch) return
  }
  const nextProgress: Record<string, unknown> = {
    ...currentTask.progress,
    stage: payload.stage,
    granularity: payload.granularity,
  }
  assignTelemetryValue(nextProgress, 'percent', payload.progress_percent)
  assignTelemetryValue(nextProgress, 'epoch', payload.epoch)
  assignTelemetryValue(nextProgress, 'epoch_index', payload.epoch_index)
  assignTelemetryValue(nextProgress, 'max_epochs', payload.max_epochs)
  assignTelemetryValue(nextProgress, 'iteration', payload.step)
  assignTelemetryValue(nextProgress, 'max_iterations', payload.steps_per_epoch)
  assignTelemetryValue(nextProgress, 'global_iteration', payload.global_step)
  assignTelemetryValue(nextProgress, 'total_iterations', payload.total_steps)
  assignTelemetryValue(nextProgress, 'input_size', payload.input_size)
  assignTelemetryValue(nextProgress, 'learning_rate', payload.learning_rate)
  if (payload.granularity === 'batch') nextProgress.batch_metrics = payload.metrics
  if (Object.keys(payload.runtime).length > 0) nextProgress.runtime = payload.runtime
  runtimeHistory.value = appendTrainingRuntimePoint(
    runtimeHistory.value,
    buildRuntimePoint(
      payload.global_step,
      payload.timestamp,
      payload.runtime,
      payload.attempt_no,
    ),
  )
  task.value = {
    ...currentTask,
    current_attempt_no: Math.max(currentTask.current_attempt_no, payload.attempt_no),
    progress: nextProgress,
  }
  if (
    payload.epoch !== null
    && payload.epoch !== undefined
    && (currentEpoch === null || payload.epoch > currentEpoch)
  ) {
    scheduleOutputFilesRefresh()
  }
}

function assignTelemetryValue(
  target: Record<string, unknown>,
  name: string,
  value: unknown,
): void {
  if (value !== null && value !== undefined) target[name] = value
}

function shouldApplyTaskEventSnapshot(
  data: Record<string, unknown>,
  incomingProgress: Record<string, unknown>,
): boolean {
  const currentTask = task.value
  if (currentTask === null) return true
  const incomingAttempt = readNumber(data.attempt_no)
  if (incomingAttempt !== null && incomingAttempt < currentTask.current_attempt_no) {
    return false
  }
  const incomingState = typeof data.state === 'string' ? data.state : null
  if (!isActiveTrainingState(currentTask.state) && isActiveTrainingState(incomingState)) {
    return false
  }
  const currentProgress = currentTask.progress
  const currentGlobalStep = readNumber(
    currentProgress.global_step ?? currentProgress.global_iteration,
  )
  const incomingGlobalStep = readNumber(
    incomingProgress.global_step ?? incomingProgress.global_iteration,
  )
  if (
    currentGlobalStep !== null
    && incomingGlobalStep !== null
    && incomingGlobalStep < currentGlobalStep
  ) {
    return false
  }
  const currentEpoch = readNumber(currentProgress.epoch)
  const incomingEpoch = readNumber(incomingProgress.epoch)
  return currentEpoch === null || incomingEpoch === null || incomingEpoch >= currentEpoch
}

function buildLatestTaskEventCursor(
  events: ModelTrainingTaskDetail['events'],
): string | null {
  const latestEvent = [...events].sort((left, right) => (
    left.created_at.localeCompare(right.created_at)
    || left.event_id.localeCompare(right.event_id)
  )).at(-1)
  return latestEvent ? `${latestEvent.created_at}|${latestEvent.event_id}` : null
}

function isActiveTrainingState(state: string | null | undefined): boolean {
  return state === 'queued' || state === 'running'
}

function syncTaskEventSubscription(): void {
  if (isActiveTrainingState(task.value?.state)) {
    taskEvents.start()
    trainingTelemetry.start()
    return
  }
  taskEvents.stop()
  trainingTelemetry.stop()
}

function appendProgressHistory(value: unknown): void {
  const progress = readRecord(value)
  if (Object.keys(progress).length === 0) return
  trainMetricHistory.value = appendTrainingMetricPoint(
    trainMetricHistory.value,
    buildMetricPointFromProgress(progress, 'train_metrics'),
  )
  validationMetricHistory.value = appendTrainingMetricPoint(
    validationMetricHistory.value,
    buildMetricPointFromProgress(progress, 'validation_metrics'),
  )
  learningRateHistory.value = appendTrainingScalarPoint(
    learningRateHistory.value,
    buildLearningRatePointFromProgress(progress),
  )
}

function mergePersistedHistories(): void {
  readPersistedMetricHistory(trainingMetricsPayload.value).forEach((point) => {
    trainMetricHistory.value = appendTrainingMetricPoint(trainMetricHistory.value, point)
  })
  readPersistedMetricHistory(validationMetricsPayload.value).forEach((point) => {
    validationMetricHistory.value = appendTrainingMetricPoint(validationMetricHistory.value, point)
  })
  readPersistedLearningRateHistory(trainingMetricsPayload.value).forEach((point) => {
    learningRateHistory.value = appendTrainingScalarPoint(learningRateHistory.value, point)
  })
  readPersistedRuntimeHistory(runtimeMetricsPayload.value).forEach((point) => {
    runtimeHistory.value = appendTrainingRuntimePoint(runtimeHistory.value, point)
  })
}

function scheduleSnapshotRefresh(): void {
  if (snapshotRefreshTimer !== null) return
  snapshotRefreshTimer = window.setTimeout(() => {
    snapshotRefreshTimer = null
    void refreshPage()
  }, 300)
}

function scheduleOutputFilesRefresh(): void {
  if (outputFilesRefreshTimer !== null) return
  outputFilesRefreshTimer = window.setTimeout(() => {
    outputFilesRefreshTimer = null
    void refreshOutputFiles()
  }, 300)
}

async function refreshOutputFiles(): Promise<void> {
  if (!taskType.value) return
  const currentTaskType = taskType.value
  try {
    const files = await listModelTrainingOutputFiles(currentTaskType, taskId.value)
    outputFiles.value = files
    const selectedFileName = selectedOutputFile.value?.file_name
    if (selectedFileName && files.some((file) => file.file_name === selectedFileName)) {
      selectedOutputFile.value = await getModelTrainingOutputFileDetail(
        currentTaskType,
        taskId.value,
        selectedFileName,
      )
    }
  } catch {
    // 后台状态同步失败不覆盖页面已有数据，后续 epoch 或手动刷新会再次获取。
  }
}

function openDeleteDialog(): void {
  deleteDialogOpen.value = true
}

async function deleteCurrentTask(): Promise<void> {
  if (!taskType.value) {
    errorMessage.value = t('trainingDetail.messages.taskTypeRequired')
    return
  }
  const currentTaskType = taskType.value
  actionRunning.value = 'delete'
  errorMessage.value = null
  try {
    await deleteModelTrainingTask(currentTaskType, taskId.value)
    await router.push('/models')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.actionFailed')
  } finally {
    actionRunning.value = null
    deleteDialogOpen.value = false
  }
}

async function registerCheckpoint(): Promise<void> {
  if (!taskType.value) {
    errorMessage.value = t('trainingDetail.messages.taskTypeRequired')
    return
  }
  if (taskType.value !== 'detection') {
    errorMessage.value = t('trainingDetail.messages.registerDetectionOnly')
    return
  }
  const currentTaskType = taskType.value
  actionRunning.value = 'register-model-version'
  errorMessage.value = null
  try {
    task.value = await registerModelTrainingLatestCheckpoint(currentTaskType, taskId.value)
    await refreshPage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.registerFailed')
  } finally {
    actionRunning.value = null
  }
}

async function selectOutputFile(fileName: string): Promise<void> {
  if (!taskType.value) {
    errorMessage.value = t('trainingDetail.messages.taskTypeRequired')
    return
  }
  const currentTaskType = taskType.value
  errorMessage.value = null
  try {
    selectedOutputFile.value = await getModelTrainingOutputFileDetail(currentTaskType, taskId.value, fileName)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.outputFailed')
  }
}

function buildMetricEntries(value: unknown): Array<{ name: string; value: string }> {
  const metrics = readRecord(value)
  return Object.entries(metrics)
    .filter(([, metricValue]) => metricValue !== null && metricValue !== undefined)
    .map(([name, metricValue]) => ({ name, value: formatMetricValue(metricValue) }))
}

function buildRuntimeMetricEntries(value: unknown): Array<{ name: string; value: string }> {
  const runtime = readRecord(value)
  const orderedNames = [
    'device',
    'batch_size',
    'batch_resolution_mode',
    'oom_recovery_count',
    'samples_per_second',
    'steps_per_second',
    'step_time_ms',
    'forward_loss_host_time_ms',
    'backward_optimizer_host_time_ms',
    'batch_compute_host_time_ms',
    'epoch_elapsed_seconds',
    'elapsed_seconds',
    'estimated_remaining_seconds',
    'gpu_utilization_percent',
    'gpu_memory_used_percent',
    'gpu_memory_allocated_bytes',
    'gpu_memory_reserved_bytes',
  ]
  return orderedNames.flatMap((name) => {
    const runtimeValue = runtime[name]
    if (runtimeValue === null || runtimeValue === undefined) return []
    return [{ name, value: formatRuntimeValue(name, runtimeValue) }]
  })
}

function formatRuntimeValue(name: string, value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return formatPlainValue(value)
  if (name.endsWith('_bytes')) return `${(value / (1024 ** 3)).toFixed(3)} GiB`
  if (name.endsWith('_percent')) return `${Number(value.toFixed(2))}%`
  if (name === 'step_time_ms' || name.endsWith('_time_ms')) return `${Number(value.toFixed(2))} ms`
  if (name.endsWith('_seconds')) return `${Number(value.toFixed(1))} s`
  if (name.endsWith('_per_second')) return Number(value.toFixed(2)).toString()
  return formatMetricValue(value)
}

function readRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return {}
}

function readNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return null
}

function formatMetricValue(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (Number.isInteger(value)) return String(value)
    return String(Number(value.toFixed(6)))
  }
  return formatPlainValue(value)
}

function formatPlainValue(value: unknown): string {
  if (typeof value === 'string' && value.trim()) return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return '-'
}
</script>

<style scoped>
.training-progress-section {
  gap: 14px;
}

.training-progress-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.training-metric-panels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.training-metric-panel {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  background: var(--am-surface-soft);
  border: 1px solid var(--am-border);
  border-radius: 8px;
}

.training-metric-panel h3 {
  margin: 0;
  color: var(--am-text);
  font-size: 13px;
}

.training-chart-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-top: 4px;
}

.training-chart-heading h3,
.training-chart-heading p {
  margin: 0;
}

.training-chart-heading h3 {
  color: var(--am-text);
  font-size: 14px;
}

.training-chart-heading p {
  margin-top: 4px;
  color: var(--am-text-muted);
  font-size: 12px;
}

.training-metric-hint {
  margin: 4px 0 0;
  color: var(--am-text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.training-metric-list {
  display: grid;
  grid-template-columns: minmax(0, 1fr) max-content;
  gap: 7px 12px;
  margin: 0;
}

.training-metric-list dt,
.training-metric-list dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.training-metric-list dt {
  color: var(--am-text-muted);
}

.training-metric-list dd {
  color: var(--am-text);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.training-muted-value {
  color: var(--am-text-muted);
  font-weight: 700;
}

@media (max-width: 960px) {
  .training-progress-grid,
  .training-metric-panels {
    grid-template-columns: 1fr;
  }
}
</style>
