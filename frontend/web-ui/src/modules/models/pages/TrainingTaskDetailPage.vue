<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <h1>{{ task?.display_name || taskId }}</h1>
        <p class="page-description">{{ t('trainingDetail.description') }}</p>
      </div>
      <div class="page-actions">
        <ButtonLink to="/models">
          <ArrowLeft :size="16" />
          {{ t('trainingDetail.actions.backToModels') }}
        </ButtonLink>
        <ButtonLink
          v-if="task"
          :to="`/tasks/${task.task_id}`"
        >
          <Activity :size="16" />
          任务状态
        </ButtonLink>
        <Button
          v-if="task && canDeleteTask"
          variant="danger"
          :disabled="actionRunning !== null"
          @click="openDeleteDialog"
        >
          <Trash2 :size="16" />
          {{ t('trainingDetail.actions.delete') }}
        </Button>
        <Button variant="secondary" :disabled="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <section v-if="task" class="resource-section">
      <div class="section-heading">
        <div>
          <h2>{{ t('trainingDetail.summaryTitle') }}</h2>
        </div>
        <StatusBadge :tone="statusTone(task.state)">{{ task.state }}</StatusBadge>
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
        <strong class="training-progress-percent">{{ progressPercentText }}</strong>
      </div>
      <div class="training-progress-track" role="progressbar" :aria-valuenow="progressPercent ?? undefined" aria-valuemin="0" aria-valuemax="100">
        <span :style="{ width: progressBarWidth }" />
      </div>
      <div class="summary-grid training-progress-grid">
        <div>
          <span>{{ t('trainingDetail.fields.stage') }}</span>
          <strong>{{ progressStage }}</strong>
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
      </div>
      <div class="training-metric-panels">
        <article class="training-metric-panel">
          <h3>{{ t('trainingDetail.trainMetricsTitle') }}</h3>
          <dl v-if="trainMetricEntries.length > 0" class="training-metric-list">
            <template v-for="metric in trainMetricEntries" :key="metric.name">
              <dt>{{ metric.name }}</dt>
              <dd>{{ metric.value }}</dd>
            </template>
          </dl>
          <span v-else class="training-muted-value">-</span>
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
      </div>
    </section>

    <section v-if="task" class="resource-section">
      <div>
        <h2>{{ t('trainingDetail.outputsTitle') }}</h2>
      </div>
      <EmptyState v-if="!loading && outputFiles.length === 0" :title="t('trainingDetail.emptyOutputsTitle')" :description="t('trainingDetail.emptyOutputsDescription')" />
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
import { computed, onMounted, ref } from 'vue'
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
import { formatSystemDateTime } from '@/shared/formatters/date-time'

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

const taskId = computed(() => String(route.params.taskId ?? ''))
const taskType = computed<ModelTaskType | null>(() => {
  const value = String(route.params.taskType ?? '')
  return ['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(value)
    ? value as ModelTaskType
    : null
})
const visibleControlActions = computed(() => task.value?.available_actions.filter((action) => action !== 'delete') ?? [])
const canDeleteTask = computed(() => task.value?.available_actions.includes('delete') ?? false)
const canRegisterCheckpoint = computed(() => Boolean(task.value?.latest_checkpoint_object_key || task.value?.control_status.resume_checkpoint_object_key))
const progressSnapshot = computed(() => task.value?.progress ?? {})
const progressPercent = computed(() => readNumber(progressSnapshot.value.percent))
const progressPercentText = computed(() => progressPercent.value === null ? '-' : `${progressPercent.value.toFixed(1)}%`)
const progressBarWidth = computed(() => `${Math.min(100, Math.max(0, progressPercent.value ?? 0))}%`)
const progressStage = computed(() => formatPlainValue(progressSnapshot.value.stage))
const progressEpochText = computed(() => {
  const epoch = readNumber(progressSnapshot.value.epoch)
  const maxEpochs = readNumber(progressSnapshot.value.max_epochs)
  if (epoch === null && maxEpochs === null) return '-'
  return `${epoch ?? '-'} / ${maxEpochs ?? '-'}`
})
const learningRateText = computed(() => formatMetricValue(progressSnapshot.value.learning_rate))
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
const trainMetricEntries = computed(() => buildMetricEntries(progressSnapshot.value.train_metrics))
const validationMetricEntries = computed(() => buildMetricEntries(progressSnapshot.value.validation_metrics))
const selectedOutputContent = computed(() => {
  const outputFile = selectedOutputFile.value
  if (!outputFile) return ''
  if (outputFile.file_kind === 'text') return outputFile.text_content || outputFile.lines.join('\n')
  if (Object.keys(outputFile.payload).length > 0) return JSON.stringify(outputFile.payload, null, 2)
  return outputFile.object_key || ''
})

onMounted(() => {
  void refreshPage()
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
    errorMessage.value = 'task_type 不能为空'
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
    outputFiles.value = files
    const selectedFileName = selectedOutputFile.value?.file_name
    const nextFileName = files.some((file) => file.file_name === selectedFileName)
      ? selectedFileName
      : files[0]?.file_name
    selectedOutputFile.value = null
    if (nextFileName) {
      await selectOutputFile(nextFileName)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function runAction(action: ModelTrainingTaskActionName): Promise<void> {
  if (!taskType.value) {
    errorMessage.value = 'task_type 不能为空'
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

function openDeleteDialog(): void {
  deleteDialogOpen.value = true
}

async function deleteCurrentTask(): Promise<void> {
  if (!taskType.value) {
    errorMessage.value = 'task_type 不能为空'
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
    errorMessage.value = 'task_type 不能为空'
    return
  }
  if (taskType.value !== 'detection') {
    errorMessage.value = 'register-model-version 当前只用于 detection 训练任务'
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
    errorMessage.value = 'task_type 不能为空'
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

.training-progress-percent {
  color: var(--accent-strong);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}

.training-progress-track {
  height: 8px;
  overflow: hidden;
  background: var(--surface-muted);
  border: 1px solid var(--line);
  border-radius: 999px;
}

.training-progress-track span {
  display: block;
  height: 100%;
  background: var(--accent);
  border-radius: inherit;
  transition: width 160ms ease;
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
  background: var(--summary-bg);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.training-metric-panel h3 {
  margin: 0;
  color: var(--text);
  font-size: 13px;
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
  color: var(--muted);
}

.training-metric-list dd {
  color: var(--text);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.training-muted-value {
  color: var(--muted);
  font-weight: 700;
}

@media (max-width: 960px) {
  .training-progress-grid,
  .training-metric-panels {
    grid-template-columns: 1fr;
  }
}
</style>
