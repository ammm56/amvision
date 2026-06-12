<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('trainingDetail.kicker') }}</p>
        <h1>{{ task?.display_name || taskId }}</h1>
        <p class="page-description">{{ t('trainingDetail.description') }}</p>
      </div>
      <div class="page-actions">
        <RouterLink to="/models">{{ t('trainingDetail.actions.backToModels') }}</RouterLink>
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
          <p class="page-kicker">{{ t('trainingDetail.summaryKicker') }}</p>
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
      <div class="table-actions table-actions--wrap">
        <Button
          v-for="action in task.available_actions"
          :key="action"
          size="sm"
          :variant="action === 'terminate' || action === 'delete' ? 'danger' : 'secondary'"
          :disabled="actionRunning !== null"
          @click="runAction(action)"
        >
          <component :is="actionIcon(action)" :size="14" />
          {{ t(`trainingDetail.actions.${action}`) }}
        </Button>
        <Button v-if="taskType === 'detection'" size="sm" variant="ghost" :disabled="!canRegisterCheckpoint || actionRunning !== null" @click="registerCheckpoint">
          <UploadCloud :size="14" />
          {{ t('trainingDetail.actions.registerModelVersion') }}
        </Button>
      </div>
    </section>

    <section v-if="taskType === 'detection'" class="resource-section">
      <div>
        <p class="page-kicker">{{ t('trainingDetail.outputsKicker') }}</p>
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

    <section v-if="task" class="resource-section">
      <div>
        <p class="page-kicker">{{ t('trainingDetail.eventsKicker') }}</p>
        <h2>{{ t('trainingDetail.eventsTitle') }}</h2>
      </div>
      <EmptyState v-if="task.events.length === 0" :title="t('trainingDetail.emptyEventsTitle')" />
      <ol v-else class="event-timeline">
        <li v-for="event in task.events" :key="event.event_id">
          <time>{{ formatSystemDateTime(event.created_at) }}</time>
          <strong>{{ event.event_type }}</strong>
          <span>{{ event.message }}</span>
        </li>
      </ol>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Pause, Play, RefreshCw, Save, Square, Trash2, UploadCloud } from '@lucide/vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  deleteDetectionTrainingTask,
  getDetectionTrainingOutputFileDetail,
  getDetectionTrainingTaskDetail,
  listDetectionTrainingOutputFiles,
  registerDetectionTrainingLatestCheckpoint,
  requestDetectionTrainingTaskAction,
  type DetectionTrainingOutputFileDetail,
  type DetectionTrainingOutputFileSummary,
  type DetectionTrainingTaskActionName,
  type DetectionTrainingTaskDetail,
  type ModelTaskType,
} from '../services/model.service'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const task = ref<DetectionTrainingTaskDetail | null>(null)
const outputFiles = ref<DetectionTrainingOutputFileSummary[]>([])
const selectedOutputFile = ref<DetectionTrainingOutputFileDetail | null>(null)
const loading = ref(false)
const actionRunning = ref<string | null>(null)
const errorMessage = ref<string | null>(null)

const taskId = computed(() => String(route.params.taskId ?? ''))
const taskType = computed<ModelTaskType | null>(() => {
  const value = String(route.params.taskType ?? '')
  return ['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(value)
    ? value as ModelTaskType
    : null
})
const canRegisterCheckpoint = computed(() => Boolean(task.value?.latest_checkpoint_object_key || task.value?.control_status.resume_checkpoint_object_key))
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

function actionIcon(action: DetectionTrainingTaskActionName) {
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
      getDetectionTrainingTaskDetail(currentTaskType, taskId.value),
      currentTaskType === 'detection' ? listDetectionTrainingOutputFiles(currentTaskType, taskId.value) : Promise.resolve([]),
    ])
    task.value = taskDetail
    outputFiles.value = files
    if (!selectedOutputFile.value && files[0]) {
      await selectOutputFile(files[0].file_name)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function runAction(action: DetectionTrainingTaskActionName): Promise<void> {
  if (!taskType.value) {
    errorMessage.value = 'task_type 不能为空'
    return
  }
  const currentTaskType = taskType.value
  if (action === 'delete' && !window.confirm(t('trainingDetail.messages.confirmDelete'))) return
  actionRunning.value = action
  errorMessage.value = null
  try {
    if (action === 'delete') {
      await deleteDetectionTrainingTask(currentTaskType, taskId.value)
      await router.push('/models')
      return
    }
    await requestDetectionTrainingTaskAction(currentTaskType, taskId.value, action)
    await refreshPage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.actionFailed')
  } finally {
    actionRunning.value = null
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
    task.value = await registerDetectionTrainingLatestCheckpoint(currentTaskType, taskId.value)
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
  if (taskType.value !== 'detection') {
    return
  }
  const currentTaskType = taskType.value
  errorMessage.value = null
  try {
    selectedOutputFile.value = await getDetectionTrainingOutputFileDetail(currentTaskType, taskId.value, fileName)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.outputFailed')
  }
}
</script>
